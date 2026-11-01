"""Offline, read-only attribution of Raydium Trade API quote refusals to venues.

LaunchLab curve trading and routed AMM swaps are distinct price sources.
A Trade API `INSUFFICIENT_LIQUIDITY` response does not independently prove
the on-chain bonding curve is unsellable. Pool status is observed from a
snapshot, not a migration proof or a trade execution receipt.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.p3.quotes import SOL_MINT
from bot.p3.curve_quote_audit import curve_exit_diagnostics
from bot.p3.store import CaptureStore


def _exact_byte(value):
    if type(value) is int and 0 <= value <= 255:
        return value
    if type(value) is str and value.isdecimal() and len(value) <= 3:
        decoded = int(value)
        return decoded if decoded <= 255 else None
    return None


def _analyzed_stage(events):
    observations = []
    for e in events:
        if e.get("kind") != "candidate_decision":
            continue
        payload = e.get("payload")
        if type(payload) is not dict or type(payload.get("analysis")) is not dict:
            continue
        analysis = payload["analysis"]
        facts = analysis.get("facts")
        if type(facts) is not dict:
            continue
        pool, config = facts.get("pool"), facts.get("config")
        if type(pool) is not dict:
            continue
        status = _exact_byte(pool.get("status"))
        curve_type = _exact_byte(config.get("curve_type")) if type(config) is dict else None
        native_sol = pool.get("mint_b") == SOL_MINT
        identity = facts.get("identity_certification")
        certified = bool(type(identity) is dict
            and identity.get("program_derived_addresses_verified") is True
            and identity.get("account_discriminators_verified") is True)
        if status is None:
            stage = "unknown"
        elif status == 0:
            stage = "launchlab_curve_active_status_observed"
        else:
            stage = "launchlab_curve_not_active_migration_not_verified"
        observations.append(dict(
            phase=payload.get("probe_phase"),
            source_slot=e.get("source_slot"),
            available_at_ms=e.get("available_at_ms"),
            stage=stage,
            raw_status=status,
            curve_type=curve_type,
            native_sol=native_sol,
            account_identity_verified=certified,
            local_curve_projection_available=type(analysis.get("conditional_projection")) is dict,
            blocking_reasons=analysis.get("blocking_reasons")
                if type(analysis.get("blocking_reasons")) is list else [],
        ))
    return observations


def venue_audit(events, *, expected_tail):
    """Audit every frozen prefix candidate; no retroactive winner selection."""
    if (type(events) is not list or not events or type(expected_tail) is not str
            or events[-1].get("record_hash") != expected_tail
            or len({e.get("id") for e in events}) != len(events)):
        raise ValueError("Verified immutable capture tail is required")
    prefixes = [e for e in events if e.get("kind") == "checkpoint"
                and e.get("outcome") == "prospective_prefix_fixed"]
    if len(prefixes) != 1:
        raise ValueError("One frozen candidate prefix required")
    candidates = prefixes[0].get("payload", {}).get("candidates")
    if type(candidates) is not list:
        raise ValueError("Missing immutable candidate prefix")
    cases = []
    counts = Counter()
    for ordinal, candidate in enumerate(candidates):
        if (type(candidate) is not dict or candidate.get("ordinal") != ordinal
                or type(candidate.get("mint")) is not str):
            raise ValueError("Invalid frozen candidate order")
        mint = candidate["mint"]
        related = [e for e in events if e.get("mint") == mint
                   and e["id"] > prefixes[0]["id"]]
        stages = _analyzed_stage(related)
        initial = next((s for s in stages if s["phase"] == "initial"), None)
        stage = initial["stage"] if initial is not None else "unknown"
        responses = []
        failures = Counter()
        for e in related:
            if e.get("kind") != "quote_attempt":
                continue
            p = e.get("payload")
            if (type(p) is not dict or p.get("provider") != "raydium_trade_api"
                    or p.get("quote_side") != "sell"):
                continue
            refusal = p.get("retained_sanitized_response")
            code = refusal.get("msg") if type(refusal) is dict else None
            if not (type(code) is str and 0 < len(code) <= 100
                    and all(c.isupper() or c.isdigit() or c == "_" for c in code)):
                code = None
            if e.get("outcome") == "unavailable":
                failures[code or e.get("reason") or "unavailable"]=(
                    failures[code or e.get("reason") or "unavailable"] + 1)
            responses.append(dict(id=e.get("id"),outcome=e.get("outcome"),
                phase=p.get("probe_phase"),scope=p.get("exit_scope"),
                provider_response_code=code,quote_kind=p.get("quote_kind"),
                exit_execution_verified=False))
        initial_refused = any(q["phase"] == "initial"
            and q["scope"] == "full_expected" and q["outcome"] == "unavailable"
            for q in responses)
        plausible_gap = bool(stage == "launchlab_curve_active_status_observed"
            and initial_refused)
        curve_diagnostics=curve_exit_diagnostics(events,mint)
        # Missing follow-up banks, insufficient observed curve circulation and
        # unsupported layouts remain distinct. Do not aggregate them into
        # a misleading claim of market illiquidity.
        reasons=Counter(item.get('reason','reason_unknown') for item in curve_diagnostics
                        if item.get('curve_estimate_available') is not True)
        if not curve_diagnostics:
            reasons['no_projected_inventory_or_curve_diagnostic']=1
        counts[stage]+=1
        cases.append(dict(ordinal=ordinal,mint=mint,stage=stage,
            stage_observations=stages,trade_api_sell_observations=responses,
            trade_api_refusal_counts=dict(sorted(failures.items())),
            active_curve_trade_api_coverage_gap_plausible=plausible_gap,
            observed_curve_sell_diagnostics=curve_diagnostics,
            observed_curve_sell_unqualified_reasons=dict(sorted(reasons.items())),
            observed_curve_sell_estimates=sum(1 for item in curve_diagnostics
                 if item.get('curve_estimate_available') is True),
            trade_api_refusal_proves_onchain_illiquidity=False,
            migration_verified=False,full_exit_executable_proven=False,
            settled_position=False,net_pnl_sol=None))
    return dict(schema="p3-venue-coverage-audit-v1",source_tail_hash=expected_tail,
        selected_tokens=len(candidates),stage_counts=dict(sorted(counts.items())),
        active_curve_trade_api_coverage_gap_candidates=sum(
            c["active_curve_trade_api_coverage_gap_plausible"] for c in cases),
        trade_api_refusal_proves_onchain_illiquidity=False,
        observed_curve_sell_estimates=sum(c['observed_curve_sell_estimates'] for c in cases),
        observed_curve_sell_unqualified_reason_counts=dict(sorted(
            sum((Counter(c['observed_curve_sell_unqualified_reasons']) for c in cases),
                Counter()).items())),
        curve_sell_basis='observed_bank_conditional_without_projected_own_buy_not_executable',
        venue_aware_executable_cycle_count=0,
        strategy_profitability_verified=False,live_ready_to_arm=False,
        financial_order_submitted=False,cases=cases)


def replay(db_path, output_path):
    source, dest = Path(db_path), Path(output_path)
    if (not source.is_file() or source.is_symlink() or dest.exists()
            or dest.is_symlink() or dest.suffix != ".json"
            or source.resolve() == dest.resolve()):
        raise ValueError("Require existing capture and new separate JSON output")
    with CaptureStore(source, readonly=True) as store:
        anchor=store.verify_integrity()
        report=venue_audit(store.events(),expected_tail=anchor)
    atomic_write_json(dest,report,indent=2,sort_keys=True,allow_nan=False)
    return dict(report=str(dest),selected_tokens=report["selected_tokens"],
        stage_counts=report["stage_counts"],
        active_curve_trade_api_coverage_gap_candidates=report[
            "active_curve_trade_api_coverage_gap_candidates"],
        observed_curve_sell_estimates=report['observed_curve_sell_estimates'],
        observed_curve_sell_unqualified_reason_counts=report['observed_curve_sell_unqualified_reason_counts'],
        venue_aware_executable_cycle_count=0,
        strategy_profitability_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(replay(args.db,args.output),sort_keys=True))


if __name__=="__main__":
    main()

"""First-page on-chain LaunchLab SOL cohort, strictly prospective and read-only.

The Helius paged scan is limited to the first 64 active survivor accounts;
the 12 candidate pubkeys are selected before reading any root account. The
selection uses only mint, creator, quote mint and account graph identity from
roots, never the root price or future S2 outcome. S1 and S2 share each own
coherent getMultipleAccounts response. No user wallet/order/signing or LIVE.
This is NOT a representative creation cohort: survivors + first page only.
"""
import json
import os
import sys
import time

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_active_launchlab_scan import discover_live_pool_account_page
from bot.p3.helius_index_prospective_cohort import _bank,_hash,BUY_LAMPORTS
from bot.p3.launchlab import _pool,addresses_from_pool,analyze_snapshot,observed_sell_projection,SnapshotEvidenceError
from bot.p3.quotes import SOL_MINT
from bot.p3.cohort import _uint as _checked_integer

MAX_SELECTED=3
WAIT_SECONDS=12
RESEARCH_LADDER_LAMPORTS=(5_000_000,10_000_000,25_000_000,50_000_000,100_000_000,250_000_000,1_000_000_000)


def _canonical_uint(value):
    """Rehydrate exact JSON-safe SDK integers; reject non-canonical strings."""
    if type(value) is str:
        if not value.isdecimal() or str(int(value)) != value:
            raise ValueError("noncanonical_snapshot_integer")
    return _checked_integer(value)


def _followup_sell_from_snapshot(analysis,exact_quantity):
    """Project only when identity/permissions remain valid at the S2 bank.

    analyze_snapshot returns _json_safe numeric fields as strings. The curve
    routine intentionally requires true integers; rehydrate each explicit
    quantity with lossless, bounded validation before calling it.
    """
    if (type(analysis) is not dict or analysis.get("risk_flags") != []
            or analysis.get("evidence_profile") != "published_metadata_v1"):
        raise ValueError("s2_snapshot_risk_flags_or_schema_invalid")
    facts=analysis["facts"]
    pool=facts["pool"];cfg=facts["config"];platform=facts["platform"]
    status=_canonical_uint(pool["status"])
    if status != 0:
        raise ValueError("s2_pool_not_active")
    numeric_pool=dict(pool)
    for key in ("virtual_a","virtual_b","real_a","real_b",
                "protocol_fee_accrued","platform_fee_accrued","status"):
        numeric_pool[key]=_canonical_uint(pool[key])
    return observed_sell_projection(numeric_pool,
        input_token_atomic=_canonical_uint(exact_quantity),
        fee_rates_ppm=tuple(_canonical_uint(rate) for rate in (
            cfg["trade_fee_rate_ppm"],platform["platform_fee_rate_ppm"],
            platform["creator_fee_rate_ppm"])),
        quote_vault_lamports=_canonical_uint(facts["quote_vault"]["amount_atomic"]),
        curve_type=_canonical_uint(cfg["curve_type"]),
        share_fee_rate_ppm=_canonical_uint(facts.get("share_fee_assumption_ppm","0")))


def observe_active_survivor_cohort(rpc,*,wait_seconds=WAIT_SECONDS,sleep=time.sleep,research_ladder=False,prefer_root_activity=False,freeze_at_s1=None):
    if (not callable(rpc) or type(wait_seconds) is not int or not 1<=wait_seconds<=20 or type(research_ladder) is not bool or type(prefer_root_activity) is not bool
            or (freeze_at_s1 is not None and not callable(freeze_at_s1))):
        raise ValueError("active_readonly_cohort_bounds_required")
    scan=discover_live_pool_account_page(rpc)
    candidates=scan["initial_pools_before_price"]
    if not candidates:
        return dict(status="NO_ACTIVE_SOL_POOLS_ON_FIRST_PAGE",
                    scan=scan,financial_order_submitted=False,live_ready_to_arm=False)
    root_slot,roots=_bank(rpc,candidates,scan["scan_slot"])
    selected=[];denominator=[];seen_creator=set();seen_mint=set()
    for i,pool_id in enumerate(candidates):
        verdict="unusable_root"
        try:
            pool,_raw=_pool(roots[pool_id])
            mint=pool["mint_a"];creator=pool["creator"]
            if pool["mint_b"]!=SOL_MINT or pool["status"]!=0:
                verdict="not_active_SOL_pool"
            elif (prefer_root_activity and
                  (type(pool.get("real_a")) is not int or pool["real_a"]<=0
                   or type(pool.get("real_b")) is not int or pool["real_b"]<=0)):
                verdict="no_observed_root_outstanding_tokens_and_SOL_reserve"
            elif creator in seen_creator or mint in seen_mint:
                verdict="duplicate_creator_or_mint"
            elif len(selected)>=MAX_SELECTED:
                verdict="outside_fixed_pre_S1_three_creator_sample"
            else:
                graph=addresses_from_pool(roots[pool_id],mint,pool_id)
                if len(set(graph.values()))!=7:
                    raise ValueError("duplicate_account_graph")
                selected.append(dict(pool=pool_id,mint=mint,
                    creator_claim=creator,addresses=graph,source_index=i))
                seen_creator.add(creator);seen_mint.add(mint)
                verdict="selected_before_S1"
        except (KeyError,ValueError,TypeError,AttributeError):
            pass
        denominator.append(dict(pool=pool_id,selection_reason=verdict,
             source_index=i))
    registration=dict(
        schema="rugger-onchain-active-survivor-S1S2-v1",
        scan_slot=scan["scan_slot"],
        account_universe_sha256=scan["observed_universe_sha256"],
        sampled_pool_sha256=_hash(candidates),
        selected_identity=[dict(pool=r["pool"],mint=r["mint"],
              creator_claim=r["creator_claim"]) for r in selected],
        denominator=denominator,entry_lamports=BUY_LAMPORTS,
        sample_scope="first_v2_page_active_survivors_only",
        no_frozen_trade_decisions=True,
        root_activity_filter_preregistered=prefer_root_activity,
        root_activity_filter="real_a_positive_and_real_b_positive_only_before_S1" if prefer_root_activity else "none",
        global_creation_universe_representative=False)
    registration_sha256=_hash(registration)
    print(json.dumps(dict(phase="FROZEN_ACTIVE_SURVIVOR_SELECTION_BEFORE_S1",
        registration_sha256=registration_sha256,
        selected_count=len(selected),root_slot=root_slot,
        financial_order_submitted=False),sort_keys=True),flush=True)
    observations=[];bank1_slot=None;bank2_slot=None
    preregistered_research_freeze=None
    if selected:
        keys=list(dict.fromkeys(
            k for r in selected for k in r["addresses"].values()))
        if len(keys)>21:
            raise ValueError("active_cohort_too_many_accounts")
        bank1_slot,b1=_bank(rpc,keys,root_slot)
        by_mint={}
        for row in selected:
            rec=dict(mint=row["mint"],pool=row["pool"],
                     creator_claim=row["creator_claim"],s1_slot=bank1_slot,
                     signed_creation_verified=False,position_acquired=False)
            try:
                analysis=analyze_snapshot(
                    {k:b1[k] for k in row["addresses"].values()},
                    context_slot=bank1_slot,expected_mint=row["mint"],
                    pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                    evidence_profile="published_metadata_v1")
                by_mint[row["mint"]]=analysis
                rec["s1_analysis_sha256"]=_hash(analysis)
                rec["s1_blocking_reasons"]=analysis["blocking_reasons"]
                entry=analysis.get("conditional_projection")
                rec["s1_buy_quantity_atomic"]=(
                    entry.get("buy_output_atomic") if type(entry) is dict else None)
                rec["s1_buy_projection_model_only"]=type(entry) is dict
                if research_ladder:
                    # All sizes are preregistered; their S1 exact quantities freeze before S2.
                    rec["research_size_ladder"]=[]
                    for amount in RESEARCH_LADDER_LAMPORTS:
                        test=analyze_snapshot({k:b1[k] for k in row["addresses"].values()},
                            context_slot=bank1_slot,expected_mint=row["mint"],pool_address=row["pool"],
                            input_lamports=amount,evidence_profile="published_metadata_v1")
                        proj=test.get("conditional_projection")
                        eligible=(test.get("risk_flags")==[] and type(proj) is dict
                            and type(proj.get("buy_output_atomic")) is str
                            and proj["buy_output_atomic"].isdecimal()
                            and int(proj["buy_output_atomic"])>0)
                        rec["research_size_ladder"].append(dict(
                            entry_lamports=str(amount),
                            s1_exact_buy_quantity_atomic=proj["buy_output_atomic"] if eligible else None,
                            s1_projection_research_only=eligible,
                            s1_blocking_reasons=test.get("blocking_reasons",[]),
                            s1_risk_flags=test.get("risk_flags",[]),
                            s1_analysis_sha256=_hash(test),
                            s2_conditional_sell_lamports=None,
                            s2_conditional_gross_markout_lamports=None,
                            observed_execution=False))
                    rec["research_size_ladder_frozen_S1_sha256"]=_hash(rec["research_size_ladder"])
            except (ValueError,KeyError,TypeError,AttributeError):
                rec["s1_refusal"]="unverifiable_account_bundle"
            observations.append(rec)
        print(json.dumps(dict(phase="S1_OBSERVED_BEFORE_S2",slot=bank1_slot,
            partial_records=len(observations),
            frozen_selection_sha256=registration_sha256,
            actual_buy_sell_cycles=0),sort_keys=True),flush=True)
        # Strictly BEFORE any sleep or follow-up bank read. A custom research
        # scorer sees ONLY frozen pool identities and S1 account analyses.
        # No historical creation signature or quote-execution claim is made.
        if freeze_at_s1 is not None:
            from copy import deepcopy
            s1clock=time.time_ns()//1_000_000
            frozen_input=dict(registration_sha256=registration_sha256,
                s1_slot=bank1_slot,s1_received_at_ms=s1clock,
                selected_before_S1=[dict(pool=r["pool"],mint=r["mint"],
                    creator_claim=r["creator_claim"]) for r in selected],
                s1_observations=[dict(row=deepcopy(rec),
                    s1_analysis=deepcopy(by_mint.get(rec["mint"])))
                    for rec in observations])
            frozen_receipt=freeze_at_s1(deepcopy(frozen_input))
            if (type(frozen_receipt) is not dict or
                    frozen_receipt.get("s1_registration_sha256")!=registration_sha256
                    or frozen_receipt.get("s1_slot")!=bank1_slot or
                    frozen_receipt.get("future_S2_used") is not False or
                    frozen_receipt.get("financial_order_submitted") is not False):
                raise ValueError("unqualified_pre_S2_research_freeze")
            preregistered_research_freeze=deepcopy(frozen_receipt)
            print(json.dumps(dict(phase="S1_RESEARCH_FREEZE_BEFORE_S2",
                freeze_sha256=_hash(frozen_receipt),
                selected_count=len(selected),financial_order_submitted=False),
                sort_keys=True),flush=True)
        sleep(wait_seconds)
        bank2_slot,b2=_bank(rpc,keys,bank1_slot+1)
        for rec in observations:
            quantity=rec.get("s1_buy_quantity_atomic")
            if type(quantity) is not str or not quantity.isdecimal() or not int(quantity):
                rec["s2_refusal"]="no_exact_S1_modelled_buy_inventory"
                continue
            row=next(r for r in selected if r["mint"]==rec["mint"])
            try:
                analysis=analyze_snapshot(
                    {k:b2[k] for k in row["addresses"].values()},
                    context_slot=bank2_slot,expected_mint=row["mint"],
                    pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                    evidence_profile="published_metadata_v1",
                    compute_projection=False)
                f=analysis["facts"]
                pool=f["pool"];config=f["config"];platform=f["platform"]
                # Distinguish genuine pool migration/close from a decoder
                # security refusal; NEVER waive a risk flag to produce profit.
                observed_flags=analysis.get("risk_flags")
                rec["s2_pool_status"]=pool.get("status")
                rec["s2_risk_flags"]=(
                    [flag for flag in observed_flags if type(flag) is str
                     and len(flag)<=85 and flag.replace("_","").isalnum()][:12]
                    if type(observed_flags) is list else ["unreadable_risk_flags"])
                rec["s2_blocking_reasons"]=(
                    [x for x in analysis.get("blocking_reasons",[])
                     if type(x) is str and len(x)<=85
                     and x.replace("_","").isalnum()][:15])
                if observed_flags!=[]:
                    raise ValueError("S2_permissions_or_active_status_invalid")
                sell=_followup_sell_from_snapshot(analysis,quantity)
                received=int(sell["output_lamports"])
                rec.update(s2_slot=bank2_slot,s2_analysis_sha256=_hash(analysis),
                    conditional_sell_lamports=received,
                    conditional_gross_markout_lamports=received-BUY_LAMPORTS,
                    own_network_fee_known=False,
                    projection_scope="exact_S1_modeled_quantity_against_S2_observed_reserves",
                    execution_verified=False,strict_economic_cycle_qualified=False)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                code=str(exc)
                # Only local parser/curve refusal codes are emitted. No raw
                # HTTP body or auth material is ever exposed.
                known_prefixes=("invalid_","unsupported_","sell_","S2_","s2_",
                    "insufficient_","three_","noncanonical_",
                    "observed_","active_","pool_","vault_","invalid_curve_",
                    "curve_","quote_","base_","token_","fee_","snapshot_")
                safe=(code if isinstance(exc,(ValueError,SnapshotEvidenceError)) and len(code)<100
                    and code.replace("_","").isalnum()
                    and code.startswith(known_prefixes)
                    else type(exc).__name__)
                rec["s2_refusal"]="insufficient_supported_real_S2_exit_evidence"
                rec["s2_refusal_diagnostic"]=safe
        if research_ladder:
            for rec in observations:
                ladder=rec.get("research_size_ladder")
                if type(ladder) is not list:
                    continue
                item=next(r for r in selected if r["mint"]==rec["mint"])
                try:
                    # Coherent S2 bank is new; never change frozen S1 quantities.
                    s2=analyze_snapshot({k:b2[k] for k in item["addresses"].values()},
                        context_slot=bank2_slot,expected_mint=item["mint"],pool_address=item["pool"],
                        input_lamports=BUY_LAMPORTS,evidence_profile="published_metadata_v1",
                        compute_projection=False)
                    for row in ladder:
                        qty=row["s1_exact_buy_quantity_atomic"]
                        if qty is None:
                            row["s2_refusal"]="S1_model_unavailable_or_risky";continue
                        try:
                            quote=_followup_sell_from_snapshot(s2,qty)
                            proceeds=_canonical_uint(quote["output_lamports"])
                            row["s2_conditional_sell_lamports"]=str(proceeds)
                            row["s2_conditional_gross_markout_lamports"]=str(proceeds-int(row["entry_lamports"]))
                            row["conditional_costs_observed"]=False
                            row["economic_cycle_qualified"]=False
                        except (SnapshotEvidenceError,ValueError,KeyError,TypeError):
                            row["s2_refusal"]="exact_lot_S2_curve_or_capacity_refused"
                except (SnapshotEvidenceError,ValueError,KeyError,TypeError):
                    for row in ladder:
                        row["s2_refusal"]="S2_bank_or_identity_unqualified"
    return dict(schema="rugger-onchain-active-survivor-S1S2-v1",
        status="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
        registration_sha256=registration_sha256,
        scan_slot=scan["scan_slot"],root_slot=root_slot,
        first_bank_slot=bank1_slot,second_bank_slot=bank2_slot,
        page_size=scan["observed_active_SOL_pools_in_one_page"],
        additional_pages_exist=scan["further_pages_exist"],
        discovery_denominator=denominator,
        selected_count=len(selected),observations=observations,
        financial_orders_submitted=0,
        strict_qualified_economic_cycles=0,
        independently_verified_creation_creators=0,
        holdout_verified=False,representative_creation_universe=False,
        no_historical_survivor_bias_control=True,
        master_vs_reference_edge_demonstrated=False,
        research_size_ladder_enabled=research_ladder,
        preregistered_research_freeze=preregistered_research_freeze,
        S1_research_freeze_before_S2_sha256=(
            _hash(preregistered_research_freeze)
            if preregistered_research_freeze is not None else None),
        root_activity_filter_enabled=prefer_root_activity,
        research_size_ladder_lamports=list(RESEARCH_LADDER_LAMPORTS) if research_ladder else None,
        research_sizes_are_not_independent_creators=True,
        live_ready_to_arm=False,financial_order_submitted=False,
        rpc_calls_used=getattr(rpc,"count",None))

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-size-ladder",action="store_true")
    parser.add_argument("--prefer-root-activity",action="store_true")
    args=parser.parse_args()
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_required")
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=6,
                                           allow_active_pool_scan=True)
        report=observe_active_survivor_cohort(rpc,research_ladder=args.research_size_ladder,
            prefer_root_activity=args.prefer_root_activity)
    except Exception as exc:
        code=str(exc)
        safe=code if type(exc) is ValueError and len(code)<100 and code.replace("_","").isalnum() else type(exc).__name__
        report=dict(status="REFUSED",reason=safe,
            last_rpc_method=(rpc.last_method if rpc else None),
            last_numeric_RPC_error_code=(rpc.last_rpc_error_code if rpc else None),
            financial_order_submitted=False,live_ready_to_arm=False)
    if report.get("status") in ("ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE", "NO_ACTIVE_SOL_POOLS_ON_FIRST_PAGE",):
        from bot.p3.readonly_evidence_archive import archive_from_github_actions
        archive_info=archive_from_github_actions(report,kind="active_survivor_cohort")
        if archive_info is not None:
            print(json.dumps(dict(phase="PUBLIC_PAPER_EVIDENCE_ARTIFACT",
                evidence_sha256=archive_info["observation_sha256"],
                financial_order_submitted=False),sort_keys=True))
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"] in ("ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
                                     "NO_ACTIVE_SOL_POOLS_ON_FIRST_PAGE") else 2

if __name__=="__main__":
    sys.exit(main())

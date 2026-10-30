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
from bot.p3.launchlab import _pool,addresses_from_pool,analyze_snapshot,observed_sell_projection
from bot.p3.quotes import SOL_MINT

MAX_SELECTED=3
WAIT_SECONDS=12

def observe_active_survivor_cohort(rpc,*,wait_seconds=WAIT_SECONDS,sleep=time.sleep):
    if not callable(rpc) or type(wait_seconds) is not int or not 1<=wait_seconds<=20:
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
        global_creation_universe_representative=False)
    registration_sha256=_hash(registration)
    print(json.dumps(dict(phase="FROZEN_ACTIVE_SURVIVOR_SELECTION_BEFORE_S1",
        registration_sha256=registration_sha256,
        selected_count=len(selected),root_slot=root_slot,
        financial_order_submitted=False),sort_keys=True),flush=True)
    observations=[];bank1_slot=None;bank2_slot=None
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
            except (ValueError,KeyError,TypeError,AttributeError):
                rec["s1_refusal"]="unverifiable_account_bundle"
            observations.append(rec)
        print(json.dumps(dict(phase="S1_OBSERVED_BEFORE_S2",slot=bank1_slot,
            partial_records=len(observations),
            frozen_selection_sha256=registration_sha256,
            actual_buy_sell_cycles=0),sort_keys=True),flush=True)
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
                if observed_flags!=[] or pool["status"]!=0:
                    raise ValueError("S2_permissions_or_active_status_invalid")
                sell=observed_sell_projection(pool,
                    input_token_atomic=int(quantity),
                    fee_rates_ppm=(config["trade_fee_rate_ppm"],
                        platform["platform_fee_rate_ppm"],
                        platform["creator_fee_rate_ppm"]),
                    quote_vault_lamports=int(f["quote_vault"]["amount_atomic"]),
                    curve_type=config["curve_type"])
                received=int(sell["output_lamports"])
                rec.update(s2_slot=bank2_slot,s2_analysis_sha256=_hash(analysis),
                    conditional_sell_lamports=received,
                    conditional_gross_markout_lamports=received-BUY_LAMPORTS,
                    own_network_fee_known=False,
                    execution_verified=False,strict_economic_cycle_qualified=False)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                code=str(exc)
                # Only local parser/curve refusal codes are emitted. No raw
                # HTTP body or auth material is ever exposed.
                known_prefixes=("invalid_","unsupported_","sell_","S2_",
                    "observed_","active_","pool_","vault_","invalid_curve_",
                    "curve_","quote_","base_","token_","fee_","snapshot_")
                safe=(code if type(exc) is ValueError and len(code)<100
                    and code.replace("_","").isalnum()
                    and code.startswith(known_prefixes)
                    else type(exc).__name__)
                rec["s2_refusal"]="insufficient_supported_real_S2_exit_evidence"
                rec["s2_refusal_diagnostic"]=safe
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
        live_ready_to_arm=False,financial_order_submitted=False,
        rpc_calls_used=getattr(rpc,"count",None))

def main():
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_required")
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=6,
                                           allow_active_pool_scan=True)
        report=observe_active_survivor_cohort(rpc)
    except Exception as exc:
        code=str(exc)
        safe=code if type(exc) is ValueError and len(code)<100 and code.replace("_","").isalnum() else type(exc).__name__
        report=dict(status="REFUSED",reason=safe,
            last_rpc_method=(rpc.last_method if rpc else None),
            last_numeric_RPC_error_code=(rpc.last_rpc_error_code if rpc else None),
            financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"] in ("ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE",
                                     "NO_ACTIVE_SOL_POOLS_ON_FIRST_PAGE") else 2

if __name__=="__main__":
    sys.exit(main())

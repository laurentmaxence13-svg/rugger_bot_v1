"""No-fee MAINNET S1-capacity-screened then future-S2 conditional quote test.

Uses the first Helius V2 page of *active survivors* only, never a complete
creation denominator. S1 is a public source snapshot, not a purchased lot.
No future S2 information may affect S1 selection. No real trading authority.
"""
import json
import os
import sys
import time

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_active_launchlab_scan import discover_live_pool_account_page
from bot.live.helius_active_launchlab_cohort import _followup_sell_from_snapshot
from bot.p3.helius_index_prospective_cohort import _bank, _hash, BUY_LAMPORTS
from bot.p3.launchlab import _pool, addresses_from_pool, analyze_snapshot
from bot.p3.quotes import SOL_MINT

MAX_CANDIDATES=12
MAX_S2=3
WAIT_SECONDS=12


def screened_s1_capacity_then_s2(rpc, *, sleep=time.sleep, wait_seconds=WAIT_SECONDS):
    if not callable(rpc) or type(wait_seconds) is not int or not 1<=wait_seconds<=20:
        raise ValueError("strict_s1_S2_cohort_bounds_required")
    scan=discover_live_pool_account_page(rpc)
    candidates=scan["initial_pools_before_price"]
    if len(candidates)>MAX_CANDIDATES:
        raise ValueError("oversized_preregistered_pool_prefix")
    if not candidates:
        return dict(status="NO_ACTIVE_POOLS_IN_PRESELECTED_PAGE",
            financial_order_submitted=False,live_ready_to_arm=False)
    roots_slot,root_accounts=_bank(rpc,candidates,scan["scan_slot"])
    prepared=[]
    rejected=[]
    for i,address in enumerate(candidates):
        try:
            raw,_=_pool(root_accounts[address])
            mint,creator=raw["mint_a"],raw["creator"]
            if raw["status"]!=0 or raw["mint_b"]!=SOL_MINT:
                raise ValueError("not_active_native_SOL_curve")
            graph=addresses_from_pool(root_accounts[address],mint,address)
            if len(set(graph.values()))!=7:
                raise ValueError("nonunique_program_graph")
            prepared.append(dict(source_index=i,pool=address,mint=mint,
                                 creator_claim=creator,graph=graph))
        except (ValueError,KeyError,TypeError,AttributeError):
            rejected.append(dict(source_index=i,pool=address,
                                 reason="root_not_supported"))
    # Commit complete candidate list before ANY seven-account source pricing.
    preregister=dict(schema="rugger-S1-capacity-then-S2-v1",
       scan_slot=scan["scan_slot"],page_sha256=scan["observed_universe_sha256"],
       exact_candidate_pools=candidates,roots_slot=roots_slot,
       source_index_root_exclusions=rejected,
       fixed_input_lamports=BUY_LAMPORTS,
       capacity_selection_rule="S1_exact_buy_and_observed_S1_sell_capacity",
       selected_S2_limit=MAX_S2,
       no_selection_using_S2_or_future_trades=True)
    reg_hash=_hash(preregister)
    print(json.dumps(dict(phase="FROZEN_POOL_PREFIX_BEFORE_S1",
        registration_sha256=reg_hash,pools=len(candidates),
        financial_order_submitted=False),sort_keys=True),flush=True)
    observed=[]
    s1_eligible=[]
    for start in range(0,len(prepared),3):
        group=prepared[start:start+3]
        keys=list(dict.fromkeys(k for row in group
                                for k in row["graph"].values()))
        if not 1<=len(keys)<=21:
            raise ValueError("S1_group_cardinality_invalid")
        bank_slot,bank=_bank(rpc,keys,roots_slot)
        for row in group:
            item=dict(source_index=row["source_index"],pool=row["pool"],
                      mint=row["mint"],creator_claim=row["creator_claim"],
                      S1_slot=bank_slot,S1_buy_lamports=BUY_LAMPORTS,
                      S1_model_only=True,real_orders_submitted=0)
            try:
                analysis=analyze_snapshot(
                    {k:bank[k] for k in row["graph"].values()},
                    context_slot=bank_slot,expected_mint=row["mint"],
                    pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                    evidence_profile="published_metadata_v1")
                item["S1_sha256"]=_hash(analysis)
                quantity=(analysis.get("conditional_projection") or {}).get(
                    "buy_output_atomic")
                item["S1_buy_quantity_atomic"]=quantity
                if type(quantity) is not str or not quantity.isdecimal() or int(quantity)==0:
                    item["S1_capacity_reason"]="no_modelled_buy_quantity"
                else:
                    output=_followup_sell_from_snapshot(analysis,quantity)
                    item["S1_capacity_available"]=True
                    item["S1_sell_lamports"]=output["output_lamports"]
                    s1_eligible.append(dict(row,quantity=quantity,
                          S1_slot=bank_slot))
            except (ValueError,TypeError,KeyError,AttributeError):
                item["S1_capacity_reason"]="no_observed_exact_lot_sell_capacity"
            observed.append(item)
    selected=[];seen_creator=set()
    for row in s1_eligible:
        if row["creator_claim"] in seen_creator:continue
        if len(selected)>=MAX_S2:break
        selected.append(row);seen_creator.add(row["creator_claim"])
    decision=dict(registration_sha256=reg_hash,
       selected=[dict(pool=r["pool"],mint=r["mint"],
                     creator_claim=r["creator_claim"],quantity=r["quantity"],
                     S1_slot=r["S1_slot"]) for r in selected],
       selection_based_on_S1_only=True,
       s1_eligible_count=len(s1_eligible),
       S2_slot_min=(max(r["S1_slot"] for r in selected)+1
                    if selected else None))
    decision_hash=_hash(decision)
    print(json.dumps(dict(phase="S1_SCREENED_SELECTION_FROZEN_BEFORE_S2",
        s1_eligible_count=len(s1_eligible),
        selected_for_S2=len(selected),decision_sha256=decision_hash,
        financial_order_submitted=False),sort_keys=True),flush=True)
    s2_slot=None
    if selected:
        sleep(wait_seconds)
        keys=list(dict.fromkeys(k for row in selected
                               for k in row["graph"].values()))
        s2_slot,bank=_bank(rpc,keys,decision["S2_slot_min"])
        for row in selected:
            item=next(x for x in observed if x["pool"]==row["pool"])
            item["S2_slot"]=s2_slot
            try:
                analysis=analyze_snapshot(
                   {k:bank[k] for k in row["graph"].values()},
                   context_slot=s2_slot,expected_mint=row["mint"],
                   pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                   evidence_profile="published_metadata_v1",
                   compute_projection=False)
                item["S2_sha256"]=_hash(analysis)
                output=_followup_sell_from_snapshot(analysis,row["quantity"])
                amount=int(output["output_lamports"])
                item.update(S2_conditional_sell_lamports=amount,
                    S2_conditional_gross_markout_lamports=amount-BUY_LAMPORTS,
                    strict_economic_cycle_qualified=False,
                    S2_execution_verified=False)
            except (ValueError,TypeError,KeyError,AttributeError) as error:
                item["S2_refusal"]="exact_modelled_lot_not_qualifiable_at_S2"
                item["S2_refusal_class"]=type(error).__name__
    return dict(schema="rugger-S1-capacity-then-S2-v1",
      status="PREDECLARED_S1_CAPACITY_SAMPLE_RECORDED",
      source="first_page_active_survivors_only_not_creation_history",
      input_lamports=BUY_LAMPORTS,scan_slot=scan["scan_slot"],
      roots_slot=roots_slot,S2_slot=s2_slot,registration_sha256=reg_hash,
      S1_decision_sha256=decision_hash,
      candidates_before_S1=len(candidates),
      source_root_rejections=rejected,
      S1_screened_count=len(observed),S1_capacity_count=len(s1_eligible),
      selected_for_S2=len(selected),results=observed,
      S2_conditional_sell_quotes=sum("S2_conditional_sell_lamports" in r
                                     for r in observed),
      S2_refusals=sum("S2_refusal" in r for r in observed),
      creator_signatures_verified=0,
      independent_holdout_creators_verified=0,
      real_buy_sell_trades=0,
      strict_market_economic_cycles=0,
      representative_creation_universe=False,
      master_vs_reference_edge_validated=False,
      financial_order_submitted=False,live_ready_to_arm=False,
      rpc_calls_used=getattr(rpc,"count",None))


def main():
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_missing")
        rpc=HeliusReadOnlyRpc.from_environment(
            max_calls=10,allow_active_pool_scan=True)
        result=screened_s1_capacity_then_s2(rpc)
    except Exception as error:
        value=str(error)
        safe=(value if type(error) is ValueError and len(value)<90
              and value.replace("_","").isalnum()
              else type(error).__name__)
        result=dict(status="REFUSED",reason=safe,
            last_rpc_method=rpc.last_method if rpc else None,
            last_rpc_error_code=rpc.last_rpc_error_code if rpc else None,
            financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"] in (
        "PREDECLARED_S1_CAPACITY_SAMPLE_RECORDED",
        "NO_ACTIVE_POOLS_IN_PRESELECTED_PAGE") else 2

if __name__=="__main__":
    sys.exit(main())

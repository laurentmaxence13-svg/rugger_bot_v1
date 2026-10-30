"""Preregistered INDEX-FIRST LaunchLab independent-creator screening on mainnet.

The public Raydium 'new' index supplies only an untrusted discovery universe.
Up to three unique-creator SOL pools are selected BEFORE any account-bank
retrieval. S1 exact seven-account bank is captured, a fixed 12-second pause
occurs, then a fresh S2 bank is requested. Missing/migrated/nonconstant
product/unsupported-token accounts are REFUSED, never silently dropped.
Quotes are modeled by the pinned LaunchLab SDK arithmetic, not executable
buys/sells. No signatures, wallets, trading or strategy promotion.
"""
import hashlib
import json
import os
import ssl
import sys
import time
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError

from bot.p3.campaign import INDEX_URL
from bot.p3.quotes import SOL_MINT, _mint
from bot.p3.launchlab import addresses_from_pool,analyze_snapshot,observed_sell_projection,SnapshotEvidenceError
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS

SELECTION_LIMIT=3
DISCOVERY_LIMIT=100
BUY_LAMPORTS=10_000_000
WAIT_SECONDS=12

class NoIndexRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("raydium_index_redirect_forbidden")

def _hash(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(",",":"),
                                   allow_nan=False).encode()).hexdigest()

def fetch_index(*,opener=None):
    opener=opener or build_opener(ProxyHandler({}),
       HTTPSHandler(context=ssl.create_default_context()),NoIndexRedirect())
    # Exact official endpoint from existing campaign, no credentials, no cookies.
    uri=INDEX_URL+"?sort=new"
    req=Request(uri,method="GET",headers={"Accept":"application/json"})
    try:
        with opener.open(req,timeout=8) as response:
            if response.status!=200 or response.geturl()!=uri:
                raise ValueError("raydium_index_status_or_redirect_refused")
            raw=response.read(1_000_001)
    except HTTPError as exc:
        raise ValueError("raydium_index_http_status_"+str(exc.code)) from None
    if len(raw)>1_000_000:
        raise ValueError("raydium_index_maximum_response_size_exceeded")
    data=json.loads(raw)
    if type(data) is not dict or data.get("success") is not True:
        raise ValueError("raydium_index_unexpected_envelope")
    rows=data.get("data",{}).get("rows")
    if type(rows) is not list or len(rows)>DISCOVERY_LIMIT*100:
        raise ValueError("raydium_index_rows_invalid")
    return rows[:DISCOVERY_LIMIT]

def _address(v):
    try:return _mint(v)
    except (ValueError,TypeError):return None

def register_prebank_universe(rows):
    if type(rows) is not list or len(rows)>DISCOVERY_LIMIT:
        raise ValueError("exact_bounded_index_rows_required")
    selected=[];denominator=[];seen_mints=set();seen_pools=set();seen_creators=set()
    for i,raw in enumerate(rows):
        row=raw if type(raw) is dict else {}
        quote=row.get("mintB")
        mint=_address(row.get("mint"));pool=_address(row.get("poolId"))
        creator=_address(row.get("creator"))
        quoted=_address(quote.get("address") if type(quote) is dict else None)
        reason="selected"
        if not mint or not pool or not creator or quoted!=SOL_MINT or mint==SOL_MINT:
            reason="unsupported_or_unidentified_index_row"
        elif mint in seen_mints or pool in seen_pools or creator in seen_creators:
            reason="duplicate_mint_pool_or_creator_claim"
        elif len(selected)>=SELECTION_LIMIT:
            reason="outside_first_three_distinct_creator_claims"
        if reason=="selected":
            seen_mints.add(mint);seen_pools.add(pool);seen_creators.add(creator)
            selected.append(dict(index=i,mint=mint,pool=pool,creator_claim=creator))
        denominator.append(dict(index=i,selection_reason=reason,
            mint=mint,pool=pool,creator_claim=creator,
            index_row_sha256=_hash(raw)))
    receipt=dict(schema="rugger-index-first-prospective-cohort-v1",
        index_order="new",page_prefix_size=len(rows),
        page_claim_hash_sha256=_hash(rows),
        selected=selected,
        denominator=denominator,
        frozen_input_lamports=BUY_LAMPORTS,
        selection_precedes_all_RPC_account_prices=True,
        claimed_creator_not_verified_by_signed_creation=True,
        all_discovery_rejections_preserved=True)
    return receipt

def _bank(rpc,addresses,floor):
    if not addresses or len(addresses)>21 or len(set(addresses))!=len(addresses):
        raise ValueError("invalid_bank_address_cardinality")
    result=rpc("getMultipleAccounts",[addresses,dict(
        encoding="base64",commitment="confirmed",minContextSlot=floor)])
    if type(result) is not dict or type(result.get("context")) is not dict:
        raise ValueError("bank_context_missing")
    slot=result["context"].get("slot");values=result.get("value")
    if type(slot) is not int or slot<floor or type(values) is not list or len(values)!=len(addresses):
        raise ValueError("bank_context_or_cardinality_invalid")
    return slot,dict(zip(addresses,values,strict=True))

def _projection(analysis):
    if type(analysis) is not dict or analysis.get("evidence_profile")!="published_metadata_v1":
        return None
    return analysis.get("conditional_projection")

def prospective_index_cohort(rpc,rows,*,sleep=time.sleep,wait_seconds=WAIT_SECONDS):
    if not callable(rpc) or type(wait_seconds) is not int or not 1<=wait_seconds<=20:
        raise ValueError("bounded_cohort_RPC_and_wait_required")
    registration=register_prebank_universe(rows)
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("wrong_chain_for_cohort")
    selected=registration["selected"]
    if not selected:
        return dict(status="NO_QUALIFIED_INDEX_LEADS",registration=registration,
            economic_cycles=0,master_vs_baseline_qualified=False,
            live_ready_to_arm=False,financial_order_submitted=False)
    roots=[r["pool"] for r in selected]
    root_slot,root_accounts=_bank(rpc,roots,1)
    candidates=[]
    for row in selected:
        try:
            addresses=addresses_from_pool(root_accounts[row["pool"]],row["mint"],row["pool"])
            if addresses["mint_b"]!=SOL_MINT or len(set(addresses.values()))!=7:
                raise ValueError("non_SOL_or_duplicate_account_graph")
            candidates.append(dict(**row,addresses=addresses))
        except (ValueError,TypeError,KeyError,SnapshotEvidenceError):
            candidates.append(dict(**row,refusal="root_graph_unavailable"))
    supported=[r for r in candidates if "addresses" in r]
    keys=list(dict.fromkeys(
        k for row in supported for k in row["addresses"].values()))
    s1slot=None;observed=[];s2slot=None; s1={}
    if keys:
        s1slot,accounts1=_bank(rpc,keys,root_slot)
        for row in supported:
            try:
                observed_at=time.time_ns()//1_000_000
                analysis=analyze_snapshot(
                    {k:accounts1[k] for k in row["addresses"].values()},
                    context_slot=s1slot,expected_mint=row["mint"],
                    pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                    evidence_profile="published_metadata_v1")
                s1[row["mint"]]=analysis
                observed.append(dict(mint=row["mint"],pool=row["pool"],
                    creator_claim=row["creator_claim"],s1_slot=s1slot,
                    s1_received_ms=observed_at,
                    s1_analysis_sha256=_hash(analysis),
                    s1_blocking_reasons=analysis["blocking_reasons"],
                    s1_identity_status=analysis["identity_status"],
                    s1_projection=_projection(analysis),
                    acquisition_verified=False,entry_executed=False))
            except (ValueError,TypeError,KeyError,SnapshotEvidenceError):
                observed.append(dict(mint=row["mint"],pool=row["pool"],
                    creator_claim=row["creator_claim"],s1_slot=s1slot,
                    s1_refusal="invalid_seven_account_snapshot",
                    acquisition_verified=False,entry_executed=False))
    reg_hash=_hash(registration)
    print(json.dumps(dict(phase="COHORT_REGISTERED_BEFORE_FUTURE_BANK",
        registration_sha256=reg_hash,selected_count=len(selected),
        s1_slot=s1slot,financial_order_submitted=False),sort_keys=True),flush=True)
    if keys:
        sleep(wait_seconds)
        s2slot,accounts2=_bank(rpc,keys,s1slot+1)
        for record in observed:
            if record.get("s1_projection") is None:
                record["s2_refusal"]="no_qualified_s1_buy_projection";continue
            row=next((r for r in supported if r["mint"]==record["mint"]),None)
            try:
                analysis2=analyze_snapshot(
                    {k:accounts2[k] for k in row["addresses"].values()},
                    context_slot=s2slot,expected_mint=row["mint"],
                    pool_address=row["pool"],input_lamports=BUY_LAMPORTS,
                    evidence_profile="published_metadata_v1",
                    compute_projection=False)
                if (analysis2["facts"].get("pool",{}).get("status")!=0
                        or analysis2.get("risk_flags") or
                        analysis2.get("blocking_reasons")==["unsupported"]):
                    raise ValueError("S2_curve_or_permissions_unqualified")
                f=analysis2["facts"];pool=f["pool"];cfg=f["config"];platform=f["platform"]
                quantity=int(record["s1_projection"]["buy_output_atomic"])
                sell=observed_sell_projection(pool,
                    input_token_atomic=quantity,
                    fee_rates_ppm=(cfg["trade_fee_rate_ppm"],
                        platform["platform_fee_rate_ppm"],platform["creator_fee_rate_ppm"]),
                    quote_vault_lamports=int(f["quote_vault"]["amount_atomic"]),
                    curve_type=cfg["curve_type"])
                proceeds=int(sell["output_lamports"])
                record.update(s2_slot=s2slot,
                    s2_analysis_sha256=_hash(analysis2),
                    hypothetical_token_amount_atomic=quantity,
                    conditional_sell_lamports=proceeds,
                    conditional_gross_markout_lamports=proceeds-BUY_LAMPORTS,
                    source_own_costs_known=False,
                    modeled_only=True,strict_economic_cycle_qualified=False)
            except (ValueError,TypeError,KeyError,SnapshotEvidenceError):
                record["s2_refusal"]="observed_s2_exit_unqualified"
    return dict(schema="rugger-index-first-prospective-cohort-v1",
        status="INDEX_FIRST_PROSPECTIVE_CAPTURE_COMPLETE",
        registration_sha256=reg_hash,
        page_prefix_size=registration["page_prefix_size"],
        full_discovery_denominator=registration["denominator"],
        selected=selected,
        observed=observed,unusable_root_graphs=sum(
            "addresses" not in r for r in candidates),
        first_bank_slot=s1slot,second_bank_slot=s2slot,
        claim_only_creator_count=len(selected),
        signed_creator_qualification_count=0,
        independent_creators_economically_qualified=0,
        actual_buy_sell_cycles=0,strict_economic_cycles=0,
        market_quote_route_and_own_costs_verified=False,
        unseen_index_rows_coverage_unknown=True,
        source_provider_claim_confirmed=True,
        selection_frozen_before_S1_and_S2=True,
        master_vs_baseline_edge_validated=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        rpc_calls_used=getattr(rpc,"count",None))

def main():
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_required")
        rows=fetch_index()
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=5)
        result=prospective_index_cohort(rpc,rows)
    except Exception as exc:
        code=str(exc)
        safe=code if (type(exc) is ValueError and len(code)<=90 and
            code.replace("_","").isalnum() and not code.startswith("helius_api_key")) else type(exc).__name__
        result=dict(status="REFUSED",reason=safe,
            last_rpc_method=(rpc.last_method if rpc else None),
            last_numeric_RPC_error_code=(rpc.last_rpc_error_code if rpc else None),
            financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"] in (
        "INDEX_FIRST_PROSPECTIVE_CAPTURE_COMPLETE","NO_QUALIFIED_INDEX_LEADS") else 2

if __name__=="__main__":
    sys.exit(main())

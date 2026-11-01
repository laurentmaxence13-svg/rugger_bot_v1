"""Audit Raydium index universe freshness across campaigns, not sample profitability.

The first 100 index rows are retained in each P3 capture. Unchanged INDEX
responses must not multiply creator groups or modelled opportunities.
Claims of creator identities or creation times are not signed proof.
"""
from collections import Counter
import hashlib
import json


def _digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),
        allow_nan=False).encode()).hexdigest()


def audit_index_universes(reports):
    if type(reports) is not list or not 1<=len(reports)<=20:
        raise ValueError("bounded_index_universe_reports_required")
    rows_by_run=[]
    sources=[]
    seen={}
    owners={}
    previous=None
    for n,report in enumerate(reports):
        if (type(report) is not dict or report.get("schema")!="p3-active-cohort-result-v1"
                or report.get("positions_acquired")!=0
                or report.get("qualified_economic_cycles")!=0
                or report.get("net_pnl_sol") is not None
                or report.get("execution_verified") is not False):
            raise ValueError("not_an_immutable_untraded_index_report")
        selection=report.get("selection")
        if (type(selection) is not dict
                or type(selection.get("records")) is not list
                or len(selection["records"])!=report.get("received_index_rows")
                or len(selection["records"])>100
                or type(selection.get("decision_at_ms")) is not int):
            raise ValueError("complete_source_universe_required")
        clock=selection["decision_at_ms"]
        if clock<=0 or previous is not None and clock<=previous:
            raise ValueError("captures_not_strictly_chronological")
        previous=clock
        page=[]
        for pos,item in enumerate(selection["records"]):
            if type(item) is not dict or item.get("universe_index")!=pos:
                raise ValueError("index_row_sequence_or_identity_invalid")
            source=item.get("source_row")
            if type(source) is not dict:
                raise ValueError("unretained_index_row")
            mint=source.get("mint");pool=source.get("pool");creator=source.get("creator_claim")
            quote=source.get("quote_mint_claim");creation=source.get("creation_time_claim_ms")
            if not all(type(x) is str and x for x in (mint,pool,creator,quote)):
                raise ValueError("missing_public_index_identity")
            if type(creation) is not int or creation<=0 or creation>clock:
                raise ValueError("provider_creation_time_claim_invalid")
            page.append((mint,pool,creator,quote,creation))
            pair=(mint,pool)
            first=seen.get(pair)
            if first is not None and first[0]!=creator:
                raise ValueError("contradictory_creator_for_same_pool")
            if pair not in seen:
                seen[pair]=(creator,n)
            if creator not in owners:
                owners[creator]=n
        if len(set((x[0],x[1]) for x in page))!=len(page):
            raise ValueError("duplicate_token_pool_within_one_index_page")
        rows_by_run.append(page)
        this=set((x[0],x[1]) for x in page)
        prev=set((x[0],x[1]) for x in rows_by_run[n-1]) if n else set()
        first_new=sum(seen[(x[0],x[1])][1]==n for x in page)
        sources.append(dict(run_index=n,source_report_sha256=_digest(report),
            source_decision_ms=clock,rows=len(page),
            index_native_SOL_quoted_claims=sum(
                x[3]=="So11111111111111111111111111111111111111112" for x in page),
            provider_claimed_unique_creators_on_page=len({x[2] for x in page}),
            newly_observed_token_pool_pairs=first_new,
            overlap_with_previous_page=len(this&prev),
            identical_page_to_previous=(page==rows_by_run[n-1]) if n else None))
    return dict(schema="rugger-index-universe-overlap-v1",
        captures=len(reports),
        total_index_observations=sum(len(x) for x in rows_by_run),
        unique_provider_claimed_token_pool_pairs=len(seen),
        unique_provider_claimed_creator_ids=len(owners),
        authentic_signed_creation_creator_ids=None,
        number_of_verified_executable_master_cycles=0,
        source_response_is_not_authentication=True,
        has_representative_creation_universe=False,
        sources=sources,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        financially_submitted_orders=0,live_ready_to_arm=False,
        market_profitability_verified=False)

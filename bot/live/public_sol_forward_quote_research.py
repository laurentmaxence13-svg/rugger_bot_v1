"""Free public prospective signed SOL S1/S2 quote-only cohort.

Use original authenticated outer-signed creator, preserve S1 seven-account
bank and freeze the genuine Master WAIT, then optionally GET an indicative
quote after the frozen decision, and a new quote after S2. NEVER execute
an order or convert an unowned hypothetical lot into Master PAPER P&L.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bot.analyser.artifacts import atomic_write_json
from bot.live.public_sol_forward_paper import run_one_public_paper_capture
from bot.live.public_sol_forward_cohort import collect_public_cohort
from bot.p3.signed_creation_forward_bank import signed_creator_asof_paper

SCHEMA="rugger-prospective-signed-sol-readonly-two-clock-quote-sidecar-v1"


def run(*,directory,window_count=3,seconds=75,
        collector=collect_public_cohort,capture=run_one_public_paper_capture):
    if (type(window_count) is not int or not 1<=window_count<=3
            or type(seconds) is not int or not 30<=seconds<=75
            or window_count*seconds>225):
        raise ValueError("bounded_signed_public_quote_cohort_required")
    folder=Path(directory)
    if folder.exists() or folder.is_symlink():
        raise ValueError("fresh_signed_quote_campaign_directory_required")

    def verified_strategy(captured,verified,rpc):
        # This real Master/reference scorer still WAITs without qualified
        # causal features and never accepts a third-party quote as a fill.
        return signed_creator_asof_paper(captured,verified,rpc,
            include_readonly_quotes=True)

    def capture_window(*,seconds,output_dir):
        return capture(seconds=seconds,output_dir=output_dir,
            strategy=verified_strategy)

    original=collector(directory=folder,window_count=window_count,
                      seconds=seconds,capture=capture_window)
    if (type(original) is not dict
            or original.get("schema")!="rugger-free-public-signed-cohort-v1"
            or original.get("financial_order_submitted") is not False
            or original.get("master_paper_buys")!=0
            or original.get("master_paper_sells")!=0
            or original.get("master_net_pnl_lamports") is not None):
        raise ValueError("unqualified_public_quote_cohort_financial_claim")
    sources=0
    pairs=0
    rejected=0
    receipts=[]
    for i in range(window_count):
        path=folder/f"window_{i:02d}"/"paired_master_source_shadow.json"
        raw=json.loads(path.read_text(encoding="utf-8"))
        if (type(raw) is not dict or
                raw.get("financial_order_submitted") is not False
                or raw.get("execution_verified") is not False
                or type(raw.get("observations")) is not list):
            raise ValueError("invalid_signed_research_quote_source")
        for row in raw["observations"]:
            if type(row) is not dict:
                raise ValueError("untrusted_signed_quote_observation")
            signed=row.get("frozen_decision_before_S2")
            buy=row.get("s1_independent_research_buy_quote")
            sell=row.get("s2_independent_research_sell_quote")
            if buy is None and sell is None:
                continue
            if (type(signed) is not dict or signed.get("master_action")=="ENTER"
                    or signed.get("future_S2_used") is not False
                    or signed.get("real_order") is not False
                    or row.get("s1_bank_preserved_before_S2") is not True):
                raise ValueError("research_quote_was_not_after_actual_Master_wait")
            sources+=1
            if buy is not None:
                if (buy.get("input_mint")!="So11111111111111111111111111111111111111112"
                        or buy.get("output_mint")!=row.get("mint")
                        or buy.get("provider_route_pool")!=row.get("pool")
                        or buy.get("actual_fill") is not False
                        or buy.get("hypothetical_lot_was_never_executed") is not True
                        or buy.get("provider_produced_at_ms") is not None
                        or buy.get("provider_source_slot") is not None
                        or type(row.get("s2_received_ms")) is not int
                        or type(signed.get("at_ms")) is not int
                        or not signed["at_ms"]<=buy.get("received_at_utc_ms",0)<row["s2_received_ms"]):
                    raise ValueError("unqualified_signed_S1_buy_quote_provenance")
            if sell is not None:
                if (type(buy) is not dict
                        or sell.get("input_mint")!=row.get("mint")
                        or sell.get("output_mint")!="So11111111111111111111111111111111111111112"
                        or sell.get("provider_route_pool")!=row.get("pool")
                        or sell.get("input_atomic")!=buy.get("output_atomic")
                        or type(row.get("s2_received_ms")) is not int
                        or sell.get("received_at_utc_ms",0)<row["s2_received_ms"]
                        or sell.get("actual_fill") is not False
                        or sell.get("provider_produced_at_ms") is not None
                        or sell.get("provider_source_slot") is not None
                        or row.get("source_produced_quote_clocks_verified") is not False
                        or row.get("research_quote_pair_is_not_an_actual_Master_PAPER_cycle") is not True):
                    raise ValueError("unqualified_signed_S2_sell_quote_provenance")
                pairs+=1
            else:
                rejected+=1
            receipts.append(dict(window=i,signature=row["signature"],
                mint=row["mint"],pool=row["pool"],
                signed_S1_before_S2=True,
                independent_S1_quote_received=buy is not None,
                independent_S2_quote_received=sell is not None,
                research_only_conditional_difference_lamports=row.get(
                    "research_only_quote_delta_before_extra_costs_lamports"),
                source_produced_quotes_and_fees_unknown=True,
                genuine_Master_PAPER_entry_executed=False))
    result=dict(schema=SCHEMA,
        source="FREE_PUBLIC_SOLANA_PLUS_READONLY_RAYDIUM_QUOTES",
        window_count=window_count,observed_signed_source_events=original["observed_unique_events"],
        signed_source_creators=original["uniquely_selected_signed_creators"],
        native_SOL_source_creators=original["native_SOL_source_creators"],
        independent_quote_S1_cases=sources,
        two_clock_quote_only_pairs=pairs,
        incomplete_quote_pairs=rejected,
        complete_causal_Master_economic_cycles=0,
        operational_Master_admission_verified=False,
        provider_produced_quote_times_and_slots_verified=False,
        hypothetical_lot_never_acquired=True,
        actual_Master_PAPER_buys=0,actual_Master_PAPER_sells=0,
        net_Master_PAPER_pnl_lamports=None,
        financial_order_submitted=False,live_trading_enabled=False,
        recorded_pairs=receipts)
    atomic_write_json(folder/"quote_sidecar_summary.json",result,
                      sort_keys=True,allow_nan=False)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--windows",type=int,default=3)
    parser.add_argument("--seconds",type=int,default=75)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print("CAUSAL_QUOTE_RESEARCH_REFUSED:NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        out=run(directory=args.output_dir,window_count=args.windows,seconds=args.seconds)
    except Exception as error:
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
            safe_error_class=type(error).__name__,financial_order_submitted=False),
            sort_keys=True))
        return 2
    print(json.dumps(out,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

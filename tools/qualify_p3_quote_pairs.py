#!/usr/bin/env python3
"""Classify archived round-trip quote pairs; never fills or writes a ledger."""
from collections import defaultdict
import json
from pathlib import Path
import sys

repo=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(repo))
from bot.p3.evidence import verify_bundle
from bot.p3.exit_qualification import qualify_exit_quote_pair


def main():
    results=[]
    index=json.loads((repo/'evidence/p3/index.json').read_text())
    for anchor in index['bundles']:
        b=verify_bundle(repo/'evidence/p3'/anchor['run_id'],expected_tail=anchor['tail_hash'])
        grouped=defaultdict(dict)
        for e in b['events']:
            p=e['payload']
            if (e['kind']=='quote_attempt' and p.get('provider')=='raydium_trade_api'
                    and e.get('request_id') is not None and p.get('quote_side') in ('buy','sell')):
                grouped[e['request_id']][p['quote_side']]=e
        for pair in grouped.values():
            if set(pair)!={'buy','sell'}:
                continue
            buy,sell=pair['buy'],pair['sell']
            verdict=qualify_exit_quote_pair(buy,sell,inventory_basis='expected_buy_output',
                entry_decision_at_ms=buy['available_at_ms'],
                exit_decision_at_ms=max(sell['available_at_ms'],buy['available_at_ms']),
                max_source_age_ms=5000,fees=None,available_cash_lamports=10000000000)
            assert verdict['execution_verified'] is False
            assert verdict['conditional_accounting_projection'] is None
            results.append(dict(run_id=anchor['run_id'],mint=buy['mint'],buy_id=buy['id'],
                sell_id=sell['id'],qualification=verdict['qualification'],reasons=verdict['reasons'],
                net_pnl_lamports=None))
    print(json.dumps(dict(schema='p3-archived-quote-pair-admission-v1',pairs=results,
        pairs_checked=len(results),max_source_age_ms=5000,additional_fee_evidence='unknown_not_zero',
        full_position_closures_verified=0,ledger_mutated=False,
        new_network_requests=0,economic_verdict='INSUFFICIENT DATA'),indent=2,sort_keys=True))


if __name__=='__main__':main()

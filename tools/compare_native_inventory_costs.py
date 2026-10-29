#!/usr/bin/env python3
"""Matched synthetic cost comparison: quantity accounting is not a profit uplift."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['RUGGER_NO_DOTENV'] = '1'
from bot.__main__ import _offline_policy
sys.addaudithook(_offline_policy)
from bot.economic_demo import _load_api, _quote_observation, _public_address
from bot.analyser.paper_trader import record_quote, paper_capital


def main():
    api = _load_api()
    mint,pool = _public_address(1),_public_address(3)
    model = dict(decision_approved=True,decision_score=75,tp_pct=10,sl_pct=8,
                 hold_seconds=1800,cost_bps=200)
    outputs = {}
    for kind in ('legacy_usd_mark','native_projected_quantity'):
        with closing(sqlite3.connect(':memory:',isolation_level=None)) as con:
            api['setup'](con)
            context = None
            if kind.startswith('native'):
                context = dict(buy_observation=_quote_observation(api,side='buy',mint=mint,
                    pool=pool,amount=1_000_000_000,output=25_000_000,requested=159970,
                    index=1,case='matched_cost'),token_decimals=6,
                    fees=api['SolFeeBreakdown'](10_000_000,10_000_000,(),provenance='synthetic'))
            record_quote(con,mint,'synthetic-creator',100,160,
                api['MarketQuote'](20000,.001,pool),model,strategy_mode='shadow_final',inventory_context=context)
            if context is not None:
                context = dict(sell_observation=_quote_observation(api,side='sell',mint=mint,
                    pool=pool,amount=25_000_000,output=1_200_000_000,requested=199970,
                    index=2,case='matched_cost'),requested_quantity_atomic='25000000',inventory_version=0,
                    fees=api['SolFeeBreakdown'](10_000_000,10_000_000,(),provenance='synthetic'))
            record_quote(con,mint,'synthetic-creator',100,200,
                api['MarketQuote'](20000,.0012,pool),model,strategy_mode='shadow_final',inventory_context=context)
            pnl = con.execute('SELECT pnl_sol FROM paper_trades').fetchone()[0]
            assert abs(pnl-.18)<1e-12
            outputs[kind] = {'net_simulated_sol':pnl,'capital_final_sol':paper_capital(con)[1],
                'cost_sol':.02,'initial_capital_sol':10,'position_sol':1,
                'atomic_inventory_known':context is not None}
    print(json.dumps({'schema':'p3-matched-inventory-cost-comparison-v1','data_kind':'synthetic',
        'network_requests':0,'execution_verified':False,'economic_profitability_verified':False,
        'source':'active record_quote; identical price return, notional and total synthetic costs',
        'comparison':outputs,'native_costs_counted_once':True,
        'interpretation':'At matched costs both ledgers return 0.18 SOL. Atomic inventory adds quantity and exit checks, not an assumed performance gain.'},indent=2,sort_keys=True))


if __name__ == '__main__':
    main()

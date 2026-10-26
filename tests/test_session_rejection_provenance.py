"""Session refusal diagnostics must use risk flags, not positive score reasons."""
from contextlib import closing
import json
import sqlite3

from bot.analyser.paper_engine import _session_summary
from bot.analyser.paper_trader import ensure_paper_portfolio, setup


def test_session_rejections_keep_risk_flags_and_scope_without_positive_reasons():
    with closing(sqlite3.connect(':memory:')) as con:
        setup(con)
        ensure_paper_portfolio(con, 10, 1000)
        for mint, when, enter in [('rejected', 1010, 0), ('accepted', 1020, 1),
                                  ('old', 999, 0), ('future', 1101, 0)]:
            con.execute('''INSERT INTO paper_decisions(
                mint,creator,signal_time,decision_time,strategy_mode,enter,
                entry_allowed,score,reasons_json,risk_flags_json,prior_launches,
                behavior_known,dev_sales,relay_transfers,bundle_transactions,
                bundle_wallets,liquidity_usd,price_usd,quote_count,hold_seconds)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (mint, 'creator', 980, when, 'shadow_final', enter, enter, 60,
                 json.dumps(['liquidity_bonus', 'repeat_creator_bonus']),
                 json.dumps(['developer_sale']), 2, 1, 1, 0, 0, 0, 20000, 1, 2, 300))
        report = _session_summary(con, 1000, 1100)
        assert report['decisions'] == 2
        assert report['accepted_decisions'] == 1
        assert report['rejections'] == 1
        assert report['rejection_reasons'] == {'developer_sale': 1}

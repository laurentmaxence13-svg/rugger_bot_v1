"""Offline regression: a vanished confirmation must keep its REORG_PENDING state and kill reason
when the blockhash lifetime later passes (synthetic fixtures only, no network)."""
import json

from test_live_engine import configured, run


def _kill_reason(journal):
    return journal.con.execute("SELECT value FROM execution_meta WHERE key='kill'").fetchone()[0]


def test_reorg_pending_survives_blockhash_expiry(tmp_path):
    engine, order, rpc, _, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    run(engine.execute(decision, order))
    rpc.status = dict(confirmationStatus='confirmed', err=None, slot=1300)
    run(engine.recover(decision))
    rpc.status = None
    rpc.height = 5001  # beyond last_valid_block_height
    result = run(engine.recover(decision))
    assert result['state'] == 'REORG_PENDING'
    assert _kill_reason(engine.journal) == 'confirmation_disappeared'
    assert not list(engine.journal.con.execute('SELECT * FROM positions'))

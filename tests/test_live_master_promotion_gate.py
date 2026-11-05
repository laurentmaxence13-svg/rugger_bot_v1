"""An experimental Master diagnostic may not spend real funds."""
from copy import deepcopy

import pytest

from bot.live.safety import Mode
from test_master_decision import qualified
from test_live_runtime import runtime,run


def test_explicit_policy_hash_does_not_promote_experimental_master(tmp_path,monkeypatch):
    value,frame,journal,route_calls=runtime(tmp_path,mode=Mode.LIVE_ENABLED)
    try:
        core,qualified_frame,health,capital=qualified()
        proposed=core.evaluate(qualified_frame,health=health,capital=capital)
        assert proposed["action"]=="ENTER"
        assert proposed["execution_authorized"] is False
        assert proposed["promotion_allowed"] is False
        # This boundary test deliberately injects an ENTER proposal that still
        # declares itself unpromoted. It is NOT source/market evidence.
        monkeypatch.setattr(value.core,"evaluate",lambda *a,**kw:deepcopy(proposed))
        value.approved_policy_sha256=value.core.policy_sha256
        frame["data_kind"]="market_observation"
        with pytest.raises(ValueError,match="unpromoted_Master"):
            run(value.observe(frame))
        assert route_calls==[]
        assert journal.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]==0
        assert journal.con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]==1
        assert journal.verify_audit()
    finally:
        journal.close()


def test_live_prepared_still_allows_unsigned_route_preparation(tmp_path,monkeypatch):
    value,frame,journal,_=runtime(tmp_path,mode=Mode.LIVE_PREPARED)
    try:
        core,qualified_frame,health,capital=qualified()
        proposed=core.evaluate(qualified_frame,health=health,capital=capital)
        assert proposed["action"]=="ENTER"
        monkeypatch.setattr(value.core,"evaluate",lambda *a,**kw:deepcopy(proposed))
        async def explicit_wrong_route(*a):
            return {"decision_id":a[0],"side":"BUY","mint":"different"}
        value.route_request_provider=explicit_wrong_route
        with pytest.raises(ValueError,match="frozen_Master"):
            run(value.observe(frame))
        # Prepared-mode invalid routes fail for route mismatch, not because
        # a real-wallet promotion is required for non-financial preflight.
        assert journal.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]==0
    finally:
        journal.close()

"""A second, synchronous gate at the HTTP transaction-payload boundary."""
from .safety import Mode


class BoundSubmissionGuard:
    """Bind a transport to one engine's durable, pre-admitted signed message.

    Installing this guard cannot arm the engine or grant authority. It refuses
    arbitrary signed bytes, duplicate transmissions, stale services and revoked
    authorization, even if transport acquisition took time after engine checks.
    """
    def __init__(self,engine):self.engine=engine

    def __call__(self,raw):
        engine=self.engine
        if engine.mode is not Mode.LIVE_ENABLED or type(raw) is not bytes:
            return False
        rows=list(engine.journal.con.execute('SELECT decision_id,state FROM orders WHERE signed_raw=?',(raw,)))
        if len(rows)!=1 or rows[0]['state']!='SUBMITTING':return False
        try:
            with engine.journal.atomic():
                if engine.journal.killed:return False
                current=engine.journal.get(rows[0]['decision_id'])
                if current['state']!='SUBMITTING' or current['signed_raw']!=raw:return False
                engine._final_admission(current['decision_id'])
        except (ValueError,KeyError,TypeError):
            return False
        return True

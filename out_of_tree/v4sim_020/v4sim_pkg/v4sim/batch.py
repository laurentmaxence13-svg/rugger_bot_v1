"""Fixed-order batches on synthetic timeline packs: position-by-position outputs for the acceptance
tests (A-5, A-7) and for the independent recomputation of RUGGER 02 (A-11). No policy, no evaluation."""
import hashlib
import json
import multiprocessing
from pathlib import Path

from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import ExecutionModel, Strategy

from v4sim import PROTOCOL_SHA256, VERSION
from v4sim.engine import Execution, replay
from v4sim.io import load_timeline_pack
from v4sim.ledger import MODES


class FixedOrder(Strategy):
    """Buy ``amount`` at the decision index; ask to sell after ``exit_after_events`` later real events."""

    def __init__(self, decision_index, amount, exit_after_events):
        self.decision_index, self.amount, self.exit_after_events = decision_index, amount, exit_after_events

    def entry(self, history):
        return self.amount if len(history) - 1 == self.decision_index else None

    def exit(self, history, position, mark):
        return len(history) - 1 - position.entry_index >= self.exit_after_events


def code_fingerprint():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.glob('*.py')):
        digest.update(path.name.encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def position_row(timeline, order, mode, model, execution=Execution()):
    strategy = FixedOrder(order['decision_index'], order['amount_lamports'], order['exit_after_events'])
    result = replay(timeline, strategy, model, quote_mint=WSOL_MINT, mode=mode, execution=execution)
    return dict(pool=timeline.pool, mode=mode, outcome=result.outcome, entry_index=result.entry_index,
                exit_index=result.exit_index, spent=result.spent, tokens=result.tokens, received=result.received,
                tx_costs=result.tx_costs, fee_rate_ppm=result.fee_rate_ppm, notes=result.notes,
                flags=result.v4['flags'], sold_tokens=result.v4['sold_tokens'],
                last_curve_value=result.v4['last_curve_value'], counters=result.v4['counters'],
                failed_attempts=result.v4['failed_attempts'])


def _work(job):
    timeline, order, model = job
    return [position_row(timeline, order, mode, model) for mode in MODES]


def run_pack(directory, *, workers=1, model=ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')):
    """Every pool entry carrying ``our_order``, in the four modes. Deterministic whatever ``workers``."""
    manifest_sha256, pools = load_timeline_pack(directory)
    jobs = [(timeline, entry['our_order'], model) for entry, timeline in pools if entry.get('our_order')]
    if workers == 1:
        rows = [_work(job) for job in jobs]
    else:
        with multiprocessing.get_context('fork').Pool(workers) as pool:
            rows = pool.map(_work, jobs, chunksize=4)
    return dict(schema='v4sim-positions-v1', v4sim_version=VERSION, protocol_sha256=PROTOCOL_SHA256,
                code_fingerprint=code_fingerprint(), pack_manifest_sha256=manifest_sha256,
                model=dict(latency_slots=model.latency_slots, fee_rate_estimator=model.fee_rate_estimator,
                           base_fee_lamports=model.base_fee_lamports, priority_fee_lamports=model.priority_fee_lamports),
                positions=[row for group in rows for row in group])


def dumps(document):
    return (json.dumps(document, indent=1, sort_keys=True) + '\n').encode()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='fixed orders of a synthetic timeline pack, four modes')
    parser.add_argument('pack', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--workers', type=int, default=1)
    a = parser.parse_args()
    raw = dumps(run_pack(a.pack, workers=a.workers))
    a.out.write_bytes(raw)
    print(json.dumps(dict(out=str(a.out), sha256=hashlib.sha256(raw).hexdigest())))

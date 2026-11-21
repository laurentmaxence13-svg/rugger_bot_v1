"""Offline tests of w2pack (R03). The frozen backfill is driven through its injectable opener by a fake chain
that replays the REAL W1 pilot archive (data/w1_pilot, 61 997 transactions); no request ever leaves the process.
Run from the frozen tree checkout (cwd), PYTHONPATH = <tree>:<w2pack>."""
import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import backfill_cli as bcli
from bot.market import backfill_export as bx
from bot.market import w1_collection as w1
from w2pack import cli, plan as P

PILOT = Path('data/w1_pilot')
ENV = {'RUGGER_BACKFILL_RPC_URL': 'https://rpc.example.test/?api-key=NOT-A-REAL-KEY'}


def _rows(kind):
    man = json.loads((PILOT / 'manifest.json').read_text())
    out = []
    for seg in man['segments']:
        if seg['kind'] == kind:
            with gzip.open(PILOT / seg['path'], 'rt') as fh:
                out.extend(json.loads(line) for line in fh)
    return man, out


MAN, TX = _rows('tx')
_, SIG = _rows('sig')
WIN = MAN['window']
ANCHOR = MAN['gsfa_anchor']


def _sigset(rows):
    return hashlib.sha256('\n'.join(sorted(r['signature'] for r in rows)).encode()).hexdigest()


class PilotChain:
    """JSON-RPC server behind JsonRpc's opener, answering from the pilot archive only."""

    def __init__(self):
        self.calls = []
        self.asc = sorted(TX, key=lambda r: (r['slot'], r['transactionIndex']))
        self.desc = sorted(SIG, key=lambda r: (r['slot'], r['transactionIndex']), reverse=True)
        self.desc_index = {r['signature']: i for i, r in enumerate(self.desc)}

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.calls.append(body['method'])
        result = getattr(self, body['method'])(*body['params'])
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())

    def getTransactionsForAddress(self, address, options):
        assert address == WIN['address'] and options['sortOrder'] == 'asc'
        slot = options['filters']['slot']
        if options['transactionDetails'] == 'signatures':          # the anchor call, first after the window
            assert options['limit'] == 1 and options['filters']['status'] == 'succeeded' and 'lte' not in slot
            after = [r for r in self.asc if r['slot'] >= slot['gte'] and (r.get('meta') or {}).get('err') is None]
            if not after:      # the real pilot's own anchor, just after the pilot window
                return {'data': [{'signature': ANCHOR['signature'], 'slot': ANCHOR['slot'], 'err': None,
                                  'transactionIndex': ANCHOR['transaction_index']}], 'paginationToken': None}
            r = after[0]
            return {'data': [{'signature': r['signature'], 'slot': r['slot'], 'err': None,
                              'transactionIndex': r['transactionIndex']}], 'paginationToken': None}
        rows = [r for r in self.asc if slot['gte'] <= r['slot'] <= slot['lte']]
        start = int(options.get('paginationToken') or 0)
        page = rows[start:start + options['limit']]
        token = str(start + len(page)) if start + len(page) < len(rows) else None
        return {'data': page, 'paginationToken': token}

    def getSignaturesForAddress(self, address, options):
        assert address == WIN['address']
        before = options.get('before')
        start = 0 if before in (None, ANCHOR['signature']) else self.desc_index[before] + 1   # rows above the window are skipped by the frozen code
        return self.desc[start:start + options['limit']]


def _run(out, *, max_credits, segment_pages=20, lo=None, hi=None):
    buf = io.StringIO()
    lo, hi = WIN['slot_min'] if lo is None else lo, WIN['slot_max'] if hi is None else hi
    code = bcli.main(['run', '--network', '--slot-min', str(lo), '--slot-max', str(hi),
                      '--anchor-after-window', '--costs', P.COSTS, '--max-requests', '5000',
                      '--max-credits', str(max_credits), '--segment-pages', str(segment_pages), '--out', str(out)],
                     environ=ENV, opener=PilotChain(), out=buf)
    return code, json.loads(buf.getvalue())


def test_window_0_is_exactly_the_frozen_w1_bounds_and_window_i_follows_s0_plus_i_times_1612800():
    cfg = P.W2Config(s0=467_275_745, windows=3)
    assert P.window_bounds(cfg, 0) == w1.bounds(467_275_745)
    for i in range(3):
        assert P.window_bounds(cfg, i) == w1.bounds(467_275_745 + i * 1_612_800)


def test_k_windows_tile_the_evaluation_union_exactly():
    for k in (1, 4, 8, 15):
        cfg = P.W2Config(s0=500_000_000, windows=k)
        u, ws = P.union(cfg), P.windows(cfg)
        assert u['evaluation_slots'] == k * 1_612_800 == u['evaluation'][1] - u['evaluation'][0]
        assert u['slot_min'] == 500_000_000 and u['slot_max'] == 500_000_000 + 402_800 + k * 1_612_800 + 4_513 - 1
        assert all(a['evaluation'][1] == c['evaluation'][0] for a, c in zip(ws, ws[1:]))
        assert P.projection(cfg)['fits']


def test_non_integer_or_bad_window_counts_and_configs_are_refused(tmp_path):
    for bad in (dict(s0=1, windows=0), dict(s0=1, windows=3.49), dict(s0=1, windows='4'), dict(s0=0, windows=1),
                dict(s0=1, windows=1, margin=0.5)):
        with pytest.raises(P.PlanError):
            P.W2Config(**bad).check()
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(dict(s0=1, windows=4, evaluation_slots=5_626_047)))
    with pytest.raises(P.PlanError):
        cli.load(path)          # the old free-length key is refused


def test_argv_is_the_frozen_command_of_one_frozen_window_with_a_bounded_cap(tmp_path):
    cfg = P.W2Config(s0=467_275_745, windows=2)
    argv = cli.window_argv(cfg, 1, tmp_path / 'w1', max_credits=500_000, max_requests=60_000)
    b = w1.bounds(467_275_745 + 1_612_800)
    assert argv[:2] == ['run', '--network'] and '--anchor-after-window' in argv and P.COSTS in argv
    assert argv[argv.index('--slot-min') + 1] == str(b['slot_min']) and argv[argv.index('--slot-max') + 1] == str(b['slot_max'])
    with pytest.raises(P.PlanError):
        cli.window_argv(cfg, 0, tmp_path / 'x', max_credits=cfg.credit_cap + 1, max_requests=1)
    with pytest.raises(P.PlanError):
        cli.window_argv(cfg, 2, tmp_path / 'x', max_credits=1, max_requests=1)


def test_offline_replay_of_the_real_pilot_is_complete_reconciled_and_identical(tmp_path):
    code, report = _run(tmp_path / 'w', max_credits=50_000)
    assert code == 0 and report['complete']
    assert report['totals']['transactions'] == MAN['totals']['transactions'] == 61_997
    assert report['totals']['duplicate_signatures'] == 0
    assert bf.verify(tmp_path / 'w')['ok']
    got = [json.loads(l) for s in json.loads((tmp_path / 'w' / 'manifest.json').read_text())['segments']
           if s['kind'] == 'tx' for l in gzip.open(tmp_path / 'w' / s['path'], 'rt')]
    assert _sigset(got) == _sigset(TX)


def test_credit_cap_stop_then_same_command_resumes_to_the_same_archive(tmp_path):
    code, report = _run(tmp_path / 'w', max_credits=2_000, segment_pages=5)
    assert code == 3 and not report['complete'] and report['stopped_by'] == 'credit_cap_reached:2000'
    code, report = _run(tmp_path / 'w', max_credits=50_000, segment_pages=5)
    assert code == 0 and report['complete'] and report['totals']['duplicate_signatures'] == 0
    assert report['totals']['transactions'] == 61_997 and bf.verify(tmp_path / 'w')['ok']
    got = [json.loads(l) for s in json.loads((tmp_path / 'w' / 'manifest.json').read_text())['segments']
           if s['kind'] == 'tx' for l in gzip.open(tmp_path / 'w' / s['path'], 'rt')]
    assert _sigset(got) == _sigset(TX)


def _export(run, out):
    bx.export_pools(run, out, entry_cutoff_gap_slots=500)
    man = (out / 'MANIFEST.json').read_bytes()
    return hashlib.sha256(man).hexdigest(), set(json.loads(man)['pools']) if isinstance(json.loads(man).get('pools'), dict) else len(json.loads(man).get('pools') or [])


def test_frozen_export_needs_one_run_per_window_a_split_collection_is_not_the_same_window(tmp_path, capsys):
    """Interface R02 e042f7b8 on the real pilot: pseudo-window A = 12 500 slots (gap 500 >= 162), collected (a) in
    ONE run, (b) in TWO contiguous runs; plus a second pseudo-window B overlapping A, in its own run."""
    a = WIN['slot_min']
    A, B = (a, a + 12_499), (a + 8_000, a + 20_499)
    assert _run(tmp_path / 'one', max_credits=50_000, lo=A[0], hi=A[1])[0] == 0
    assert _run(tmp_path / 's1', max_credits=50_000, lo=A[0], hi=a + 6_999)[0] == 0
    assert _run(tmp_path / 's2', max_credits=50_000, lo=a + 7_000, hi=A[1])[0] == 0
    assert _run(tmp_path / 'B', max_credits=50_000, lo=B[0], hi=B[1])[0] == 0
    one = _export(tmp_path / 'one', tmp_path / 'x_one')
    s2 = _export(tmp_path / 's2', tmp_path / 'x_s2')
    b = _export(tmp_path / 'B', tmp_path / 'x_B')
    # the frozen export reads ONE run; its window is that run's window
    for run, win in (('one', A), ('s2', (a + 7_000, A[1])), ('B', B)):
        m = json.loads((tmp_path / run / 'manifest.json').read_text())['window']
        assert (m['slot_min'], m['slot_max']) == win
    # a segment run is not window A: its export differs from the one-run export of A
    assert s2[0] != one[0]
    with pytest.raises(TypeError):
        bx.export_pools([tmp_path / 's1', tmp_path / 's2'], tmp_path / 'x_both', entry_cutoff_gap_slots=500)
    print(json.dumps(dict(one=one[0], s2=s2[0], B=b[0])))

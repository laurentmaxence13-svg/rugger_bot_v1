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
            assert slot['gte'] == WIN['slot_max'] + 1 and options['limit'] == 1
            return {'data': [{'signature': ANCHOR['signature'], 'slot': ANCHOR['slot'], 'err': None,
                              'transactionIndex': ANCHOR['transaction_index']}], 'paginationToken': None}
        rows = [r for r in self.asc if slot['gte'] <= r['slot'] <= slot['lte']]
        start = int(options.get('paginationToken') or 0)
        page = rows[start:start + options['limit']]
        token = str(start + len(page)) if start + len(page) < len(rows) else None
        return {'data': page, 'paginationToken': token}

    def getSignaturesForAddress(self, address, options):
        assert address == WIN['address']
        before = options.get('before')
        start = 0 if before in (None, ANCHOR['signature']) else self.desc_index[before] + 1
        return self.desc[start:start + options['limit']]


def _run(out, *, max_credits, segment_pages=20):
    buf = io.StringIO()
    code = bcli.main(['run', '--network', '--slot-min', str(WIN['slot_min']), '--slot-max', str(WIN['slot_max']),
                      '--anchor-after-window', '--costs', P.COSTS, '--max-requests', '5000',
                      '--max-credits', str(max_credits), '--segment-pages', str(segment_pages), '--out', str(out)],
                     environ=ENV, opener=PilotChain(), out=buf)
    return code, json.loads(buf.getvalue())


def test_w1_parameters_give_exactly_the_frozen_w1_bounds():
    assert P.bounds(P.W2Config(s0=467_275_745)) == w1.bounds(467_275_745)


def test_segments_are_contiguous_and_cover_the_window_and_cohorts_are_never_cut():
    cfg = P.W2Config(s0=500_000_000, evaluation_slots=12_055_814, segment_slots=2_812_000, observation_slots=5_000)
    b, segs, coh = P.bounds(cfg), P.segments(cfg), P.cohorts(cfg)
    assert segs[0]['slot_min'] == b['slot_min'] and segs[-1]['slot_max'] == b['slot_max']
    assert all(a['slot_max'] + 1 == c['slot_min'] for a, c in zip(segs, segs[1:]))
    assert sum(s['slots'] for s in segs) == b['collected_slots']
    assert coh[0]['created_from'] == b['evaluation'][0] and coh[-1]['created_before'] == b['evaluation'][1]
    for c in coh:
        assert segs[c['ready_after_segment']]['slot_max'] >= c['needs_collected_to']
    assert P.plan(cfg)['projection']['fits']


def test_bad_configs_are_refused():
    for bad in (dict(s0=0), dict(s0=1, observation_slots=10), dict(s0=1, margin=0.5), dict(s0=1, segment_slots=-1)):
        with pytest.raises(P.PlanError):
            P.W2Config(**bad).check()


def test_argv_is_the_frozen_command_with_the_segment_bounds_and_refuses_a_cap_above_the_config(tmp_path):
    cfg = P.W2Config(s0=467_275_745)
    argv = cli.segment_argv(cfg, 0, tmp_path / 'seg0', max_credits=500_000, max_requests=60_000)
    assert argv[:2] == ['run', '--network'] and '--anchor-after-window' in argv and P.COSTS in argv
    assert argv[argv.index('--slot-min') + 1] == '467275745'
    with pytest.raises(P.PlanError):
        cli.segment_argv(cfg, 0, tmp_path / 'x', max_credits=cfg.credit_cap + 1, max_requests=1)
    with pytest.raises(P.PlanError):
        cli.segment_argv(cfg, 99, tmp_path / 'x', max_credits=1, max_requests=1)


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

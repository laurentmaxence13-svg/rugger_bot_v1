"""Offline census checks: synthetic world, fake clock, never network or wallets."""
import asyncio
import base64
import copy
import gzip
import heapq
import json
import math
from pathlib import Path
import struct
import subprocess

import pytest

from bot.p3 import campaign as cp
from bot.p3 import census as cs
from bot.p3 import census_report as cr
from bot.p3 import certification as cert
from bot.p3 import collect
from bot.p3 import launchlab as ll
from bot.p3.quotes import RAYDIUM_QUOTE_URL, SOL_MINT
from test_multiple_launches import instruction
from test_p3_collection import Transport
from test_p3_launchlab import ALPHABET, decode, encode, fixture, mutate_account
from test_p3_quotes import Response, quote_payload
from test_p3_token2022 import metadata

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / 'benchmarks' / 'p3_launchlab_census_v1' / 'protocol.json'
T0 = 1_800_000_000_000
CREATOR = encode(bytes([8]) * 32)


class Clock:
    def __init__(self, start=T0):
        self.ms = start
        self.sleeps = 0

    def __call__(self):
        return self.ms

    async def sleep(self, seconds):
        self.sleeps += 1
        self.ms += max(1, math.ceil(seconds * 1000))


class Crash(BaseException):
    """A process death: no except clause in the collector may absorb it."""


def protocol():
    return dict(copy.deepcopy(cs.PROTOCOL_V1), registered_at_ms=T0 - 10_000)


def authorization(**changes):
    value = {'schema': cs.AUTHORIZATION_SCHEMA, 'protocol_sha256': cs.sha256_of(protocol()),
             'approved_by': 'synthetic-owner', 'approved_at_ms': T0 - 5_000,
             'max_enrollment_duration_ms': 600_000, 'max_creations': 10,
             'request_budgets': {cs.RPC: 500, cs.QUOTE: 200, cs.INDEX: 100},
             'spend_authorized': False, 'subscriptions_authorized': False,
             'wallet_or_signing_authorized': False,
             'network_scope': 'anonymous_public_reads_listed_in_protocol'}
    value.update(changes)
    return value


def variant(mint_byte, *, qualified):
    """Distinct synthetic LaunchLab pool; qualified uses published PDAs."""
    original, old = fixture()
    a = dict(old)
    a['mint_a'] = encode(bytes([mint_byte]) * 32)
    if qualified:
        a['pool'], _ = cert.find_program_address((b'pool', decode(a['mint_a']), decode(SOL_MINT)))
        a['config'], _ = cert.find_program_address((b'global_config', decode(SOL_MINT), b'\0', b'\0\0'))
        for role, mint in (('vault_a', 'mint_a'), ('vault_b', 'mint_b')):
            a[role], _ = cert.find_program_address((b'pool_vault', decode(a['pool']), decode(a[mint])))
    else:
        for index, role in enumerate(('pool', 'vault_a', 'vault_b'), 1):
            a[role] = encode(bytes([mint_byte + index]) * 32)
    accounts = {a[role]: copy.deepcopy(original[old[role]]) for role in ll.ACCOUNT_ROLES}
    for role, offset in (('config', 141), ('platform', 173), ('mint_a', 205),
                         ('mint_b', 237), ('vault_a', 269), ('vault_b', 301)):
        mutate_account(accounts, a['pool'], offset, decode(a[role]))
    mutate_account(accounts, a['vault_a'], 0, decode(a['mint_a']))
    if qualified:
        for role in cert.DISCRIMINATORS:
            mutate_account(accounts, a[role], 0, cert.DISCRIMINATORS[role])
        authority, bump = cert.find_program_address((b'vault_auth_seed',))
        mutate_account(accounts, a['pool'], 16, bump)
        mutate_account(accounts, a['pool'], 365, 1)
        for role in ('vault_a', 'vault_b'):
            mutate_account(accounts, a[role], 32, decode(authority))
        base = accounts[a['mint_a']]
        raw = base64.b64decode(base['data'][0])
        extension = metadata(mint=decode(a['mint_a']))
        raw += bytes(83) + b'\1' + struct.pack('<HH', 18, 64) + bytes(32) + decode(a['mint_a'])
        raw += struct.pack('<HH', 19, len(extension)) + extension
        base['data'][0] = base64.b64encode(raw).decode()
        base['owner'] = ll.TOKEN_2022_PROGRAM
        accounts[a['vault_a']]['owner'] = ll.TOKEN_2022_PROGRAM
    return accounts, a


class World:
    """Index, RPC and quote providers driven by one fake clock (no sockets)."""

    def __init__(self, clock, creations, *, latency_ms=150, crash=None, index_down=None):
        self.clock, self.creations, self.latency = clock, creations, latency_ms
        self.crash, self.index_down = crash, index_down
        self.calls = []
        self.throttled = set()

    def slot(self, at=None):
        return 1000 + ((self.clock() if at is None else at) - T0) // 400

    def _respond(self, value, **kwargs):
        self.clock.ms += self.latency
        return Response(value, **kwargs)

    def get(self, url, **kwargs):
        self.calls.append((self.clock(), 'GET', url, copy.deepcopy(kwargs.get('params'))))
        if url == cp.INDEX_URL:
            now = self.clock()
            if self.index_down and self.index_down[0] <= now < self.index_down[1]:
                return self._respond(None, status=500)
            rows = [c['row'] for c in self.creations if c['listed_at'] <= now]
            rows.sort(key=lambda row: row.get('createAt', 0), reverse=True)
            rows.append({'mint': 'invalid-identity', 'poolId': 'x'})
            return self._respond({'success': True, 'data': {'rows': rows[:100]}})
        assert url == RAYDIUM_QUOTE_URL
        params = kwargs['params']
        side = 'buy' if params['inputMint'] == SOL_MINT else 'sell'
        mint = params['outputMint'] if side == 'buy' else params['inputMint']
        creation = next((c for c in self.creations if c['row']['mint'] == mint and c['accounts']), None)
        if creation is None:
            return self._respond({'id': 'synthetic', 'success': False, 'msg': 'ROUTE_NOT_FOUND'})
        key = (mint, side, params['amount'])
        if creation.get('throttle_first') == (side, params['amount']) and key not in self.throttled:
            self.throttled.add(key)
            return self._respond(None, status=429, headers={'Retry-After': '1'})
        if side == 'buy':
            output = str(int(params['amount']) * 25_000)
            return self._respond(quote_payload(SOL_MINT, mint, params['amount'], output, output))
        offset = self.clock() - creation['create_at']
        returns = creation.get('sell_returns')
        if returns is None:
            return self._respond({'id': 'synthetic', 'success': False, 'msg': 'ROUTE_NOT_FOUND'})
        spent = int(params['amount']) // 25_000
        bucket = 900_000 if 900_000 <= offset < 3_600_000 else (300_000 if offset < 900_000 else 3_600_000)
        output = str(spent * returns[bucket][0] // returns[bucket][1])
        return self._respond(quote_payload(mint, SOL_MINT, params['amount'], output, output))

    def post(self, url, *, json=None, **kwargs):
        method, params = json['method'], json['params']
        self.calls.append((self.clock(), 'POST', url, method))
        if self.crash is not None and self.crash(method, params, self.clock()):
            self.crash = None
            raise Crash()
        if method == 'getSignaturesForAddress':
            creation = next((c for c in self.creations if c['row']['poolId'] == params[0]
                             and c['accounts']), None)
            page = [] if creation is None else [dict(
                signature=creation['signature'], slot=creation['slot'], err=None,
                blockTime=creation['create_at'] // 1000)]
            return self._respond({'jsonrpc': '2.0', 'id': 1, 'result': page})
        if method == 'getTransaction':
            creation = next(c for c in self.creations if c['signature'] == params[0])
            row = creation['row']
            tx = dict(blockTime=creation['create_at'] // 1000, slot=creation['slot'],
                      transaction=dict(signatures=[creation['signature']],
                                       message=dict(accountKeys=[dict(pubkey='fee-payer', signer=True)],
                                                    instructions=[instruction(row['mint'], creator=CREATOR,
                                                                              pool=row['poolId'])])),
                      meta=dict(err=None, innerInstructions=[], fee=5000))
            return self._respond({'jsonrpc': '2.0', 'id': 1, 'result': tx})
        if method == 'getMultipleAccounts':
            # Each bank belongs to the creation whose pool is requested, so
            # shared config/platform addresses keep that creation's bytes.
            owner = next((c for c in self.creations if c['row']['poolId'] in params[0]), None)
            accounts = ({} if owner is None else
                        owner.get('accounts_at', lambda c, t: c['accounts'])(owner, self.clock()))
            values = [copy.deepcopy(accounts.get(address)) for address in params[0]]
            return self._respond({'jsonrpc': '2.0', 'id': 1,
                                  'result': {'context': {'slot': self.slot()}, 'value': values}})
        if method == 'getBlockTime':
            return self._respond({'jsonrpc': '2.0', 'id': 1,
                                  'result': (T0 + (params[0] - 1000) * 400) // 1000})
        raise AssertionError('unexpected method ' + method)


def left_curve_after_300(creation, now):
    accounts = copy.deepcopy(creation['accounts'])
    if now - creation['create_at'] >= 300_000:
        mutate_account(accounts, creation['addresses']['pool'], 17, 1)
    return accounts


def world_creations(clock):
    def make(index, accounts, addresses, create_at, **extra):
        row = dict(mint=addresses['mint_a'], poolId=addresses['pool'], mintB={'address': SOL_MINT},
                   creator=CREATOR, createAt=create_at, configId=addresses['config'])
        value = dict(row=row, accounts=accounts, addresses=addresses, create_at=create_at,
                     listed_at=create_at + 10_000, signature=ALPHABET[index] * 88,
                     slot=1000 + (create_at - T0) // 400)
        value.update(extra)
        return value
    pre = [dict(row=dict(mint=encode(bytes([200 + i]) * 32), poolId=encode(bytes([210 + i]) * 32),
                         mintB={'address': SOL_MINT}, creator=CREATOR, createAt=T0 - 3_600_000 + i),
                listed_at=0, create_at=T0 - 3_600_000 + i, accounts={}, signature=ALPHABET[40 + i] * 88,
                slot=1) for i in range(2)]
    late = dict(row=dict(mint=encode(bytes([230]) * 32), poolId=encode(bytes([231]) * 32),
                         mintB={'address': SOL_MINT}, creator=CREATOR, createAt=T0 - 600_000),
                listed_at=T0 + 30_000, create_at=T0 - 600_000, accounts={},
                signature=ALPHABET[45] * 88, slot=1)
    a1, d1 = fixture()
    a2, d2 = variant(40, qualified=True)
    a3, d3 = variant(60, qualified=False)
    a4, d4 = variant(80, qualified=False)
    return pre + [late,
        make(1, a1, d1, T0 + 20_000),
        make(2, a2, d2, T0 + 50_000, sell_returns={300_000: (9, 10), 900_000: (8, 10),
                                                   3_600_000: (5, 10)}),
        make(3, a3, d3, T0 + 80_000, accounts_at=left_curve_after_300,
             throttle_first=('buy', '500000000')),
        make(4, a4, d4, T0 + 100_000, listed_at=T0 + 300_000),
    ]


@pytest.fixture
def frozen_clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(collect, 'now_ms', clock)
    monkeypatch.setattr(cp, 'now_ms', clock)
    return clock


def run_identity(quota=None):
    p, a = protocol(), quota or authorization()
    ph, ah = cs.sha256_of(p), cs.sha256_of(a)
    return {'schema': cs.CENSUS_SCHEMA, 'run_id': 'census-synthetic0001', 'protocol_sha256': ph,
            'authorization_sha256': ah, 'preregistration_sha256': cs.preregistration_sha256(ph, ah),
            'source_revision': 'a' * 40, 'created_at_ms': T0 - 1_000}


def census(run_dir, clock, world, **kwargs):
    quota = kwargs.pop('authorization', None) or authorization()
    run = kwargs.pop('run', None) or run_identity(quota)
    if not (Path(run_dir) / 'run.json').exists():
        cs.prepare_run_dir(run_dir, run)
    return cs.CensusRun(run_dir, transport=world, run=run, protocol=protocol(),
                        authorization=quota,
                        clock_ms=clock, monotonic_ms=clock, sleep=clock.sleep,
                        store_clock_ms=clock, provenance='synthetic',
                        limits=kwargs.pop('limits', {'segment_max_records': 150,
                                                     'segment_max_bytes': 8 * 1024 * 1024,
                                                     'segment_max_duration_ms': 1_800_000}),
                        **kwargs)


def by_mint(report, mint):
    return next(c for c in report['creations'] if c['mint'] == mint)


# -- pre-registration ------------------------------------------------------

def test_committed_protocol_is_the_frozen_code_protocol_and_hash_is_recorded():
    registered = json.loads(PROTOCOL_PATH.read_text())
    digest = cs.validate_protocol(registered)
    recorded = (PROTOCOL_PATH.parent / 'protocol.sha256').read_text().split()[0]
    assert digest == recorded == cs.sha256_of(registered)
    assert registered['universe']['independent_reference'] is None
    assert registered['analysis']['economic_verdict'] == 'not_part_of_census'


@pytest.mark.parametrize('path,value', [
    (('schedule', 'state_offsets_ms'), [60000, 300000, 900000]),
    (('schedule', 'buy_sizes_lamports'), [500000000, 1000000000.0]),
    (('universe', 'price_volume_score_filter'), 'top_volume'),
    (('strategy_free',), 1), (('registered_at_ms',), True), (('registered_at_ms',), 2**62),
])
def test_any_protocol_change_is_a_new_unsupported_protocol(path, value):
    changed = protocol()
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(cs.CensusPolicyError):
        cs.validate_protocol(changed)
    with pytest.raises(cs.CensusPolicyError):
        cs.validate_protocol(dict(protocol(), extra='field'))


def test_committed_authorization_template_cannot_authorize_any_request():
    template = json.loads((PROTOCOL_PATH.parent / 'authorization.template.json').read_text())
    registered = json.loads(PROTOCOL_PATH.read_text())
    assert template['protocol_sha256'] == cs.sha256_of(registered)
    with pytest.raises(cs.CensusPolicyError):
        cs.validate_authorization(template, registered)


@pytest.mark.parametrize('changes', [
    {'spend_authorized': True}, {'wallet_or_signing_authorized': 1},
    {'subscriptions_authorized': None}, {'protocol_sha256': '0' * 64},
    {'approved_by': ''}, {'approved_at_ms': T0 - 20_000}, {'max_creations': 1001},
    {'max_enrollment_duration_ms': 43_200_001}, {'max_creations': 0},
    {'request_budgets': {cs.RPC: 13, cs.QUOTE: 200, cs.INDEX: 100}},
    {'request_budgets': {cs.RPC: 500, cs.QUOTE: 200, cs.INDEX: 1}},
    {'request_budgets': {cs.RPC: 500, cs.QUOTE: 200}},
    {'request_budgets': {cs.RPC: 20_001, cs.QUOTE: 200, cs.INDEX: 100}},
    {'network_scope': 'any'},
])
def test_authorization_never_widens_quota_spend_or_scope(changes):
    assert cs.validate_authorization(authorization(), protocol(), now_ms=T0)
    with pytest.raises(cs.CensusPolicyError):
        cs.validate_authorization(authorization(**changes), protocol(), now_ms=T0)


def git(repo, *args):
    return subprocess.run(['git', '-c', 'user.email=synthetic@example.invalid', '-c',
                           'user.name=synthetic', '-c', 'commit.gpgsign=false', *args],
                          cwd=repo, check=True, capture_output=True, text=True)


def test_git_preflight_requires_committed_unmodified_preregistration(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    plan = repo / 'protocol.json'
    plan.write_text('{}')
    with pytest.raises(cs.CensusPolicyError):
        cs.git_preflight(repo, [plan])
    git(repo, 'add', 'protocol.json')
    git(repo, 'commit', '-q', '-m', 'freeze')
    head = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    assert cs.git_preflight(repo, [plan]) == head
    plan.write_text('{"edited": true}')
    with pytest.raises(cs.CensusPolicyError):
        cs.git_preflight(repo, [plan])
    with pytest.raises(cs.CensusPolicyError):
        cs.git_preflight(repo, [tmp_path / 'outside.json'])


def test_cli_refuses_network_without_flag_or_owner_quota(tmp_path, capsys):
    template = PROTOCOL_PATH.parent / 'authorization.template.json'
    with pytest.raises(SystemExit):
        cs.main(['run', '--protocol', str(PROTOCOL_PATH), '--authorization', str(template),
                 '--run-dir', str(tmp_path / 'run')])
    with pytest.raises(cs.CensusPolicyError):
        cs.main(['run', '--network', '--protocol', str(PROTOCOL_PATH), '--authorization',
                 str(template), '--run-dir', str(tmp_path / 'run')])
    assert not (tmp_path / 'run').exists()
    printed = cs.main(['hash', '--protocol', str(PROTOCOL_PATH)])
    assert printed['protocol_sha256'] == cs.sha256_of(json.loads(PROTOCOL_PATH.read_text()))
    capsys.readouterr()


# -- transport policy --------------------------------------------------------

def session(clock, transport, budgets=None):
    return cs.CensusSession(transport, budgets or {cs.RPC: 5, cs.QUOTE: 2, cs.INDEX: 1},
                            clock_ms=clock, monotonic_ms=clock)


def rpc_body(method):
    return {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': []}


async def enter(context):
    async with context as response:
        return response


@pytest.mark.parametrize('method', ['sendTransaction', 'simulateTransaction', 'requestAirdrop',
                                    'getProgramAccounts'])
def test_census_inherits_read_only_method_policy(method):
    clock, transport = Clock(), Transport()
    with pytest.raises(cs.ReadOnlyPolicyError):
        session(clock, transport).post(cs.RPC_URL, json=rpc_body(method))
    assert transport.calls == []


def test_census_refuses_unregistered_destinations_before_any_count():
    census_session = session(Clock(), Transport())
    for url in (collect.FX_URL, 'https://example.invalid', cp.INDEX_URL + '/x'):
        with pytest.raises(cs.ReadOnlyPolicyError):
            census_session.get(url, params={'sort': 'new'})
    assert census_session.requests_used == 0


def test_budget_tokens_and_backoff_are_enforced_before_transport():
    clock = Clock()
    transport = Transport(gets=[Response(None, status=429, headers={'Retry-After': '45'})],
                          posts=[Response({'jsonrpc': '2.0', 'id': 1, 'result': 1})] * 6)
    census_session = session(clock, transport)
    for _ in range(3):
        asyncio.run(enter(census_session.post(cs.RPC_URL, json=rpc_body('getBlockTime'))))
    with pytest.raises(cs.ReadOnlyPolicyError, match='local_rate_limit'):
        asyncio.run(enter(census_session.post(cs.RPC_URL, json=rpc_body('getBlockTime'))))
    assert census_session.wait_for_tokens_ms(cs.RPC, 1) == 500
    clock.ms += 500
    asyncio.run(enter(census_session.post(cs.RPC_URL, json=rpc_body('getBlockTime'))))
    clock.ms += 10_000
    asyncio.run(enter(census_session.post(cs.RPC_URL, json=rpc_body('getBlockTime'))))
    with pytest.raises(cs.ReadOnlyPolicyError, match='budget'):
        clock.ms += 10_000
        asyncio.run(enter(census_session.post(cs.RPC_URL, json=rpc_body('getBlockTime'))))
    assert census_session.used[cs.RPC] == 5 and len([c for c in transport.calls if c[0] == 'POST']) == 5
    params = {'inputMint': SOL_MINT, 'outputMint': collect.USDC_MINT, 'amount': '1',
              'slippageBps': '100', 'txVersion': 'V0'}
    response = asyncio.run(enter(census_session.get(RAYDIUM_QUOTE_URL, params=params,
                                                    allow_redirects=False)))
    assert response.status == 429 and census_session.backoff_remaining_ms(cs.QUOTE) == 45_000
    assert census_session.throttles[0]['retry_after_seconds'] == 45
    clock.ms += 5_000
    with pytest.raises(cs.ProviderBackoffError):
        asyncio.run(enter(census_session.get(RAYDIUM_QUOTE_URL, params=params,
                                             allow_redirects=False)))
    assert all(call[2]['allow_redirects'] is False for call in transport.calls)


def test_census_rows_keep_every_row_without_selection_or_metadata():
    _, a = fixture()
    rows = [{'mint': a['mint_a'], 'poolId': a['pool'], 'mintB': {'address': 'other'},
             'createAt': 5, 'marketCap': 10**9, 'metadata': {'api_key': 'not-retained'}},
            {'mint': a['mint_a'], 'poolId': a['pool']}, None, {'mint': SOL_MINT, 'poolId': a['pool']}]
    records, replay_input, total = cs.census_rows({'success': True, 'data': {'rows': rows}})
    assert total == 4 and [r['row_status'] for r in records] == [
        'valid', 'duplicate_in_response', 'invalid_identity', 'invalid_identity']
    assert 'not-retained' not in json.dumps(replay_input) and 'marketCap' not in json.dumps(replay_input)
    with pytest.raises(ValueError):
        cs.census_rows({'success': True, 'data': {'rows': {}}})


# -- end-to-end synthetic census ---------------------------------------------

def test_synthetic_census_counts_every_creation_and_never_imputes(tmp_path, frozen_clock):
    creations = world_creations(frozen_clock)
    world = World(frozen_clock, creations)
    run_dir = tmp_path / 'run'
    summary = asyncio.run(census(run_dir, frozen_clock, world).start())
    assert summary['enrolled'] == 4 and summary['export_failures'] == []
    assert summary['close_reason'] == 'authorized_max_enrollment_duration_elapsed'
    assert summary['segments'] > 1
    assert not any(path.suffix == '.sqlite' for path in (run_dir / 'bundles').rglob('*'))
    allowed = {('POST', cs.RPC_URL), ('GET', RAYDIUM_QUOTE_URL), ('GET', cp.INDEX_URL)}
    assert {(call[1], call[2]) for call in world.calls} <= allowed
    quote_times = [call[0] for call in world.calls if call[2] == RAYDIUM_QUOTE_URL]
    assert all(b - a >= 1000 for a, b in zip(quote_times, quote_times[1:]))
    for provider, used in summary['requests_used'].items():
        assert used <= authorization()['request_budgets'][provider]

    report = cr.analyze(run_dir)
    assert report == cr.analyze(run_dir)
    assert report['run_complete'] is True and report['tasks_terminal'] == report['tasks_total'] == 52
    assert report['population_enrolled'] == 4 and report['protocol_deviations']
    assert report['coverage']['coverage_of_all_launchlab_creations'] is None
    dispositions = report['coverage']['universe_disposition_counts']
    assert dispositions == {'enrolled': 4, 'pre_window_baseline': 2, 'pre_window_late_listed': 1}
    for size in ('500000000', '1000000000'):
        for label in ('primary_buy60_sell900', 'secondary_local_curve_buy60_sell900'):
            output = report['outputs'][label][size]
            assert sum(output['category_counts'].values()) == output['population'] == 4

    legacy, sellable, migrated, late = (by_mint(report, c['row']['mint']) for c in creations[3:])
    assert legacy['verification'] == sellable['verification'] == 'creation_verified'
    assert legacy['primary']['1000000000']['category'] == 'sell:provider_unavailable:provider_rejected'
    assert legacy['secondary']['1000000000']['category'] == 'local_entry_unavailable:published_identity_check_failed'
    assert sellable['primary']['1000000000'] == {'category': 'observed', 'gross_return': '-0.200000000'}
    assert sellable['primary']['500000000']['gross_return'] == '-0.200000000'
    assert sellable['secondary']['1000000000']['category'] == 'observed'
    assert sellable['buys']['1000000000']['implied_lamports_per_atomic'] == '0.000040000'
    buy = sellable['buys']['1000000000']
    assert buy['source_time_ms'] is None and buy['source_slot'] is None  # provider gives none
    assert buy['requested_at_ms'] <= buy['received_at_ms'] <= buy['available_at_ms']
    sell = sellable['sells']['900000:1000000000']
    assert sell['http_status'] == 200 and sell['output_lamports'] == '800000000'
    assert sell['source_time_ms'] is None and sell['received_at_ms'] <= sell['available_at_ms']
    assert legacy['sells']['900000:1000000000']['http_status'] == 200
    assert sellable['creation_received_at_ms'] <= sellable['creation_available_at_ms']
    assert sellable['creation_slot'] == creations[4]['slot']
    assert migrated['buys']['500000000']['category'] == 'provider_unavailable:http_429'
    assert migrated['buys']['1000000000']['category'] == 'missed:provider_backoff'
    assert migrated['sells']['900000:500000000']['category'] == 'not_attempted:no_plus60_buy_quantity'
    assert migrated['migration']['left_active_curve_within_window'] is True
    assert migrated['migration']['first_offset_not_active_ms'] == 300000
    assert late['states']['60000']['category'] == 'missed:detected_after_tolerance'
    assert late['primary']['1000000000']['category'] == 'buy:missed:detected_after_tolerance'
    assert late['states']['300000']['category'] == 'observed'
    assert late['detection']['category'] == 'observed'
    assert late['index_detection_latency_ms'] == late['enrolled_at_ms'] - late['creation_block_time_ms']
    assert 200_000 <= late['index_detection_latency_ms'] < 200_000 + 15_000 + 1_000
    primary = report['outputs']['primary_buy60_sell900']['1000000000']
    assert primary['observed_count'] == 1 and primary['observed_conditional_quantiles']['0.5'] == '-0.200000000'
    exit_900 = report['outputs']['sellable_exit']['900000:1000000000']
    assert exit_900['sellable_quoted'] == 1 and exit_900['denominator_all_enrolled'] == 4
    assert exit_900['denominator_plus60_buy_quoted'] == 2 and exit_900['denominator_sell_dispatched'] == 2
    assert report['outputs']['migration_within_window']['left_active_curve'] == 1
    change = report['outputs']['state_change_vs_plus60']['900000']
    assert change['pairs_observed'] == 3 and change['pairs_unavailable'] == 1  # late creation lacks +60
    assert change['real_b_equal'] == 3 and change['real_b_ratio_quantiles']['0.5'] == '1.000000000'
    for creation in report['creations']:
        assert creation['detection']['category'] == 'observed'
        assert creation['detection']['latency_ms'] > 0
        for offset, state in creation['states'].items():
            if state['category'] == 'observed':
                assert state['within_tolerance_vs_verified_creation'] is True
                assert state['received_at_ms'] <= state['available_at_ms'] <= state['analysis_at_ms']
    assert report['economic_verdict'] == 'not_part_of_census'
    assert report['budget']['throttle_events'] == 1
    output = tmp_path / 'report.json'
    first = cr.main(['--evidence', str(run_dir), '--output', str(output)])
    second_path = tmp_path / 'again.json'
    assert cr.main(['--evidence', str(run_dir), '--output', str(second_path)]) == first
    assert output.read_bytes() == second_path.read_bytes()


def test_tampered_missing_or_relinked_evidence_is_refused(tmp_path, frozen_clock):
    run_dir = tmp_path / 'run'
    world = World(frozen_clock, world_creations(frozen_clock))
    asyncio.run(census(run_dir, frozen_clock, world,
                       authorization=authorization(max_enrollment_duration_ms=60_000),
                       limits={'segment_max_records': 40, 'segment_max_bytes': 8 * 1024 * 1024,
                               'segment_max_duration_ms': 1_800_000}).start())
    cr.analyze(run_dir)
    archive = run_dir / 'bundles' / '000002' / 'events.jsonl.gz'
    original = archive.read_bytes()
    lines = gzip.decompress(original).splitlines()
    lines[1] = lines[1].replace(b'"synthetic"', b'"live"')
    archive.write_bytes(gzip.compress(b'\n'.join(lines) + b'\n', mtime=0))
    with pytest.raises(ValueError):
        cr.analyze(run_dir)
    archive.write_bytes(original)
    anchor = run_dir / 'anchors' / '000002.json'
    saved = anchor.read_bytes()
    anchor.unlink()
    with pytest.raises(cs.CensusPolicyError):
        cr.analyze(run_dir)
    anchor.write_bytes(saved.replace(b'"records"', b'"records_"'))
    with pytest.raises((cs.CensusPolicyError, ValueError)):
        cr.analyze(run_dir)
    anchor.write_bytes(saved)
    cr.analyze(run_dir)


def test_new_census_refuses_existing_run_directory(tmp_path):
    (tmp_path / 'run').mkdir()
    with pytest.raises(cs.CensusPolicyError):
        cs.prepare_run_dir(tmp_path / 'run', run_identity())


def test_quota_reservation_stops_enrollment_and_keeps_later_rows_in_universe(tmp_path, frozen_clock):
    run_dir = tmp_path / 'run'
    world = World(frozen_clock, world_creations(frozen_clock))
    budget = authorization(request_budgets={cs.RPC: 28, cs.QUOTE: 200, cs.INDEX: 100})
    summary = asyncio.run(census(run_dir, frozen_clock, world, authorization=budget).start())
    assert summary['enrolled'] == 2
    assert summary['close_reason'] == 'request_quota_reservation_insufficient'
    report = cr.analyze(run_dir)
    dispositions = report['coverage']['universe_disposition_counts']
    assert dispositions.get('not_enrolled_after_stop:request_quota_reservation_insufficient') == 1
    assert report['budget']['used'][cs.RPC] <= 28


def test_crash_resume_closes_segment_never_retries_and_marks_missed(tmp_path, frozen_clock):
    creations = world_creations(frozen_clock)
    sellable = creations[4]

    def crash(method, params, now):
        return (method == 'getBlockTime'
                and now - sellable['create_at'] >= 300_000 and now - sellable['create_at'] < 360_000)
    run_dir = tmp_path / 'run'
    first = census(run_dir, frozen_clock, World(frozen_clock, creations, crash=crash))
    with pytest.raises(Crash):
        asyncio.run(first.start())
    first.store.close()  # the process died; committed rows persist
    frozen_clock.ms += 400_000
    resumed = census(run_dir, frozen_clock, World(frozen_clock, creations))
    summary = asyncio.run(resumed.resume())
    assert summary['export_failures'] == []
    report = cr.analyze(run_dir)
    assert report['run_complete'] is True and report['budget']['resumes'] == 1
    assert report['tasks_terminal'] == report['tasks_total']
    assert report['coverage']['open_gaps_by_reason']['run_interrupted'] == 1
    interrupted = by_mint(report, sellable['row']['mint'])
    assert interrupted['states']['300000']['category'] == 'interrupted_in_flight:run_interrupted'
    assert interrupted['states']['900000']['category'] == 'observed'
    assert interrupted['sells']['300000:1000000000']['category'] == 'missed:run_interrupted'
    assert interrupted['primary']['1000000000']['gross_return'] == '-0.200000000'
    events, _, segments = cs.load_segments(run_dir, cs.read_run(run_dir))
    resumed_event = next(e for e in events if e['outcome'] == 'census_resumed')
    assert resumed_event['payload']['in_flight_tasks'] == ['00002:state:300000:-']
    closed = [e for e in events if e['outcome'] == 'segment_closed']
    assert any(e['payload']['reason'] == 'interrupted_closed_on_resume' for e in closed)
    assumed = resumed_event['payload']['assumed_requests_used']
    started = [e for e in events if e['outcome'] == 'census_task_started'
               and e['payload']['task_id'] == '00002:state:300000:-']
    assert len(started) == 1  # never retried after the crash
    assert assumed[cs.RPC] >= 3 and assumed[cs.INDEX] >= 1
    with pytest.raises(cs.CensusPolicyError):
        asyncio.run(census(run_dir, frozen_clock, World(frozen_clock, creations)).resume())


def test_resume_refuses_another_run_identity(tmp_path, frozen_clock):
    run_dir = tmp_path / 'run'
    creations = world_creations(frozen_clock)
    first = census(run_dir, frozen_clock, World(frozen_clock, creations,
                                                crash=lambda method, *_: method == 'getTransaction'))
    with pytest.raises(Crash):
        asyncio.run(first.start())
    first.store.close()
    other = dict(run_identity(), run_id='census-other000001')
    with pytest.raises(cs.CensusPolicyError):
        asyncio.run(cs.CensusRun(run_dir, transport=World(frozen_clock, creations), run=other,
                                 protocol=protocol(), authorization=authorization(),
                                 clock_ms=frozen_clock, monotonic_ms=frozen_clock,
                                 sleep=frozen_clock.sleep, store_clock_ms=frozen_clock).resume())


def test_poll_failure_gap_closes_on_overlap_and_index_flood_stays_open(tmp_path, frozen_clock):
    flood = [dict(row=dict(mint=encode(bytes([1, i]) + bytes(30)), poolId=encode(bytes([2, i]) + bytes(30)),
                           mintB={'address': SOL_MINT}, creator=CREATOR, createAt=T0 + 200_000 + i),
                  listed_at=T0 + 200_000, create_at=T0 + 200_000 + i, accounts={},
                  signature=ALPHABET[50] * 88, slot=1) for i in range(100)]
    world = World(frozen_clock, world_creations(frozen_clock) + flood,
                  index_down=(T0 + 10_000, T0 + 40_000))
    run_dir = tmp_path / 'run'
    summary = asyncio.run(census(run_dir, frozen_clock, world,
                                 authorization=authorization(max_creations=4)).start())
    assert summary['enrolled'] == 4 and summary['close_reason'] == 'authorized_max_creations_enrolled'
    report = cr.analyze(run_dir)
    coverage = report['coverage']
    assert coverage['polls_failed'] == 2 and coverage['poll_continuity_counts']['overflow_possible'] == 1
    assert coverage['gap_event_counts']['closed:discovery_poll_failed_continuity_unknown'] == 1
    assert 'discovery_poll_failed_continuity_unknown' not in coverage['open_gaps_by_reason']
    assert coverage['open_gaps_by_reason']['discovery_continuity_not_established'] == 1
    assert coverage['universe_disposition_counts'][
        'not_enrolled_after_stop:authorized_max_creations_enrolled'] == 99
    unknown = by_mint(report, flood[0]['row']['mint'])
    assert unknown['verification'] == 'creation_not_verified'
    assert unknown['states']['60000']['category'] == 'state_pool_account_absent'
    assert unknown['buys']['500000000']['category'] == 'provider_unavailable:provider_rejected'
    assert unknown['detection'] == {'category': 'creation_not_verified'}
    assert sum(report['outputs']['primary_buy60_sell900']['1000000000']['category_counts'].values()) == 4


def test_ready_tasks_run_earliest_deadline_first_so_verification_waits(tmp_path, frozen_clock):
    run = census(tmp_path / 'run', frozen_clock, World(frozen_clock, []))
    verify, state = cs.creation_tasks(1, T0 - 60_000, T0 - 1_000, T0 + 10**7)[:2]
    late_verify = dict(verify, task_id='00002:verify:-:-', seq=2, due_at_ms=T0 - 70_000)
    for task in (late_verify, state):
        heapq.heappush(run.heap, (cs._sort_key(task), task['task_id'], task))
    assert run.heap[0][2]['kind'] == 'verify'  # plain ready-time order would pick it first
    assert run._pop_ready(T0)['kind'] == 'state'
    assert run._pop_ready(T0)['kind'] == 'verify'


def test_journaled_backoff_survives_a_resume():
    clock = Clock()
    census_session = session(clock, Transport())
    census_session.restore_backoff([{'provider': cs.QUOTE, 'observed_at_ms': T0 - 10_000,
                                     'backoff_ms': 30_000, 'http_status': 429,
                                     'retry_after_seconds': None},
                                    {'provider': cs.RPC, 'observed_at_ms': T0 - 40_000,
                                     'backoff_ms': 30_000, 'http_status': 429,
                                     'retry_after_seconds': None}])
    assert census_session.backoff_remaining_ms(cs.QUOTE) == 20_000
    assert census_session.backoff_remaining_ms(cs.RPC) == 0

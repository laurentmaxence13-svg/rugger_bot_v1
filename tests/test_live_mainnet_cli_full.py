"""Actual mainnet CLI entrypoint tested over a complete fake HTTP JSON-RPC server.

No sockets, no wallets, no live keys, no network access and no transaction
submission are possible in this fixture. Unlike the other component tests, this
runs the CLI, aiohttp-style session, strict HttpJsonRpcTransport, SolanaRpc,
migration/Ed25519, onchain pin verification, CPMM build, unsigned simulation,
and writes/reads the private 0600 report in ONE continuous flow.
"""
import asyncio
import json
import os
import time

import aiohttp

from bot.p3 import transport as transport_module
from bot.live.readonly_plan import MAINNET_GENESIS, PUBLIC_MAINNET_RPC
from bot.live import readonly_cli as cli
from test_live_cpmm_rpc_integration import SyntheticSolanaTransport
from test_live_readonly_plan import _plan
from test_live_migration_evidence import OLD


class MainnetFixture(SyntheticSolanaTransport):
    async def __call__(self,method,params):
        if method=='getGenesisHash':
            self.calls.append((method,params))
            return MAINNET_GENESIS
        return await super().__call__(method,params)


class Response:
    status=200

    def __init__(self,body):
        self.body=body
        self.content=self

    async def iter_chunked(self,limit):
        assert limit>0
        yield self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self,*args):
        return False


class FakeRequest:
    def __init__(self,simulation,envelope,history):
        self.simulation=simulation
        self.envelope=envelope
        self.history=history

    async def __aenter__(self):
        method=self.envelope['method']
        assert method!='sendTransaction', 'No financial route should be present'
        self.history.append((self.envelope['id'],method))
        value=await self.simulation(method,self.envelope['params'])
        self.response=Response(json.dumps(dict(jsonrpc='2.0',
            id=self.envelope['id'],result=value),
            separators=(',',':')).encode())
        return self.response

    async def __aexit__(self,*args):
        return False

    @property
    def status(self):return self.response.status

    @property
    def content(self):return self.response.content


def fake_http(monkeypatch,simulation):
    history=[]

    class Session:
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False
            assert isinstance(kwargs['cookie_jar'],aiohttp.DummyCookieJar)

        async def __aenter__(self):return self

        async def __aexit__(self,*args):return False

        def post(self,endpoint,**options):
            assert endpoint==PUBLIC_MAINNET_RPC
            assert options['allow_redirects'] is False
            assert options['proxy']=='http://proxy.synthetic:8080'
            assert 'json' in options and 'data' not in options
            assert options['json']['method']!='sendTransaction'
            return FakeRequest(simulation,options['json'],history)

    monkeypatch.setattr(aiohttp,'ClientSession',Session)
    monkeypatch.setattr(transport_module,'managed_proxy_routes',
        lambda endpoints:{PUBLIC_MAINNET_RPC:'http://proxy.synthetic:8080'})
    monkeypatch.setattr(transport_module,'connector',
        lambda recorder,proxy_host:None)
    monkeypatch.setattr(transport_module,'disable_retries',lambda session:None)
    return history


def prepared_plan(simulation):
    plan=_plan()
    plan['program_pins']=simulation.program_pins
    plan['migration_signature']=simulation.signature
    plan['original_launchlab_pool']=OLD
    plan['amount_in']=simulation.pool['amount_in']
    plan['min_context_slot']=1234
    plan['rpc_endpoint']=PUBLIC_MAINNET_RPC
    plan['expected_genesis_hash']=MAINNET_GENESIS
    plan['max_rpc_requests']=18
    plan['max_transport_elapsed_seconds']=60
    return plan


def test_full_cli_bounded_simulation_emits_private_hashed_report_without_send(
        monkeypatch,tmp_path,capsys):
    fake=MainnetFixture()
    fake.block_time=int(time.time())
    http_history=fake_http(monkeypatch,fake)
    plan=prepared_plan(fake)
    plan_file=tmp_path/'plan.json'
    plan_file.write_text(json.dumps(plan))
    out=tmp_path/'private-receipt.json'
    code=cli.main(['--plan',str(plan_file),'--out',str(out),'--run-readonly'])
    assert code==0
    public=json.loads(capsys.readouterr().out)
    assert public['status']=='UNSIGNED_CPMM_ROUTE_SIMULATED'
    assert public['requests_used']==18
    assert public['financial_order_submitted'] is False
    assert public['live_ready_to_arm'] is False
    assert len(http_history)==18
    assert [id for id,method in http_history]==list(range(1,19))
    assert all(method!='sendTransaction' for _,method in http_history)
    report=json.loads(out.read_text())
    assert report['status']=='UNSIGNED_CPMM_ROUTE_SIMULATED'
    assert report['trade_sent'] is False
    assert report['signer_used'] is False
    assert report['wallet_armed'] is False
    assert report['live_ready_to_arm'] is False
    assert report['actual_read_only_evidence']['bank']['fee_source_context_slot']==1237
    assert report['actual_read_only_evidence']['unsigned_simulation'][
        'parsed_RPC_simulation_result']['err'] is None
    assert report['actual_read_only_evidence']['historical_signature_proof'][
        'cryptographic_signatures_verified'] is True
    assert os.stat(out).st_mode & 0o077==0


def test_cli_rejects_unknown_real_message_fee_without_second_submission(
        monkeypatch,tmp_path,capsys):
    fake=MainnetFixture()
    fake.block_time=int(time.time())
    original=fake.__call__
    async def faulty_call(method,params):
        if method=='getFeeForMessage':
            fake.calls.append((method,params))
            return dict(context=dict(slot=1237),value=None)
        return await original(method,params)
    fake_http(monkeypatch,faulty_call)
    plan=prepared_plan(fake)
    plan_file=tmp_path/'plan.json'
    plan_file.write_text(json.dumps(plan))
    out=tmp_path/'refusal.json'
    code=cli.main(['--plan',str(plan_file),'--out',str(out),'--run-readonly'])
    assert code==2
    public=json.loads(capsys.readouterr().out)
    assert public['status']=='REFUSED'
    assert public['requests_used']<=18
    report=json.loads(out.read_text())
    assert report['status']=='REFUSED'
    assert report['trade_sent'] is False
    assert report['actual_read_only_evidence']['unsigned_simulation'] is None
    assert sum(method=='sendTransaction' for method,_ in fake.calls)==0

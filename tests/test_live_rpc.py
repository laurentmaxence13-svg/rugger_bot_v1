"""RPC contract and independent transport gate, without sockets or user files."""
import asyncio
import base64

import pytest

from bot.live.rpc import SolanaRpc, HttpJsonRpcTransport, RpcError
from bot.p3.certification import _encode

KEY=_encode(bytes([7])*32)
SIG=_encode(bytes([8])*64)
RAW=b'\x01'+bytes([8])*64+b'test-only-wire'


class Transport:
    def __init__(self,result):self.result=result;self.calls=[]
    async def __call__(self,method,params):
        self.calls.append((method,params));return self.result


def run(awaitable):return asyncio.run(awaitable)


def test_unsigned_simulation_never_replaces_signed_message_blockhash():
    t=Transport(dict(context=dict(slot=123),value=dict(err=None,unitsConsumed=50000)))
    assert run(SolanaRpc(t).simulate_transaction(RAW,sig_verify=False))['err'] is None
    method,p=t.calls[0]
    assert method=='simulateTransaction' and base64.b64decode(p[0])==RAW
    assert p[1]['sigVerify'] is False and p[1]['replaceRecentBlockhash'] is False
    assert p[1]['encoding']=='base64'


def test_simulation_causal_slot_is_retained_and_old_or_missing_slot_refused():
    t=Transport(dict(context=dict(slot=123),value=dict(err=None)))
    assert run(SolanaRpc(t).simulate_transaction(RAW,sig_verify=False,min_context_slot=123))['context_slot']==123
    assert t.calls[-1][1][1]['minContextSlot']==123
    with pytest.raises(RpcError):run(SolanaRpc(t).simulate_transaction(RAW,sig_verify=False,min_context_slot=124))
    t.result.pop('context')
    with pytest.raises(RpcError):run(SolanaRpc(t).simulate_transaction(RAW,sig_verify=False))


@pytest.mark.parametrize('method',['signature_status','get_transaction','send_transaction'])
def test_invalid_signature_identity_is_sanitized_rpc_error(method):
    t=Transport('bad')
    with pytest.raises(RpcError):
        run(getattr(SolanaRpc(t),method)(RAW if method=='send_transaction' else 'bad'))


def test_send_no_implicit_retry_and_preflight_is_required():
    t=Transport(SIG)
    assert run(SolanaRpc(t).send_transaction(RAW))==SIG
    assert len(t.calls)==1
    assert t.calls[0][1][1]['maxRetries']==0
    assert t.calls[0][1][1]['skipPreflight'] is False


def test_status_absence_is_unknown_and_finalized_transaction_keeps_compiled_message():
    t=Transport(dict(value=[None]))
    assert run(SolanaRpc(t).signature_status(SIG)) is None
    assert t.calls[0][1][1]['searchTransactionHistory'] is True
    t.result=None
    assert run(SolanaRpc(t).get_transaction(SIG)) is None
    assert t.calls[-1][1][1]['encoding']=='json'
    assert t.calls[-1][1][1]['commitment']=='finalized'


@pytest.mark.parametrize('value',[True,-1,2**64,1.0,'10',None])
def test_rpc_balance_and_height_must_be_exact_uint64(value):
    t=Transport(dict(value=value))
    with pytest.raises(RpcError):run(SolanaRpc(t).get_balance(KEY))
    t.result=value
    with pytest.raises(RpcError):run(SolanaRpc(t).get_block_height())


@pytest.mark.parametrize('value',['01','-1','1.0','１２',str(2**64),1,True])
def test_token_inventory_has_canonical_atomic_quantity(value):
    with pytest.raises(RpcError):
        run(SolanaRpc(Transport(dict(value=dict(amount=value)))).get_token_account_balance(KEY))


def test_bank_context_floor_and_exact_account_count_are_enforced():
    t=Transport(dict(context=dict(slot=11),value=[None]))
    assert run(SolanaRpc(t).get_multiple_accounts([KEY],min_context_slot=10))['context']['slot']==11
    t.result['context']['slot']=9
    with pytest.raises(RpcError):run(SolanaRpc(t).get_multiple_accounts([KEY],min_context_slot=10))
    t.result=dict(context=dict(slot=11),value=[])
    with pytest.raises(RpcError):run(SolanaRpc(t).get_multiple_accounts([KEY],min_context_slot=10))


class NoHttp:
    def post(self,*a,**kw):raise AssertionError('Unexpected HTTP request')


def test_submission_requires_independent_transport_gate_before_any_request():
    transport=HttpJsonRpcTransport(NoHttp(),endpoint='https://api.mainnet.solana.com',
        proxy='http://proxy:8080')
    with pytest.raises(RpcError,match='admission'):
        run(SolanaRpc(transport).send_transaction(RAW))
    assert transport.used==0


@pytest.mark.parametrize('endpoint',['http://api.mainnet.solana.com','https://secret@api.example',
    'https://api.example/?api-key=secret','https://api.example/#token','https://api.example:80'])
def test_rpc_configuration_refuses_embedded_secrets_and_unverified_transport(endpoint):
    with pytest.raises(ValueError):
        HttpJsonRpcTransport(NoHttp(),endpoint=endpoint,proxy='http://proxy:8080')


class Content:
    def __init__(self,body):self.body=body
    async def iter_chunked(self,size):yield self.body


class Response:
    def __init__(self,body,status=200):self.content=Content(body);self.status=status
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass


class Http:
    def __init__(self,body,status=200):self.body=body;self.status=status;self.calls=[]
    def post(self,*args,**kwargs):
        self.calls.append(kwargs);return Response(self.body,self.status)


@pytest.mark.parametrize('body,status',[(b'{"jsonrpc":"2.0","id":2,"result":1}',200),
    (b'{"jsonrpc":"2.0","id":1,"error":{"message":"do-not-log"}}',200),
    (b'invalid',200),(b'limited',429)])
def test_blocking_rpc_error_stops_transport_without_retry_or_leaking_response(body,status):
    http=Http(body,status)
    transport=HttpJsonRpcTransport(http,endpoint='https://api.mainnet.solana.com',proxy='http://proxy:8080')
    with pytest.raises(RpcError) as error:run(transport('getBlockHeight',[]))
    assert 'do-not-log' not in str(error.value)
    with pytest.raises(RpcError):run(transport('getBlockHeight',[]))
    assert len(http.calls)==transport.used==1
    assert http.calls[0]['allow_redirects'] is False


def test_http_budget_and_request_identity_are_preserved():
    http=Http(b'{"jsonrpc":"2.0","id":1,"result":15}')
    t=HttpJsonRpcTransport(http,endpoint='https://api.mainnet.solana.com',proxy='http://proxy:8080',max_requests=1)
    assert run(t('getBlockHeight',[]))==15
    with pytest.raises(RpcError):run(t('getBlockHeight',[]))
    assert len(http.calls)==1


def test_financial_payload_rechecks_gate_after_connection_delay():
    from bot.live.rpc import _GuardedJsonPayload
    admitted=[True];written=[]
    class Writer:
        async def write(self,value):written.append(value)
    payload=_GuardedJsonPayload(b'public-test-json',RAW,lambda raw:admitted[0] and raw==RAW)
    admitted[0]=False
    with pytest.raises(RpcError,match='revoked'):
        run(payload.write(Writer()))
    with pytest.raises(RpcError,match='revoked'):
        run(payload.write_with_length(Writer(),None))
    with pytest.raises(RpcError,match='complete'):
        run(payload.write_with_length(Writer(),1))
    assert not written
    admitted[0]=True
    run(payload.write(Writer()))
    assert written==[b'public-test-json']


def test_rpc_get_block_time_is_exact_positive_source_epoch_not_caller_guess():
    rpc=Transport(1793295100)
    assert run(SolanaRpc(rpc).get_block_time(1235))==1793295100
    assert rpc.calls==[('getBlockTime',[1235])]


@pytest.mark.parametrize('invalid',[None,False,True,0,-1,1.5,'1793295100',2**64])
def test_rpc_get_block_time_missing_or_untyped_fails_closed(invalid):
    t=Transport(invalid)
    with pytest.raises(RpcError):
        run(SolanaRpc(t).get_block_time(1235))


@pytest.mark.parametrize('invalid',[None,True,0,-1,'1235'])
def test_rpc_get_block_time_rejects_noninteger_source_slot_without_request(invalid):
    t=Transport(1793295100)
    with pytest.raises(RpcError):
        run(SolanaRpc(t).get_block_time(invalid))
    assert t.calls==[]


def test_fee_receipt_requests_message_at_or_after_blockhash_bank_and_retains_context():
    t=Transport(dict(context=dict(slot=400),value=5000))
    result=run(SolanaRpc(t).get_fee_for_message_receipt(b'compiled-test-message',
                                                         min_context_slot=399))
    assert result==dict(context_slot=400,value=5000)
    assert t.calls==[('getFeeForMessage',[
        base64.b64encode(b'compiled-test-message').decode(),
        dict(commitment='confirmed',minContextSlot=399)])]


@pytest.mark.parametrize('reply',[
    dict(context=dict(slot=399),value=5000),
    dict(context=dict(slot=True),value=5000),
    dict(context=dict(slot=400),value=None),
    dict(context=dict(slot=400),value=0),
    dict(context=dict(slot=400),value=-1),
    dict(context=dict(slot=400),value='5000'),
    dict(value=5000),
    dict(context=None,value=5000),
    True,
])
def test_fee_receipt_invalid_or_older_bank_always_refused(reply):
    t=Transport(reply)
    with pytest.raises(RpcError):
        run(SolanaRpc(t).get_fee_for_message_receipt(b'compiled-test-message',
                                                      min_context_slot=400))


@pytest.mark.parametrize('invalid',[True,0,-1,'400',None])
def test_fee_receipt_invalid_floor_fails_before_transport(invalid):
    t=Transport(dict(context=dict(slot=400),value=5000))
    with pytest.raises(RpcError):
        run(SolanaRpc(t).get_fee_for_message_receipt(b'message',
                                                      min_context_slot=invalid))
    assert t.calls==[]



def test_rpc_method_trace_has_only_number_method_and_outcome_even_on_http_failure():
    http=Http(b'RPC SECRET private_wallet_token',status=429)
    transport=HttpJsonRpcTransport(http,endpoint='https://api.mainnet.solana.com',
                                   proxy='http://proxy:8080')
    with pytest.raises(RpcError):
        run(transport('getGenesisHash',[]))
    assert transport.method_trace==[
        dict(ordinal=1,method='getGenesisHash',outcome='failed')]
    assert 'SECRET' not in str(transport.method_trace)
    assert 'proxy' not in str(transport.method_trace)
    assert transport.used==1
    assert transport.stopped is True


def test_rpc_method_trace_preserves_request_order_and_never_logs_params():
    http=Http(b'{"jsonrpc":"2.0","id":1,"result":999}')
    transport=HttpJsonRpcTransport(http,endpoint='https://api.mainnet.solana.com',
                                   proxy='http://proxy:8080',max_requests=1)
    assert run(transport('getBlockHeight',[dict(private_arg='DO_NOT_LOG')]))==999
    assert transport.method_trace==[
        dict(ordinal=1,method='getBlockHeight',outcome='success')]
    assert 'DO_NOT_LOG' not in str(transport.method_trace)
    with pytest.raises(RpcError):
        run(transport('getBlockHeight',[dict(private_arg='SECRET')]))
    assert len(transport.method_trace)==1

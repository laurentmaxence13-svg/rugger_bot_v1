"""Two public program reads only; never quotes, wallet, simulation or submission.

Run only after publishing/readback of PROGRAM_PROBE_PLAN.json. A separate
process watchdog must bound this process to18+2seconds. Raw public code is
retained, but observing its hash never approves that code for execution.
"""
import asyncio
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.environ['RUGGER_NO_DOTENV']='1'
from bot.analyser.artifacts import atomic_write_json
from bot.live.evidence import UPGRADEABLE_LOADER
from bot.live.rpc import HttpJsonRpcTransport,SolanaRpc
from bot.p3.certification import PROGRAM,_decode,_encode,find_program_address
from bot.p3.transport import PhaseRecorder,connector,disable_retries,managed_proxy_routes
import aiohttp

RPC='https://api.mainnet.solana.com'
PROGRAMDATA=find_program_address((_decode(PROGRAM),),UPGRADEABLE_LOADER)[0]


def inspect_accounts(response):
    slot=response['context']['slot'];program,data=response['value']
    if (program['owner']!=UPGRADEABLE_LOADER or program['executable'] is not True
            or data['owner']!=UPGRADEABLE_LOADER or data['executable'] is not False):
        raise ValueError('program_owner_or_execution_flag_mismatch')
    raw=[]
    for account in (program,data):
        encoded=account['data']
        if type(encoded) is not list or encoded[1]!='base64':raise ValueError('raw_base64_required')
        raw.append(base64.b64decode(encoded[0],validate=True))
    p,d=raw
    if len(p)!=36 or struct.unpack_from('<I',p)[0]!=2 or p[4:]!=_decode(PROGRAMDATA):
        raise ValueError('canonical_programdata_binding_invalid')
    if len(d)<109 or struct.unpack_from('<I',d)[0]!=3 or d[12] not in (0,1):
        raise ValueError('programdata_layout_invalid')
    deployment=struct.unpack_from('<Q',d,4)[0]
    if deployment>slot or not d[45:].startswith(b'\x7fELF'):raise ValueError('deployed_code_invalid')
    return dict(program_id=PROGRAM,programdata_address=PROGRAMDATA,observed_slot=slot,
        deployment_slot=deployment,upgrade_authority=_encode(d[13:45]) if d[12] else None,
        ELF_bytes=len(d)-45,ELF_sha256=hashlib.sha256(d[45:]).hexdigest(),
        independently_approved=False,source_build_matches_deployed_code=None,
        evidence_scope='public_RPC_observation_of_current_code_bytes_not_code_approval')


async def capture(plan,output):
    routes=managed_proxy_routes((RPC,));records=[];started=time.monotonic_ns()
    phase=PhaseRecorder(lambda value:None)
    result=dict(schema='rugger-live-public-program-probe-v1',plan=plan,records=records,
        code_observation=None,stop_reason=None,financial_operation=False,
        live_ready_to_arm=False,source_authenticity_scope='verified_TLS_public_RPC_claims')
    async with aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),
            connector=connector(phase,proxy_host=urlsplit(routes[RPC]).hostname)) as session:
        disable_retries(session)
        transport=HttpJsonRpcTransport(session,endpoint=RPC,proxy=routes[RPC],
            max_requests=2,max_elapsed_seconds=16)
        async def retained(method,params):
            at=time.time_ns()//1_000_000
            row=dict(method=method,params=params,requested_at_ms=at,response=None,received_at_ms=None,error_type=None)
            records.append(row)
            try:
                value=await transport(method,params);row['received_at_ms']=time.time_ns()//1_000_000
                row['response']=value
                return value
            except BaseException as error:
                row['received_at_ms']=time.time_ns()//1_000_000;row['error_type']=type(error).__name__;raise
        rpc=SolanaRpc(retained)
        try:
            result['genesis_hash']=await rpc.genesis_hash()
            if result['genesis_hash']!=plan['expected_genesis_hash']:
                raise ValueError('unexpected_mainnet_genesis')
            response=await rpc.get_multiple_accounts([PROGRAM,PROGRAMDATA],min_context_slot=plan['minimum_context_slot'])
            result['code_observation']=inspect_accounts(response)
        except (ValueError,KeyError,TypeError,RuntimeError):
            result['stop_reason']='blocking_transport_or_public_program_evidence_error'
        finally:
            result.update(requests_used=transport.used,elapsed_ms=(time.monotonic_ns()-started)//1_000_000)
            # Output is committed before session/DNS-thread cleanup.
            payload=json.dumps(result,sort_keys=True,allow_nan=False).encode()
            output.write_bytes(gzip.compress(payload,mtime=0))
    return result


if __name__=='__main__':
    plan_path,output=map(Path,sys.argv[1:])
    if output.exists() or output.is_symlink():raise SystemExit('new_output_required')
    plan=json.loads(plan_path.read_text())
    if (plan['rpc_source']!=RPC or plan['addresses']!=[PROGRAM,PROGRAMDATA]
            or plan['max_requests']!=2 or plan['send_allowed'] is not False
            or time.time_ns()//1_000_000<=plan['registered_at_ms']):
        raise SystemExit('exact_published_program_read_plan_required')
    result=asyncio.run(capture(plan,output))
    print(json.dumps({k:result[k] for k in ('requests_used','elapsed_ms','stop_reason','code_observation')}))

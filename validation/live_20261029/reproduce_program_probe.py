"""Offline reproduction of the two original public-program reads, never a probe."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
os.environ['RUGGER_NO_DOTENV']='1'
def guard(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo','sqlite3.connect'):
        raise AssertionError('Program replay forbids network and databases')
sys.addaudithook(guard)
base=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('retained_program_probe',base/'program_probe.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
plan=json.loads((base/'PROGRAM_PROBE_PLAN.json').read_text())
assert hashlib.sha256((base/'program_probe.py').read_bytes()).hexdigest()==plan['script_sha256']
value=json.loads(gzip.decompress((base/'program-probe.json.gz').read_bytes()))
assert value['plan']==plan and value['requests_used']==2 and value['stop_reason'] is None
records=value['records'];assert [r['method'] for r in records]==plan['methods']
assert records[0]['response']==plan['expected_genesis_hash']==value['genesis_hash']
assert records[1]['params'][0]==plan['addresses']
assert module.inspect_accounts(records[1]['response'])==value['code_observation']
registration=json.loads((base/'PROGRAM_REGISTRATION_READBACK.json').read_text())
assert plan['registered_at_ms']<registration['verified_at_ms']<records[0]['requested_at_ms']
assert value['code_observation']['independently_approved'] is False
print(json.dumps(dict(original_requests_replayed=2,new_network_requests=0,
    ELF_sha256=value['code_observation']['ELF_sha256'],source_build_match=None,
    live_ready_to_arm=False),indent=2,sort_keys=True))

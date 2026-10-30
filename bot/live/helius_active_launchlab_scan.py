"""On-chain CURRENT ACTIVE LaunchLab/SOL pool discovery. No trade, no cohort GO.

One exact filtered getProgramAccounts with zero-byte dataSlice, only public
program-owned pool addresses; sorted by a source-slot-committed SHA permutation
before any pool prices are observed. This is a SURVIVOR sample (active only),
not the creation universe. Cannot prove a historical or P4 strategy edge.
"""
import hashlib
import json
import os
import sys

from bot.p3.certification import PROGRAM,_decode
from bot.p3.quotes import SOL_MINT
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS

OPTIONS=dict(encoding="base64",commitment="confirmed",
    withContext=True,dataSlice=dict(offset=0,length=0),
    limit=64,filters=[dict(dataSize=429),dict(memcmp=dict(offset=17,bytes="1")),
             dict(memcmp=dict(offset=237,bytes=SOL_MINT))])
MAX_UNIVERSE=50000
SAMPLE=12

def _h(data):
    return hashlib.sha256(data.encode()).hexdigest()

def discover_live_pool_account_page(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("wrong_mainnet_genesis")
    result=rpc("getProgramAccountsV2",[PROGRAM,OPTIONS])
    if type(result) is not dict or type(result.get("context")) is not dict:
        raise ValueError("program_accounts_context_missing")
    slot=result["context"].get("slot")
    page=result.get("value")
    if type(page) is not dict:
        raise ValueError("paged_program_accounts_envelope_required")
    rows=page.get("accounts")
    cursor=page.get("paginationKey")
    if (type(slot) is not int or slot<=0 or type(rows) is not list
            or len(rows)>64 or (cursor is not None and type(cursor) is not str)):
        raise ValueError("program_accounts_context_or_page_cap_invalid")
    addresses=[]
    for row in rows:
        if type(row) is not dict or type(row.get("account")) is not dict:
            raise ValueError("untrusted_program_account_shape")
        address=row.get("pubkey")
        if (type(address) is not str or len(_decode(address))!=32
                or row["account"].get("owner")!=PROGRAM
                or row["account"].get("executable") is not False
                or row["account"].get("data")!=["","base64"]):
            raise ValueError("untrusted_or_unfiltered_program_account")
        addresses.append(address)
    if len(set(addresses))!=len(addresses):
        raise ValueError("duplicate_program_account_scan")
    # A deterministic pseudorandom permutation, committed before any S1
    # pricing; not a sampling-theory certificate of representativeness.
    selected=sorted(addresses,
        key=lambda a:_h("rugger-active-scan-v1:"+str(slot)+":"+a))[:SAMPLE]
    return dict(schema="rugger-current-active-program-accounts-v1",
        status="ACTIVE_SOL_POOLS_PAGE_RECORDED",
        program=PROGRAM,scan_slot=slot,observed_active_SOL_pools_in_one_page=len(addresses),
        all_current_active_SOL_pools_enumerated=(cursor is None),
        further_pages_exist=(cursor is not None),
        cursor_not_retained_or_followed=True,
        observed_universe_sha256=_h("\n".join(sorted(addresses))),
        initial_pools_before_price=selected,
        predetermined_approach="fixed_SHA256_slot_permutation_first_12",
        source="filtered_getProgramAccountsV2_first_page_current_active_only",
        global_uniform_sample=False,
        is_creation_universe=False, includes_inactive_or_failed_launches=False,
        survivorship_bias_present=True,creator_identity_verified=False,
        future_price_used_in_selection=False,independent_qualified_creators=0,
        buy_sell_trades=0,strict_economic_cycles=0,
        master_edge_validated=False,financial_order_submitted=False,
        live_ready_to_arm=False,rpc_calls_used=getattr(rpc,"count",None))

def main():
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_missing")
        rpc=HeliusReadOnlyRpc.from_environment(
            max_calls=2,allow_active_pool_scan=True)
        result=discover_live_pool_account_page(rpc)
    except Exception as exc:
        code=str(exc)
        safe=code if type(exc) is ValueError and len(code)<100 and code.replace("_","").isalnum() else type(exc).__name__
        result=dict(status="REFUSED",reason=safe,
            last_rpc_method=(rpc.last_method if rpc else None),
            last_numeric_RPC_error_code=(rpc.last_rpc_error_code if rpc else None),
            financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="ACTIVE_SOL_POOLS_PAGE_RECORDED" else 2

if __name__=="__main__":
    sys.exit(main())

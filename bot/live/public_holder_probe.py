"""Public-only potential SELL simulation wallet discovery for one verified CPMM mint.

No wallet secret or signing; getTokenLargestAccounts and two same-or-later
account-bank reads. A discovered address belongs to an unrelated public owner,
and must NEVER be treated as consent to transact or as user-owned inventory.
"""
import json
import os
import ssl
import sys
import time
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError

from bot.p3.certification import _decode
from bot.p3 import launchlab
from bot.live.route import TOKEN_PROGRAM,SYSTEM_PROGRAM,associated_token_address
from bot.live.readonly_plan import MAINNET_GENESIS,PUBLIC_MAINNET_RPC
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc

MINT="56RC8gxeW2m8gDWZz3MXGjF9DikgP6DTo1PyBox5rray"
MIGRATION_SLOT=458932584

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("public_holder_redirect_refused")

class ReadOnlyHolderRpc:
    def __init__(self):
        self.count=0
        self.started=time.monotonic()
        self.opener=build_opener(ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    def __call__(self,method,params):
        if method not in ("getGenesisHash","getTokenLargestAccounts","getMultipleAccounts"):
            raise ValueError("holder_read_methods_only")
        if self.count>=4 or time.monotonic()-self.started>50:
            raise ValueError("public_holder_RPC_budget_exceeded")
        self.count+=1
        request=Request(PUBLIC_MAINNET_RPC,
            data=json.dumps(dict(jsonrpc="2.0",id=self.count,method=method,params=params),
            separators=(",",":")).encode("utf-8"),
            headers={"Content-Type":"application/json"},method="POST")
        with self.opener.open(request,timeout=8) as response:
            if response.status!=200 or response.geturl()!=PUBLIC_MAINNET_RPC:
                raise ValueError("holder_RPC_http_refusal")
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError("holder_RPC_response_exceeded")
        reply=json.loads(raw)
        if (type(reply) is not dict or reply.get("jsonrpc")!="2.0"
            or reply.get("id")!=self.count or "error" in reply
            or "result" not in reply):
            raise ValueError("holder_RPC_envelope_refused")
        return reply["result"]

def _bank(value,expected,min_slot):
    if type(value) is not dict:
        raise ValueError("holder_bank_required")
    slot=value.get("context",{}).get("slot")
    items=value.get("value")
    if (type(slot) is not int or slot<min_slot
            or type(items) is not list or len(items)!=expected):
        raise ValueError("holder_bank_slot_or_cardinality_invalid")
    return slot,items

def find_public_ata_holder(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("holder_wrong_mainnet")
    result=rpc("getTokenLargestAccounts",[MINT,dict(commitment="finalized")])
    slot,entries=_bank(result,len(result.get("value",[])),MIGRATION_SLOT+1)
    if not 1<=len(entries)<=20:
        raise ValueError("largest_holder_page_invalid")
    token_accounts=[]
    for entry in entries:
        address=entry.get("address") if type(entry) is dict else None
        if type(address) is not str:
            raise ValueError("holder_address_invalid")
        _decode(address)
        token_accounts.append(address)
    if len(set(token_accounts))!=len(token_accounts):
        raise ValueError("duplicate_top_token_accounts")
    second=rpc("getMultipleAccounts",[token_accounts,dict(
        encoding="base64",commitment="finalized",minContextSlot=slot)])
    bank_slot,accounts=_bank(second,len(token_accounts),slot)
    qualified=[]
    for account,address in zip(accounts,token_accounts,strict=True):
        try:
            state,_=launchlab._vault(account,"public_holder")
            owner=state["authority"]
            if (state["mint"]!=MINT or state["state"]!=1 or state["is_native"]
                    or state["delegate_present"] or state["close_authority_present"]
                    or state["amount_atomic"]<=0
                    or associated_token_address(owner,MINT)!=address):
                continue
            qualified.append((owner,address,state["amount_atomic"]))
        except (ValueError,TypeError,launchlab.SnapshotEvidenceError):
            continue
    if not qualified:
        return dict(status="NO_PUBLIC_SYSTEM_WALLET_ATA_IN_TOP_HOLDERS",
            bank_slot=bank_slot,financial_order_submitted=False,live_ready_to_arm=False)
    candidate=qualified[:12]
    owners=list(dict.fromkeys(pair[0] for pair in candidate))
    reply=rpc("getMultipleAccounts",[owners,dict(
        encoding="base64",commitment="finalized",minContextSlot=bank_slot)])
    wallet_slot,wallet_items=_bank(reply,len(owners),bank_slot)
    owner_info=dict(zip(owners,wallet_items,strict=True))
    for owner,ata,amount in candidate:
        item=owner_info[owner]
        if (type(item) is dict and item.get("owner")==SYSTEM_PROGRAM
                and item.get("executable") is False
                and item.get("data") in (["","base64"],("","base64"))
                and type(item.get("lamports")) is int and
                item["lamports"]>=5_000_000):
            return dict(schema="rugger-public-simulation-holder-v1",
                status="PUBLIC_CANDIDATE_WALLET_AND_ATA_IDENTIFIED",
                wallet=owner,ata=ata,public_token_amount_atomic=amount,
                public_wallet_lamports=item["lamports"],bank_slot=wallet_slot,
                rpc_calls_used=getattr(rpc,"count",None),
                user_ownership_verified=False,transaction_signature_available=False,
                actual_sell_simulated=False,financial_order_submitted=False,
                live_ready_to_arm=False,economic_edge_validated=False)
    return dict(status="NO_SPENDABLE_PUBLIC_SYSTEM_WALLET_IN_TOP_HOLDERS",
        bank_slot=wallet_slot,financial_order_submitted=False,live_ready_to_arm=False)

def main():
    try:
        rpc=(HeliusReadOnlyRpc.from_environment(max_calls=4)
             if "HELIUS_API_KEY" in os.environ else ReadOnlyHolderRpc())
        report=find_public_ata_holder(rpc)
    except Exception as exc:
        report=dict(status="REFUSED",error_type=type(exc).__name__,
                    http_status_code=exc.code if isinstance(exc,HTTPError) else None,
                    diagnostic_code=(str(exc) if str(exc).startswith("helius_")
                                     else "read_only_lookup_unavailable"),
                    financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="PUBLIC_CANDIDATE_WALLET_AND_ATA_IDENTIFIED" else 2

if __name__=="__main__":
    sys.exit(main())

"""Second-provider cryptographic check of the first real SOL-quoted LaunchLab creator.

A single bounded proof read from PUBLICNODE, independent of the original
Solana public RPC capture, not a quote or trade. No wallet, key or order.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from bot.analyser.artifacts import atomic_write_json
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.compiled_launchlab import compiled_launchlab_creations

SCHEMA="rugger-second-provider-native-sol-signed-creation-v1"
RPC="https://solana-rpc.publicnode.com"
MAX_RESPONSE=1_750_000
SIGNATURE="5qqLenzDgNbLkuN482pPEzoZLyygQYsdLzdMZ2cuKqbpXyXRbXZCASRGw2gWNK91cpBZgorjThhJAhiCtwJk6hUk"
SLOT=464432476
MESSAGE_SHA256="69a94c670266c768c86cc0cb01fd6673079cf26153b0eb3ff0d62fff3bf1680b"
CREATOR="HxM1EeyZ9z71m8mu5x9bsUdtTP1f9qtT7mo9D5tB3xwM"
MINT="ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
POOL="EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
SAFE_CODES=frozenset((
    "second_provider_genesis_invalid",
    "second_provider_reply_invalid",
    "second_provider_receipt_unavailable",
    "second_provider_signature_slot_failed",
    "second_provider_compiled_message_not_equal",
    "second_provider_signed_creation_identity_mismatch",
    "second_provider_source_not_pinned",
    "second_provider_response_too_large",
    "second_provider_file_must_be_new",
))


def _rpc_once(method,params,*,opener=urlopen):
    if (method=="getGenesisHash" and params==[]):
        pass
    elif (method=="getTransaction" and params==[SIGNATURE,dict(
            encoding="json",commitment="finalized",maxSupportedTransactionVersion=0)]):
        pass
    else:
        raise ValueError("second_provider_source_not_pinned")
    body=json.dumps(dict(jsonrpc="2.0",id=1,method=method,params=params),
            separators=(",",":")).encode()
    req=Request(RPC,data=body,method="POST",headers={
        "Accept":"application/json","Content-Type":"application/json",
        "User-Agent":"RuggerSecondProviderReadOnlyProof/1.0"})
    with opener(req,timeout=12) as response:
        if response.status!=200:
            raise ValueError("second_provider_reply_invalid")
        raw=response.read(MAX_RESPONSE+1)
    if len(raw)>MAX_RESPONSE:
        raise ValueError("second_provider_response_too_large")
    try:
        message=json.loads(raw)
    except (UnicodeDecodeError,ValueError):
        raise ValueError("second_provider_reply_invalid") from None
    if (type(message) is not dict or message.get("jsonrpc")!="2.0"
            or message.get("id")!=1 or "error" in message
            or "result" not in message):
        raise ValueError("second_provider_reply_invalid")
    return message["result"]


def verify_second_provider(*,rpc=_rpc_once):
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("second_provider_genesis_invalid")
    raw=rpc("getTransaction",[SIGNATURE,dict(
        encoding="json",commitment="finalized",maxSupportedTransactionVersion=0)])
    if (type(raw) is not dict or raw.get("slot")!=SLOT
            or type(raw.get("meta")) is not dict or raw["meta"].get("err") is not None
            or type(raw.get("transaction")) is not dict
            or type(raw["transaction"].get("signatures")) is not list
            or not raw["transaction"]["signatures"]
            or raw["transaction"]["signatures"][0]!=SIGNATURE):
        raise ValueError("second_provider_signature_slot_failed")
    proof=verify_compiled_rpc_signatures(raw)
    if (proof.get("cryptographic_signatures_verified") is not True
            or proof.get("exact_message_sha256")!=MESSAGE_SHA256):
        raise ValueError("second_provider_compiled_message_not_equal")
    outer=dict(raw,meta=dict(raw["meta"],innerInstructions=[]))
    verified=compiled_launchlab_creations(outer)
    message=raw["transaction"].get("message")
    if (type(message) is not dict or type(message.get("header")) is not dict
            or type(message.get("accountKeys")) is not list
            or type(message["header"].get("numRequiredSignatures")) is not int):
        raise ValueError("second_provider_signed_creation_identity_mismatch")
    signers=message["accountKeys"][:message["header"]["numRequiredSignatures"]]
    if not any(type(item) is dict
               and item.get("creator")==CREATOR and item.get("payer")==CREATOR
               and item.get("mint")==MINT and item.get("pool_state")==POOL
               and CREATOR in signers for item in verified):
        raise ValueError("second_provider_signed_creation_identity_mismatch")
    return dict(schema=SCHEMA,
        status="PUBLICNODE_REVERIFIED_SAME_NATIVE_SOL_CREATION",
        source_archive_run_id=41415157117,
        independent_provider="PublicNode",
        verified_slot=SLOT,
        signature=SIGNATURE,mint=MINT,pool=POOL,creator=CREATOR,
        verified_exact_message_sha256=MESSAGE_SHA256,
        compiled_message_ed25519_verified=True,
        original_sol_public_rpc_receipt_hash_matched=True,
        independent_full_chain_consensus_established=False,
        current_seven_account_bank_verified=False,
        executable_entry_exit_quotes_verified=False,
        genuine_Master_PAPER_buy_sell_verified=False,
        master_net_pnl_lamports=None,
        financial_order_submitted=False,live_trading_enabled=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--output-file",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print('SECOND_PROVIDER_REFUSED:EXPLICIT_NETWORK_OPT_IN_REQUIRED')
        return 2
    if args.output_file.exists() or args.output_file.is_symlink():
        print('SECOND_PROVIDER_REFUSED:NEW_OUTPUT_PATH_REQUIRED')
        return 2
    try:
        result=verify_second_provider()
        atomic_write_json(args.output_file,result,sort_keys=True,allow_nan=False)
    except Exception as err:
        code=str(err) if type(err) is ValueError and str(err) in SAFE_CODES else None
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
            safe_error_class=type(err).__name__,safe_reason_code=code,
            financial_order_submitted=False),sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

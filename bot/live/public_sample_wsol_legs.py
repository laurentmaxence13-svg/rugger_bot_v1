"""Verify one sampled WSOL-quoted LaunchLab BUY and one SELL on mainnet.

The two legs have DIFFERENT public signers, distinct signatures and are
NOT a same-payer BUY→SELL cycle; they cannot demonstrate PnL. Free Parquet
sample quote mint is confirmed against the signed compiled account set.
No signing, no send, no wallet access, no permission to trade.
"""
import json
import os
import sys
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.p3.certification import PROGRAM
from bot.p3.quotes import SOL_MINT

LEGS=(
    dict(kind="public_WSOL_BUY",
        signature="4UJtByMypEBjmusqMJEb4q7iZqbvCuVKNJ3gBrdQ7PJ7KQt4bM8emehhrKRBP55mvyABaMwKRKxXwr1wKVmCuwmc",
        slot=445316399,pool="22HLvCy2Ejp1RMuLFZ4N2kXB9peAt146yuAw1ixJh9V3",
        payer="6dHHC2tKmFA7d5huxKH6KAkxE79kzMNhaLfrQnhra4V"),
    dict(kind="public_WSOL_SELL",
        signature="2ZEaVXDd7A6DYi2XHsoe6Ve8tsXcZivHNBLbnnQNskXstbqJUYZbG37GzZAZ8HPUQ9CRuB1JjCWmv1eb58mvtpkm",
        slot=445315928,pool="22HLvCy2Ejp1RMuLFZ4N2kXB9peAt146yuAw1ixJh9V3",
        payer="ARu4n5mFdZogZAravu7CcizaojWnS6oqka37gdLT5SZn"),
)
OPTS=dict(encoding="json",commitment="finalized",maxSupportedTransactionVersion=1)

def verify_two_wsol_legs(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("exact_mainnet_required")
    if LEGS[0]["payer"]==LEGS[1]["payer"]:
        raise ValueError("test_is_not_intended_as_causal_cycle")
    verified=[]
    for leg in LEGS:
        tx=rpc("getTransaction",[leg["signature"],OPTS])
        if (type(tx) is not dict or tx.get("slot")!=leg["slot"]
                or type(tx.get("meta")) is not dict
                or tx["meta"].get("err") is not None
                or tx.get("transaction",{}).get("signatures",[None])[0]!=leg["signature"]):
            raise ValueError("WSOL_leg_transaction_or_slot_invalid")
        proof=verify_compiled_rpc_signatures(tx)
        keys=normalized_compiled_transaction(tx)["transaction"]["message"]["accountKeys"]
        found={x["pubkey"] for x in keys}
        if not ({leg["pool"],leg["payer"],SOL_MINT,PROGRAM}.issubset(found)
                and any(k["pubkey"]==leg["payer"] and k["signer"] for k in keys)):
            raise ValueError("WSOL_quoted_leg_required_keys_or_payer_signer_missing")
        if proof.get("cryptographic_signatures_verified") is not True:
            raise ValueError("WSOL_quoted_leg_Ed25519_unverified")
        verified.append(dict(kind=leg["kind"],signature=leg["signature"],
            slot=leg["slot"],pool=leg["pool"],quote_mint=SOL_MINT,
            signer=leg["payer"],exact_message_sha256=proof["exact_message_sha256"],
            signed_transaction_verified=True))
    return dict(schema="rugger-free-sample-Wsol-trade-legs-v1",
        status="TWO_DISCONNECTED_WSOL_LEGS_CRYPTOGRAPHICALLY_VERIFIED",
        verified_legs=verified,
        same_pool_but_different_payer=True,
        sell_slot_precedes_sample_buy_slot=True,
        same_payer_causal_buy_sell_cycle_proven=False,
        amounts_and_event_data_independently_reconciled=False,
        economic_edge_validated=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        rpc_calls_used=getattr(rpc,"count",None))

def main():
    try:
        report=verify_two_wsol_legs(
            HeliusReadOnlyRpc.from_environment(max_calls=3))
    except Exception as exc:
        code=str(exc)
        safe=(code if type(exc) is ValueError and len(code)<100
              and code.replace("_","").isalnum()
              and not code.startswith("helius_api_key")
              else type(exc).__name__)
        report=dict(status="REFUSED",reason=safe,
                    financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="TWO_DISCONNECTED_WSOL_LEGS_CRYPTOGRAPHICALLY_VERIFIED" else 2

if __name__=="__main__":
    sys.exit(main())

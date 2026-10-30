"""Cross-check four publicly sampled BUY/SELL transactions against mainnet.

Four exact historical signatures, pool accounts, submitters and slots were
extracted from the user-supplied free Raydium Launchpad Parquet ZIP after
verifying the ZIP manifest's 23 SHA256 checksums. Solana RPC verification
checks the raw compiled Ed25519 message and both role keys; it does NOT
independently decode/reconcile the Parquet TradeEvent amounts, demonstrate
net profits, cover other missing trades, authorize a wallet or place orders.

The sample covers only a short period and is selected AFTER known results;
it is *not* a prospective strategy/holdout evaluation.
"""
import json
import os
import sys
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.p3.certification import PROGRAM

SAMPLES=(
    dict(
        label="exact_token_amount_pair",
        pool="4B8fFhma9rW26qisMsb7bgwPUT1wZtV4hRt7ug8MaRbc",
        payer="REDBUtdAjot2V6abs2pojT9BiRUdC1NuUpi8QSfrMVt",
        buy_sig="qgYuaN1kHVcv43ZcGvnyJndrZCwzrCVjFQPVhEBJBeKmSWCj9e1x7CatrVZrctikBVAx84zZArx5eU4hcbn3mMk",
        buy_slot=445316414,
        sell_sig="2QUUw3Z68pXZWp52ZtYrSULhnB1gopbPNt5DvEzPG342gqhtURwJipKiKKbjYfr27QKxzGbNLDNZikPLHEhXoWap",
        sell_slot=445316611,
        sampled_buy_sol_lamports=96987772,
        sampled_buy_token_atomic=33207397256443,
        sampled_sell_token_atomic=33207397256443,
        sampled_sell_sol_lamports=109827011),
    dict(
        label="partial_token_amount_pair",
        pool="2LGqW7dj2rQtTRwLzUBKRNgxQ5m9eD8VtJJoKToPe6zN",
        payer="4MunitMby28PuCDKR996X6r8gVMSoZ2ew57E515jzwPp",
        buy_sig="4Yp2YbyVv61vzHGyeRK4pUrFPXDRdiTTPWbezJZBf4pEdguCMXH9SbQfAmvNq1Qybfi6NcDXwX4EudaGq2fHCwtn",
        buy_slot=445316568,
        sell_sig="4KHch5sx3KuL9tLsmfu8BQe6iB6uRvxEBuLCXdtDexiqVYBDWHPimeNNTU5Jzb3S7iifJdef69wCs4dYAMHtXRZ5",
        sell_slot=445316589,
        sampled_buy_sol_lamports=80474356,
        sampled_buy_token_atomic=25873956133366,
        sampled_sell_token_atomic=25359064406311,
        sampled_sell_sol_lamports=84059924),
)
OPTIONS=dict(encoding="json",commitment="finalized",
             maxSupportedTransactionVersion=1)


def verify_public_sample_receipts(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("exact_mainnet_genesis_required")
    results=[]
    for sample in SAMPLES:
        if not sample["buy_slot"]<sample["sell_slot"]:
            raise ValueError("source_sample_not_chronologically_ordered")
        for side in ("buy","sell"):
            sig=sample[side+"_sig"]
            slot=sample[side+"_slot"]
            tx=rpc("getTransaction",[sig,OPTIONS])
            if (type(tx) is not dict or tx.get("slot")!=slot
                    or type(tx.get("meta")) is not dict
                    or tx["meta"].get("err") is not None
                    or tx.get("transaction",{}).get("signatures",[None])[0]!=sig):
                raise ValueError("sample_signature_slot_or_success_mismatch")
            verified=verify_compiled_rpc_signatures(tx)
            normalized=normalized_compiled_transaction(tx)
            keys=normalized["transaction"]["message"]["accountKeys"]
            if not ({sample["pool"],sample["payer"],PROGRAM}
                    .issubset({r["pubkey"] for r in keys})):
                raise ValueError("public_sample_pool_payer_or_program_missing")
            if not any(k["pubkey"]==sample["payer"] and k["signer"] for k in keys):
                raise ValueError("sample_claimed_payer_not_transaction_signer")
            if verified["cryptographic_signatures_verified"] is not True:
                raise ValueError("sample_ed25519_not_verified")
            results.append(dict(label=sample["label"],side=side,
                signature=sig,slot=slot,
                exact_message_sha256=verified["exact_message_sha256"],
                account_pool_present=True,claimed_payer_signer=True,
                source_provider_claim_finalized=True,
                compiled_message_ed25519_verified=True))
    return dict(schema="rugger-four-sampled-buy-sell-receipts-v1",
        status="FOUR_SAMPLED_PUBLIC_SIGNED_TRANSACTIONS_VERIFIED",
        verified_receipts=results,
        claimed_historical_pair_count=2,
        exact_token_amount_pair_count=1,
        sampled_data_status="from_nonrepresentative_free_Parquet_subset",
        sampled_TradeEvent_amounts_independently_decoded_from_logs=False,
        sampled_buy_and_sell_token_transfers_independently_reconciled=False,
        net_profitability_or_wallet_full_history_verified=False,
        master_policy_decisions_present_in_dataset=False,
        independent_holdout_creator_count=0,
        verified_strategy_cycles=0,
        live_ready_to_arm=False,financial_order_submitted=False,
        rpc_calls_used=getattr(rpc,"count",None))


def main():
    rpc=None
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_secret_not_configured")
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=5)
        report=verify_public_sample_receipts(rpc)
    except Exception as error:
        code=str(error)
        safe=code if (type(error) is ValueError and len(code)<100
                       and code.replace("_","").isalnum()
                       and not code.startswith("helius_api_key")) else type(error).__name__
        report=dict(status="REFUSED",safe_reason=safe,
            last_rpc_method=rpc.last_method if rpc is not None else None,
            numeric_rpc_error_code=rpc.last_rpc_error_code if rpc is not None else None,
            live_ready_to_arm=False,financial_order_submitted=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="FOUR_SAMPLED_PUBLIC_SIGNED_TRANSACTIONS_VERIFIED" else 2


if __name__=="__main__":
    sys.exit(main())

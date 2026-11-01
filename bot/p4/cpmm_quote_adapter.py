"""Conservative exact-in Raydium CPMM SELL quote for source-verified banks.

Uses explicit on-chain pool/account facts. The CPMM program id, mint order,
fee-on direction and accrued protocol/fund/creator fees are retained.
Token-2022 transfer fees must come from a verified mint state; unknown
extensions prevent a quote. This quote is an observed-bank model, not an
independently executable provider response or actual paper fill.

Reference: raydium-io/raydium-docs-v1 products/cpmm/fees.mdx and SDK V2
CurveCalculator.swapBaseInput for the live program configuration.
"""
from bot.p3.quotes import SOL_MINT
from bot.p4.live_like_paper_ledger import source_quote,migration_proof

CPMM_MAINNET="CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
RATE_DENOMINATOR=1_000_000


def u64(v,name,*,positive=False):
    if type(v) is not int or not (1 if positive else 0)<=v<2**64:
        raise ValueError("invalid_cpmm_"+name)
    return v


def _ceil_fee(amount,ppm):
    return (amount*ppm+RATE_DENOMINATOR-1)//RATE_DENOMINATOR


def cpmm_sell_source_quote(*,bank,mint,curve_pool,token_amount_atomic,
                           migration,network_and_priority_fee_lamports=None,
                           account_creation_fee_lamports=None,
                           failed_attempt_fee_lamports=None):
    if type(bank) is not dict or type(migration) is not dict:
        raise ValueError("verified_cpmm_bank_and_migration_required")
    required={"pool","owner_program","token0_mint","token1_mint",
              "token_mint","sol_mint","vault_token_atomic","vault_sol_lamports",
              "accrued_protocol_token","accrued_fund_token","accrued_creator_token",
              "accrued_protocol_sol","accrued_fund_sol","accrued_creator_sol",
              "trade_fee_rate_ppm","creator_fee_rate_ppm","creator_fee_on",
              "token_transfer_fee_input_atomic","sol_transfer_fee_output_lamports",
              "token2022_extensions_verified","source_bank_owner_verified",
              "source_slot","available_at_ms","source_sha256"}
    if set(bank)!=required:
        raise ValueError("exact_trusted_cpmm_source_bank_required")
    if (bank["owner_program"]!=CPMM_MAINNET
            or bank["token_mint"]!=mint or bank["sol_mint"]!=SOL_MINT
            or {bank["token0_mint"],bank["token1_mint"]}!={mint,SOL_MINT}
            or bank["token2022_extensions_verified"] is not True
            or bank["source_bank_owner_verified"] is not True):
        raise ValueError("wrong_cpmm_program_or_token_mint_or_unverified_extensions")
    slot=u64(bank["source_slot"],"source_slot",positive=True)
    at=u64(bank["available_at_ms"],"available_at_ms",positive=True)
    if (type(bank["source_sha256"]) is not str
            or len(bank["source_sha256"])!=64
            or any(c not in "0123456789abcdef" for c in bank["source_sha256"])):
        raise ValueError("cpmm_source_bank_digest_required")
    migration_proof(migration,mint=mint,from_pool=curve_pool,
                    to_pool=bank["pool"],slot=slot)
    amount=u64(token_amount_atomic,"token_lot",positive=True)
    if any(x is None for x in (network_and_priority_fee_lamports,
          account_creation_fee_lamports,failed_attempt_fee_lamports)):
        raise ValueError("unknown_cpmm_network_priority_account_or_failure_cost")
    for label,v in [("network_fee",network_and_priority_fee_lamports),
                    ("account_fee",account_creation_fee_lamports),
                    ("failure_fee",failed_attempt_fee_lamports)]:
        u64(v,label)
    trade=u64(bank["trade_fee_rate_ppm"],"trade_fee")
    creator=u64(bank["creator_fee_rate_ppm"],"creator_fee")
    if trade+creator>=RATE_DENOMINATOR:
        raise ValueError("cpmm_total_fee_over_denominator")
    fee_on=bank["creator_fee_on"]
    if fee_on not in ("BothToken","OnlyToken0","OnlyToken1"):
        raise ValueError("unsupported_cpmm_creator_fee_on")
    creator_on_input=(fee_on=="BothToken" or
        fee_on=="OnlyToken0" and bank["token0_mint"]==mint or
        fee_on=="OnlyToken1" and bank["token1_mint"]==mint)
    token_reserve=u64(bank["vault_token_atomic"],"vault_token",positive=True)
    sol_reserve=u64(bank["vault_sol_lamports"],"vault_sol",positive=True)
    token_accrued=sum(u64(bank[k],k) for k in
        ("accrued_protocol_token","accrued_fund_token","accrued_creator_token"))
    sol_accrued=sum(u64(bank[k],k) for k in
        ("accrued_protocol_sol","accrued_fund_sol","accrued_creator_sol"))
    if token_accrued>=token_reserve or sol_accrued>=sol_reserve:
        raise ValueError("accrued_cpmm_fees_exceed_vault")
    reserve_in=token_reserve-token_accrued
    reserve_out=sol_reserve-sol_accrued
    transfer_in=u64(bank["token_transfer_fee_input_atomic"],"input_transfer")
    transfer_out=u64(bank["sol_transfer_fee_output_lamports"],"output_transfer")
    if transfer_in>=amount:
        raise ValueError("input_token2022_transfer_consumes_lot")
    post_transfer=amount-transfer_in
    fee_trade=_ceil_fee(post_transfer,trade)
    fee_creator_in=_ceil_fee(post_transfer,creator) if creator_on_input else 0
    net_input=post_transfer-fee_trade-fee_creator_in
    if net_input<=0:
        raise ValueError("cpmm_trade_input_consumed_by_fees")
    gross=net_input*reserve_out//(reserve_in+net_input)
    fee_creator_out=_ceil_fee(gross,creator) if not creator_on_input else 0
    output=gross-fee_creator_out-transfer_out
    if output<=0 or gross>=reserve_out:
        raise ValueError("cpmm_liquidity_or_fee_refused")
    q=dict(
        id=str(bank["source_sha256"])+":CPMM_SELL:"+str(amount),
        mint=mint,pool=bank["pool"],venue="RAYDIUM_CPMM",side="SELL",
        input_atomic=amount,output_atomic=output,source_slot=slot,
        available_at_ms=at,source_produced_at_ms=at,
        source_observation_sha256=bank["source_sha256"],
        provenance="OBSERVED_CHAIN_MODEL",
        network_and_priority_fee_lamports=network_and_priority_fee_lamports,
        account_creation_fee_lamports=account_creation_fee_lamports,
        failed_attempt_fee_lamports=failed_attempt_fee_lamports,
        migration_proof=migration)
    source_quote(q)
    return dict(
        paper_quote=q,fee_details=dict(
            protocol_fund_creator_accruals_excluded_from_reserves=True,
            net_token_reserve_atomic=str(reserve_in),
            net_sol_reserve_lamports=str(reserve_out),
            token2022_input_transfer_fee_atomic=str(transfer_in),
            swap_trade_fee_token_atomic=str(fee_trade),
            creator_fee_token_atomic=str(fee_creator_in),
            creator_fee_sol_lamports=str(fee_creator_out),
            token2022_output_transfer_lamports=str(transfer_out),
            provider_quote_not_observed=True),
        quote_is_conditional_bank_model=True,actual_transaction_executed=False,
        performance_verified=False)

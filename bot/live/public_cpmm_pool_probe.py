"""Read-only finalized on-chain bank observation for two proven SOL CPMM pools.

Pinned addresses are from the real signed public migration receipts and are
cross-checked against CPMM owner/discriminator/vault PDA/token balances.
No wallet, user ATA, signing, simulation or financial order occurs.
This does NOT certify an executable sell route or economic profitability.
"""
import json
import sys
from bot.p3.certification import _decode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.p3 import launchlab
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.route import TOKEN_PROGRAM
from bot.live.cpmm_exit import (
    _account, _pool, _config, POOL_ACCOUNT_SIZE,
    POOL_DISCRIMINATOR, CONFIG_ACCOUNT_SIZE, CONFIG_DISCRIMINATOR)
from bot.live.public_program_observer import PublicReadOnlyRpc, _bank
from bot.live.readonly_plan import MAINNET_GENESIS

# Real Ed25519-verified mainnet migration receipts, source provider 2026-10-30.
MIGRATED_POOLS = (
    ("GkfmzPpzPiYM8kxXCfo88z8t9vqh1NECbFLG814SSLcx",
     "7vtE5SpwBWhXgBrW7AjHikBatSvbYLdvD4qHuRMQkids",458935475),
    ("DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck",
     "56RC8gxeW2m8gDWZz3MXGjF9DikgP6DTo1PyBox5rray",458932584),
)

def probe_cpmm_pools(rpc):
    if not callable(rpc):
        raise ValueError("explicit_readonly_rpc_required")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("wrong_mainnet_genesis")
    pool_ids=[p[0] for p in MIGRATED_POOLS]
    min_slot=max(p[2] for p in MIGRATED_POOLS)+1
    opts=dict(encoding="base64",commitment="finalized",minContextSlot=min_slot)
    first=rpc("getMultipleAccounts",[pool_ids,opts])
    first_slot,values=_bank(first,2,min_slot)
    pools=[]
    for (addr,mint,slot),item in zip(MIGRATED_POOLS,values,strict=True):
        raw=_account(item,name="pool",size=POOL_ACCOUNT_SIZE,
                     discriminator=POOL_DISCRIMINATOR)
        pool=_pool(raw)
        if ({pool["token_0_mint"],pool["token_1_mint"]}!={mint,SOL_MINT}
                or pool["token_0_program"]!=TOKEN_PROGRAM
                or pool["token_1_program"]!=TOKEN_PROGRAM):
            raise ValueError("migrated_pool_is_not_classic_SPL_SOL_pair")
        pools.append(pool)
    others=[]
    for pool in pools:
        others += [pool["amm_config"],pool["token_0_vault"],pool["token_1_vault"]]
    # Deduplicate while preserving account-bank identity; bounded to 8.
    addresses=list(dict.fromkeys(pool_ids+others))
    if len(addresses)>8:
        raise ValueError("unexpected_pool_graph_cardinality")
    opts=dict(encoding="base64",commitment="finalized",minContextSlot=first_slot)
    second=rpc("getMultipleAccounts",[addresses,opts])
    bank_slot,items=_bank(second,len(addresses),first_slot)
    accounts=dict(zip(addresses,items,strict=True))
    results=[]
    for (pool_id,mint,migration_slot),prior in zip(MIGRATED_POOLS,pools,strict=True):
        pool=_pool(_account(accounts[pool_id],name="pool",
                         size=POOL_ACCOUNT_SIZE,discriminator=POOL_DISCRIMINATOR))
        for k in ("amm_config","token_0_mint","token_1_mint",
                  "token_0_vault","token_1_vault","observation_key","lp_mint"):
            if pool[k]!=prior[k]:
                raise ValueError("cpmm_pool_identity_changed_between_banks")
        if pool["status"] & 4 or pool["lp_supply"]==0:
            raise ValueError("cpmm_pool_swaps_disabled_or_no_LP")
        cfg=_config(_account(accounts[pool["amm_config"]],name="config",
                     size=CONFIG_ACCOUNT_SIZE,discriminator=CONFIG_DISCRIMINATOR))
        config_expected=find_program_address((b"amm_config",cfg["index"].to_bytes(2,"big")),
                            program_id=CPMM_PROGRAM)[0]
        if config_expected!=pool["amm_config"]:
            raise ValueError("cpmm_fee_config_PDA_mismatch")
        mint_index=0 if pool["token_0_mint"]==mint else 1
        reserves=[]
        for i in (0,1):
            vault=pool["token_"+str(i)+"_vault"]
            expected=find_program_address((b"pool_vault",_decode(pool_id),
                _decode(pool["token_"+str(i)+"_mint"])),program_id=CPMM_PROGRAM)[0]
            if vault!=expected:
                raise ValueError("cpmm_vault_PDA_mismatch")
            token,_=launchlab._vault(accounts[vault],"cpmm_vault_"+str(i))
            if token["mint"]!=pool["token_"+str(i)+"_mint"] or token["state"]!=1:
                raise ValueError("cpmm_vault_mint_or_state_invalid")
            fees=(pool["protocol_fees_token_"+str(i)]+
                  pool["fund_fees_token_"+str(i)]+
                  pool["creator_fees_token_"+str(i)])
            net=token["amount_atomic"]-fees
            if net<=0:
                raise ValueError("cpmm_empty_effective_vault")
            reserves.append(net)
        results.append(dict(pool=pool_id,mint=mint,migration_slot=migration_slot,
                            token_reserve_atomic=reserves[mint_index],
                            wsol_reserve_lamports=reserves[1-mint_index],
                            trade_fee_rate_ppm=cfg["trade_fee_rate"],
                            pool_status=pool["status"],lp_supply_atomic=pool["lp_supply"]))
    return dict(schema="rugger-readonly-real-cpmm-bank-v1",
        status="TWO_FINALIZED_CPMM_POOL_BANKS_OBSERVED",
        bank_slot=bank_slot,rpc_calls_used=getattr(rpc,"count",None),
        pools=results,signature_and_migration_verified_in_this_probe=False,
        wallet_position_verified=False,actual_sell_simulated=False,
        rpc_consensus_cryptographically_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        economic_edge_validated=False)

def main():
    try:
        report=probe_cpmm_pools(PublicReadOnlyRpc())
    except Exception as exc:
        report=dict(status="REFUSED",error_type=type(exc).__name__,
                    financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="TWO_FINALIZED_CPMM_POOL_BANKS_OBSERVED" else 2

if __name__=="__main__":
    sys.exit(main())

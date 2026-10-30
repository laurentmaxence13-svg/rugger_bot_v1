"""Preregistered two-bank CPMM market markout; NO orders or wallet access.

One exact migrated classic SPL/SOL pool is selected BEFORE observing S2.
S1 reserves establish three fixed, separately sized, hypothetical buys. S2
reserves price sale of each exact S1 amount, without assuming our S1 hypothetical
buy changed actual S2 liquidity. Such markouts are NOT real BUY->SELL fills,
causal strategy profits, independent trials or Master-vs-baseline evidence.
"""
import hashlib
import json
import os
import sys
import time

from bot.p3.certification import _decode, find_program_address
from bot.p3.quotes import SOL_MINT
from bot.p3 import launchlab
from bot.live.cpmm_exit import (
    _account, _pool, _config, _quote_exact_input,
    POOL_ACCOUNT_SIZE, CONFIG_ACCOUNT_SIZE,
    POOL_DISCRIMINATOR, CONFIG_DISCRIMINATOR)
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.route import TOKEN_PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.public_cpmm_pool_probe import MIGRATED_POOLS
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc

POOL="DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck"
MINT="56RC8gxeW2m8gDWZz3MXGjF9DikgP6DTo1PyBox5rray"
ENTRY_LAMPORTS=(10_000_000,50_000_000,100_000_000)
HOLD_SECONDS=12
COST_ASSUMPTION_LAMPORTS=10_000
assert (POOL,MINT,458932584) in MIGRATED_POOLS


def _jsonhash(doc):
    return hashlib.sha256(json.dumps(
        doc,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _bank(reply,count,floor):
    if type(reply) is not dict or type(reply.get("context")) is not dict:
        raise ValueError("missing_cpmm_bank_context")
    slot=reply["context"].get("slot")
    items=reply.get("value")
    if type(slot) is not int or slot<floor or type(items) is not list or len(items)!=count:
        raise ValueError("cpmm_slot_or_cardinality_mismatch")
    return slot,items


def _static_graph(pool_id,raw_pool):
    pool=_pool(_account(raw_pool,name="pool",size=POOL_ACCOUNT_SIZE,
                discriminator=POOL_DISCRIMINATOR))
    if ({pool["token_0_mint"],pool["token_1_mint"]}!={MINT,SOL_MINT}
            or pool["token_0_program"]!=TOKEN_PROGRAM
            or pool["token_1_program"]!=TOKEN_PROGRAM
            or pool["status"]!=0 or pool["lp_supply"]<=0):
        raise ValueError("cpmm_pair_program_or_status_unqualified")
    expected_auth,bump=find_program_address(
        (b"vault_and_lp_mint_auth_seed",),program_id=CPMM_PROGRAM)
    if pool["auth_bump"]!=bump:
        raise ValueError("cpmm_authority_bump_invalid")
    for i in (0,1):
        mint=pool["token_"+str(i)+"_mint"]
        expected=find_program_address((b"pool_vault",_decode(pool_id),_decode(mint)),
                                     program_id=CPMM_PROGRAM)[0]
        if pool["token_"+str(i)+"_vault"]!=expected:
            raise ValueError("cpmm_noncanonical_vault")
    lp=find_program_address((b"pool_lp_mint",_decode(pool_id)),program_id=CPMM_PROGRAM)[0]
    observation=find_program_address((b"observation",_decode(pool_id)),program_id=CPMM_PROGRAM)[0]
    if pool["lp_mint"]!=lp or pool["observation_key"]!=observation:
        raise ValueError("cpmm_lp_or_observation_identity_mismatch")
    return pool,expected_auth


def decode_bank(accounts):
    if type(accounts) is not dict or POOL not in accounts:
        raise ValueError("cpmm_exact_account_mapping_required")
    pool,authority=_static_graph(POOL,accounts[POOL])
    if set(accounts)!={POOL,pool["amm_config"],pool["token_0_vault"],
                        pool["token_1_vault"]}:
        raise ValueError("cpmm_four_exact_accounts_required")
    cfg=_config(_account(accounts[pool["amm_config"]],name="config",
               size=CONFIG_ACCOUNT_SIZE,discriminator=CONFIG_DISCRIMINATOR))
    expected,bump=find_program_address(
        (b"amm_config",cfg["index"].to_bytes(2,"big")),program_id=CPMM_PROGRAM)
    if pool["amm_config"]!=expected or cfg["bump"]!=bump or cfg["disabled"]!=0:
        raise ValueError("cpmm_config_not_active_or_canonical")
    if (cfg["trade_fee_rate"]>=1_000_000
            or cfg["trade_fee_rate"]+cfg["creator_fee_rate"]>=1_000_000
            or cfg["protocol_fee_rate"]+cfg["fund_fee_rate"]>1_000_000
            or cfg["creator_fee_share_rate"]>1_000_000):
        raise ValueError("cpmm_fee_config_out_of_range")
    amounts=[]
    for i in (0,1):
        token,_=launchlab._vault(accounts[pool["token_"+str(i)+"_vault"]],
                                 "cpmm_prospective_vault_"+str(i))
        expected_mint=pool["token_"+str(i)+"_mint"]
        if (token["mint"]!=expected_mint or token["authority"]!=authority
                or token["state"]!=1 or token["delegate_present"]
                or token["close_authority_present"]
                or token["is_native"]!=(expected_mint==SOL_MINT)):
            raise ValueError("cpmm_vault_authority_or_token_state_invalid")
        accrued=sum(pool[key+"_token_"+str(i)] for key in
                    ("protocol_fees","fund_fees","creator_fees"))
        if type(accrued) is not int or accrued>=token["amount_atomic"]:
            raise ValueError("cpmm_effective_vault_empty")
        amounts.append(token["amount_atomic"]-accrued)
    mint_index=0 if pool["token_0_mint"]==MINT else 1
    return dict(pool=POOL,mint=MINT,base_reserve_atomic=amounts[mint_index],
        sol_reserve_lamports=amounts[1-mint_index],
        mint_index=mint_index,config=cfg,
        creator_enabled=bool(pool["enable_creator_fee"]),
        creator_fee_on=pool["creator_fee_on"],
        stable_pool_identity={k:pool[k] for k in (
            "amm_config","token_0_mint","token_1_mint","token_0_vault",
            "token_1_vault","lp_mint","observation_key","auth_bump")},
        conditional_only=True)


def _quote(bank,side,amount):
    if side not in ("BUY","SELL") or type(amount) is not int or amount<=0:
        raise ValueError("conditional_quote_side_or_amount_invalid")
    entry_token_index=(1-bank["mint_index"]) if side=="BUY" else bank["mint_index"]
    creator_on_input=bank["creator_enabled"] and (
        bank["creator_fee_on"]==0 or
        bank["creator_fee_on"]==(1 if entry_token_index==0 else 2))
    config=bank["config"]
    if side=="BUY":
        input_reserve,output_reserve=bank["sol_reserve_lamports"],bank["base_reserve_atomic"]
    else:
        input_reserve,output_reserve=bank["base_reserve_atomic"],bank["sol_reserve_lamports"]
    return _quote_exact_input(
        amount=amount,input_reserve=input_reserve,output_reserve=output_reserve,
        config=config,creator_enabled=bank["creator_enabled"],
        creator_fee_on_input=creator_on_input)


def conditional_markouts(s1,s2,*,first_slot,second_slot,registered_before_s2):
    if (type(first_slot) is not int or type(second_slot) is not int
            or first_slot<=0 or second_slot<=first_slot
            or registered_before_s2 is not True
            or s1["stable_pool_identity"]!=s2["stable_pool_identity"]
            or s1["config"]!=s2["config"]
            or s1["pool"]!=POOL or s2["pool"]!=POOL
            or s1["mint"]!=MINT or s2["mint"]!=MINT):
        raise ValueError("cpmm_noncausal_or_inconsistent_two_bank_comparison")
    input_changed=_jsonhash(s1)!=_jsonhash(s2)
    results=[]
    for budget in ENTRY_LAMPORTS:
        buy=_quote(s1,"BUY",budget)
        quantity=buy["output"]
        try:
            sell=_quote(s2,"SELL",quantity)
            proceeds=sell["output"]
            pnl_before_extra=proceeds-budget
            lower=pnl_before_extra-COST_ASSUMPTION_LAMPORTS
            results.append(dict(input_lamports=budget,
                hypothetical_S1_token_quantity_atomic=quantity,
                observed_S2_sell_quote_lamports=proceeds,
                gross_conditional_markout_lamports=pnl_before_extra,
                conditional_net_with_assumed_10000_lamports=lower,
                assumed_network_cost_lamports=COST_ASSUMPTION_LAMPORTS,
                cost_source="hypothetical_not_observed",
                execution_verified=False,strict_economic_cycle_qualified=False,
                profit_validated=False))
        except ValueError:
            results.append(dict(input_lamports=budget,
                hypothetical_S1_token_quantity_atomic=quantity,
                observed_S2_sell_quote_lamports=None,
                gross_conditional_markout_lamports=None,
                conditional_net_with_assumed_10000_lamports=None,
                refusal="S2_sell_projection_failed",
                execution_verified=False,strict_economic_cycle_qualified=False,
                profit_validated=False))
    return dict(schema="rugger-prospective-cpmm-markout-v1",
        status=("DESCRIPTIVE_TWO_BANK_HYPOTHETICAL_MARKOUT" if input_changed
                else "UNCHANGED_BANK_FRICTION_ONLY"),
        observed_pool_state_changed=input_changed,
        observed_independent_market_transition_count=(1 if input_changed else 0),
        pool=POOL,mint=MINT,
        first_slot=first_slot,second_slot=second_slot,
        s1_input_sha256=_jsonhash(s1),s2_input_sha256=_jsonhash(s2),
        fixed_budgets_lamports=list(ENTRY_LAMPORTS),
        results=results,
        selection_registered_before_S2=True,
        future_S2_treated_as_S1_executable_quote=False,
        hypothetical_entry_changes_to_actual_S2_bank=False,
        master_vs_baseline_economic_edge_validated=False,
        completed_actual_buy_sell_cycles=0,
        strict_economic_cycles_qualified=0,live_ready_to_arm=False,
        financial_order_submitted=False)


def observe_prospective_two_banks(rpc,*,wait_seconds=HOLD_SECONDS,sleep=time.sleep):
    if not callable(rpc) or type(wait_seconds) is not int or not 1<=wait_seconds<=20:
        raise ValueError("bounded_prospective_public_observation_required")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("wrong_mainnet_genesis")
    opts=dict(encoding="base64",commitment="confirmed",minContextSlot=458932585)
    first=rpc("getMultipleAccounts",[[POOL],opts])
    slot0,rows=_bank(first,1,458932585)
    pool,_=_static_graph(POOL,rows[0])
    addresses=[POOL,pool["amm_config"],pool["token_0_vault"],pool["token_1_vault"]]
    a=rpc("getMultipleAccounts",[addresses,dict(
        encoding="base64",commitment="confirmed",minContextSlot=slot0)])
    s1_slot,entries=_bank(a,4,slot0)
    s1=decode_bank(dict(zip(addresses,entries,strict=True)))
    registration=dict(pool=POOL,mint=MINT,entry_sizes=list(ENTRY_LAMPORTS),
        s1_slot=s1_slot,s1_sha256=_jsonhash(s1),holding_seconds=wait_seconds,
        planned_next_read="getMultipleAccounts_current_confirmed",
        market_selection="fixed_before_future_bank",
        no_trade=True)
    print(json.dumps(dict(phase="REGISTERED_BEFORE_S2",
        commitment="confirmed",registration_sha256=_jsonhash(registration),
        s1_slot=s1_slot,financial_order_submitted=False),sort_keys=True),flush=True)
    sleep(wait_seconds)
    b=rpc("getMultipleAccounts",[addresses,dict(
        encoding="base64",commitment="confirmed",minContextSlot=s1_slot+1)])
    s2_slot,entries=_bank(b,4,s1_slot+1)
    s2=decode_bank(dict(zip(addresses,entries,strict=True)))
    output=conditional_markouts(s1,s2,first_slot=s1_slot,second_slot=s2_slot,
                                registered_before_s2=True)
    output.update(preregistration_sha256=_jsonhash(registration),
        rpc_calls_used=getattr(rpc,"count",None),
        source_provider_claim_confirmed=True,
        independent_RPC_provider_comparison_for_this_S2=False,
        actual_fill_or_executable_profit_verified=False)
    return output


def main():
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_API_key_must_be_in_GitHub_secrets")
        report=observe_prospective_two_banks(
            HeliusReadOnlyRpc.from_environment(max_calls=4))
    except Exception as exc:
        code=str(exc)
        safe=(code if type(exc) is ValueError and len(code)<110
              and code.replace("_","").isalnum() else type(exc).__name__)
        report=dict(status="REFUSED",safe_reason=safe,
                    financial_order_submitted=False,
                    live_ready_to_arm=False,economic_edge_validated=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report.get("status") in (
        "DESCRIPTIVE_TWO_BANK_HYPOTHETICAL_MARKOUT",
        "UNCHANGED_BANK_FRICTION_ONLY") else 2


if __name__=="__main__":
    sys.exit(main())

"""Strict S1 signed-source -> existing Master curve bank evidence bridge.

The signed creator and single-context seven-account bank already exist at S1.
Previously the real Master frame discarded the decoded bank as None. This
bridges ONLY authenticated, identity/supply-qualified bank facts into the
frozen BEFORE-S2 frame, with exact observed fee rates and reserve units.

It never supplies fake USD features, executable quotes, historical edge,
operational health, or capital. WAIT remains mandatory until those are real.
"""
from __future__ import annotations

import re

from bot.p3.curve_size_grid import _s1_inputs

SHA256=re.compile(r"^[0-9a-f]{64}$")
DOCUMENTED_NON_TRADE_BLOCKERS=frozenset({
    "execution_not_verified",
    "additional_execution_costs_unknown",
    "creation_transaction_not_verified_by_snapshot",
    # PlatformConfig does not retain original platform admin seed; explicitly
    # UNKNOWN alone is not a disqualifier for quote/reserve MODELING, but still
    # disqualifies the actual Master for any ENTER decision.
    "original_platform_admin_seed_not_retained",
})

def signed_s1_master_bank(*,analysis,mint,pool,creator,signature,
                          source_slot,received_at_ms,raw_bank_sha256,
                          signed_creation_verified):
    """Return (authenticated bank, refusal code) without guessing fields."""
    if (type(signed_creation_verified) is not bool or
            signed_creation_verified is not True or
            type(analysis) is not dict or
            analysis.get("evidence_profile")!="published_metadata_v1" or
            analysis.get("pool_address")!=pool or
            analysis.get("mint")!=mint or
            analysis.get("context_slot")!=source_slot or
            type(source_slot) is not int or source_slot<=0 or
            type(received_at_ms) is not int or received_at_ms<=0 or
            type(creator) is not str or not creator or
            type(signature) is not str or not signature or
            type(raw_bank_sha256) is not str or
            SHA256.fullmatch(raw_bank_sha256) is None):
        return None,"S1_SIGNED_CONTEXT_OR_PROVENANCE_UNVERIFIED"
    if (type(analysis.get("risk_flags")) is not list or
            analysis["risk_flags"] or
            type(analysis.get("blocking_reasons")) is not list or
            any(type(s) is not str or s not in DOCUMENTED_NON_TRADE_BLOCKERS
                for s in analysis["blocking_reasons"])):
        return None,"S1_BANK_RISK_OR_UNKNOWN_BLOCKER"
    facts=analysis.get("facts")
    if type(facts) is not dict:
        return None,"S1_BANK_DECODED_FACTS_MISSING"
    ident=facts.get("identity_certification")
    if (type(ident) is not dict or
            ident.get("account_discriminators_verified") is not True):
        return None,"S1_BANK_IDENTITY_NOT_INDEPENDENTLY_CERTIFIED"
    fully_qualified=(ident.get("program_derived_addresses_verified") is True
                     and ident.get("blocking_reasons")==[]
                     and facts.get("program_derived_addresses_verified") is True)
    partial_model_only=False
    if not fully_qualified:
        # Only ONE published schema gap is permissible for model analysis:
        # the original PlatformConfig admin seed cannot be independently
        # reconstructed from the retained platform account. All other PDAs,
        # owners, discriminators, vault links, supplies and signed creation
        # remain mandatory. Never mark identity_qualified=True in this case.
        checks=ident.get("checks")
        if (type(checks) is not list
                or not checks
                or ident.get("blocking_reasons")!=[
                    "original_platform_admin_seed_not_retained"]
                or ident.get("program_derived_addresses_verified") is not False
                or facts.get("program_derived_addresses_verified") is not False):
            return None,"S1_BANK_IDENTITY_NOT_INDEPENDENTLY_CERTIFIED"
        by_name={}
        for check in checks:
            if (type(check) is not dict
                    or type(check.get("name")) is not str
                    or check["name"] in by_name
                    or check.get("status") not in ("PASS","UNKNOWN")):
                return None,"S1_BANK_IDENTITY_NOT_INDEPENDENTLY_CERTIFIED"
            by_name[check["name"]]=check
        mandatory=("pool_pda","vault_a_pda","vault_b_pda",
                   "config_pda","authority_pda")
        platform=by_name.get("platform_pda")
        if (any(by_name.get(k,{}).get("status")!="PASS" for k in mandatory)
                or type(platform) is not dict
                or platform.get("status")!="UNKNOWN"
                or platform.get("reason")!="original_platform_admin_seed_not_retained"
                or any(v.get("status")!="PASS" and k!="platform_pda"
                       for k,v in by_name.items())):
            return None,"S1_BANK_IDENTITY_NOT_INDEPENDENTLY_CERTIFIED"
        partial_model_only=True
    supply=facts.get("supply_consistency")
    if type(supply) is not dict or supply.get("matches") is not True or supply.get("context_slot") != source_slot:
        return None,"S1_BANK_SUPPLY_NOT_RECONCILED"
    try:
        source=_s1_inputs(analysis)
    except (ValueError,TypeError,KeyError):
        return None,"S1_BANK_FEE_OR_RESERVE_FACTS_UNQUALIFIED"
    if (source["pool"].get("mint_a")!=mint or
            source["pool"].get("mint_b")!="So11111111111111111111111111111111111111112"):
        return None,"S1_BANK_WRONG_NATIVE_SOL_POOL"
    return dict(
        observation_id="signed-s1-"+signature,
        mint=mint,pool=pool,creator=creator,
        source_slot=source_slot,available_at_ms=received_at_ms,
        provenance="retained_rpc_snapshot",
        identity_qualified=not partial_model_only,
        creation_verified=True,supply_verified=True,
        platform_admin_pda_unverified=partial_model_only,
        research_only_no_execution=(partial_model_only is True),
        evidence_tail_hash=raw_bank_sha256,
        pool_state=source["pool"],
        fee_rates_ppm=list(source["fee_rates_ppm"]),
        base_vault_atomic=source["base_vault_atomic"],
        quote_vault_lamports=source["quote_vault_lamports"],
        curve_type=0,
        share_fee_rate_ppm=source["share_fee_rate_ppm"],
    ),("S1_PARTIAL_PLATFORM_ADMIN_UNKNOWN_MODEL_ONLY" if partial_model_only else None)

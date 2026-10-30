"""Bounded MAINNET finalized LaunchLab creation sampling, no wallet or trade.

Exactly one *newest-first* page of 20 program signatures is registered before
fetching up to four successful tx pairs. Every candidate attempted remains
in the denominator, even if no creation or no transaction can be decoded.
This is a sample, not complete LaunchLab discovery or P4 market qualification.

Raw JSON exact-message Ed25519 checks are independent of jsonParsed IDL
candidate classification, but both come from one RPC. No source-clock-qualified
entry prices, own BUY/SELL inventory, independent market control or strategy
profit is inferred from a detected launch.
"""
import hashlib
import json
import os
import sys
from bot.p3.certification import PROGRAM
from bot.p3.platform_admin_history import _signature
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.scanner.transaction_parser import find_raydium_launches

PAGE_LIMIT=20
BODY_LIMIT=4
RAW_OPTS=dict(encoding="json",commitment="finalized",
              maxSupportedTransactionVersion=0)
PARSED_OPTS=dict(encoding="jsonParsed",commitment="finalized",
                 maxSupportedTransactionVersion=0)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
            separators=(",",":"),allow_nan=False).encode()).hexdigest()


def read_launchlab_creation_sample(rpc):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("explicit_mainnet_genesis_required")
    page=rpc("getSignaturesForAddress",[
        PROGRAM,dict(limit=PAGE_LIMIT,commitment="finalized")])
    if type(page) is not list or len(page)>PAGE_LIMIT:
        raise ValueError("bounded_mainnet_signature_page_invalid")
    valid=[]
    for row in page:
        if (type(row) is not dict or type(row.get("slot")) is not int
                or row["slot"]<=0 or "err" not in row):
            raise ValueError("malformed_sample_signature_row")
        _signature(row.get("signature"))
        valid.append(row)
    if len({r["signature"] for r in valid})!=len(valid):
        raise ValueError("duplicate_program_signature_page")
    # The choices are frozen from the page before any transaction is inspected.
    chosen=[r for r in valid if r["err"] is None][:BODY_LIMIT]
    registered=dict(schema="rugger-helius-sampled-launchlab-creations-v1",
        program=PROGRAM,page_limit=PAGE_LIMIT,
        page_sha256=_digest(valid),
        transaction_candidates=[r["signature"] for r in chosen],
        candidate_count=len(chosen),page_rows=len(page),
        page_selection="first_four_successful_in_newest_first_page",
        inspection_only=True,no_live_orders=True)
    report=[]
    creators=set()
    for row in chosen:
        sig=row["signature"];slot=row["slot"]
        raw=rpc("getTransaction",[sig,RAW_OPTS])
        parsed=rpc("getTransaction",[sig,PARSED_OPTS])
        if raw is None or parsed is None:
            report.append(dict(signature=sig,status="TRANSACTION_NOT_AVAILABLE"))
            continue
        if (type(raw) is not dict or type(parsed) is not dict
                or raw.get("slot")!=slot or parsed.get("slot")!=slot
                or type(raw.get("meta")) is not dict or
                type(parsed.get("meta")) is not dict or
                raw["meta"].get("err") is not None or
                parsed["meta"].get("err") is not None or
                raw.get("transaction",{}).get("signatures",[None])[0]!=sig or
                parsed.get("transaction",{}).get("signatures",[None])[0]!=sig):
            report.append(dict(signature=sig,status="INCONSISTENT_FINALIZED_TRANSACTION"))
            continue
        try:
            verification=verify_compiled_rpc_signatures(raw)
            if verification.get("cryptographic_signatures_verified") is not True:
                raise ValueError("ed25519_mismatch")
            normalized=normalized_compiled_transaction(raw)
            keys={k["pubkey"] for k in normalized["transaction"]["message"]["accountKeys"]}
            launches=find_raydium_launches(parsed)
            if any(not {v["mint"],v["creator"],v["pool_state"]}.issubset(keys)
                   for v in launches):
                raise ValueError("parsed_identity_not_in_verified_message")
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):
            report.append(dict(signature=sig,status="SIGNATURE_OR_CREATION_REJECTED"))
            continue
        if not launches:
            report.append(dict(signature=sig,status="VERIFIED_NON_CREATION",
                slot=slot,exact_message_sha256=verification["exact_message_sha256"]))
            continue
        creators.update(v["creator"] for v in launches)
        report.append(dict(signature=sig,status="SIGNED_CREATION_CANDIDATE",
            slot=slot,exact_message_sha256=verification["exact_message_sha256"],
            launches=[dict(mint=v["mint"],creator=v["creator"],
                           pool=v["pool_state"]) for v in launches]))
    return dict(schema="rugger-helius-sampled-launchlab-creations-v1",
        status="BOUNDED_HISTORICAL_SAMPLE_RECORDED",
        registered_selection_sha256=_digest(registered),
        page_sha256=registered["page_sha256"],page_row_count=len(page),
        inspected_transactions=len(chosen),chosen_count=len(chosen),
        source_provider_claim_finalized=True,
        records=report,
        signed_creation_candidates=sum(r["status"]=="SIGNED_CREATION_CANDIDATE" for r in report),
        distinct_creator_claims_in_sample=len(creators),
        independent_creators_economically_qualified=0,
        requested_universe_coverage_verified=False,
        data_kind="historical_backfill_not_prospective_asof",
        actual_buy_sell_cycles=0,master_vs_reference_edge_validated=False,
        financial_order_submitted=False,live_ready_to_arm=False,
        rpc_calls_used=getattr(rpc,"count",None))


def main():
    try:
        if "HELIUS_API_KEY" not in os.environ:
            raise ValueError("helius_actions_secret_required")
        report=read_launchlab_creation_sample(
            HeliusReadOnlyRpc.from_environment(
                max_calls=10,allow_launch_discovery=True))
    except Exception as exc:
        code=str(exc)
        safe=(code if type(exc) is ValueError and len(code)<100
              and code.replace("_","").isalnum() and not code.startswith("helius_api_key")
              else type(exc).__name__)
        report=dict(status="REFUSED",reason=safe,
                    financial_order_submitted=False,live_ready_to_arm=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="BOUNDED_HISTORICAL_SAMPLE_RECORDED" else 2


if __name__=="__main__":
    sys.exit(main())

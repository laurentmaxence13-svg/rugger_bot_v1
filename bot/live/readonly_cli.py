"""One explicitly authorized READ-ONLY Solana CPMM mainnet preflight.

This command cannot send a transaction because HttpJsonRpcTransport receives
NO submission authorizer. It does NOT load .env, wallets or private keys.
Reports are private local files only, never committed or uploaded.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

os.environ["RUGGER_NO_DOTENV"]="1"

from bot.live.readonly_plan import validate_readonly_plan,readonly_plan_sha256
from bot.live.readonly_report import make_private_report,save_private_report
from bot.live.readonly_diagnostics import safe_refusal_reason


async def once(plan):
    import aiohttp
    from bot.p3.transport import (
        PhaseRecorder,connector,disable_retries,managed_proxy_routes)
    from bot.live.rpc import HttpJsonRpcTransport,SolanaRpc
    from bot.live.cpmm_readiness import preflight_migrated_sell

    endpoint=plan["rpc_endpoint"]
    routes=managed_proxy_routes((endpoint,))
    phase=PhaseRecorder(lambda event:None)
    # Caller-managed TLS, anonymous cookie jar, no automatic retries, no
    # authority to sign or submit. Transport budget is identical to plan.
    async with aiohttp.ClientSession(
            trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),
            connector=connector(phase,proxy_host=urlsplit(routes[endpoint]).hostname)
    ) as session:
        disable_retries(session)
        transport=HttpJsonRpcTransport(
            session,endpoint=endpoint,proxy=routes[endpoint],
            max_requests=plan["max_rpc_requests"],
            max_elapsed_seconds=plan["max_transport_elapsed_seconds"],
            submission_authorizer=None)
        rpc=SolanaRpc(transport)
        phase=dict(name='not_started')
        def note_phase(label):
            # Only labels from the internal fixed phase sequence are accepted.
            if label not in ('program_pin_launchlab','program_pin_cpmm',
                'migration_receipt','cpmm_bank','unsigned_simulation','complete'):
                raise ValueError('unknown_internal_preflight_phase')
            phase['name']=label
        try:
            result=await preflight_migrated_sell(
                rpc,phase_hook=note_phase,program_pins=plan["program_pins"],
                original_launchlab_pool=plan["original_launchlab_pool"],
                migrated_cpmm_pool=plan["migrated_cpmm_pool"],
                migration_signature=plan["migration_signature"],
                mint=plan["mint"],wallet=plan["wallet"],
                decision_id=plan["decision_id"],
                min_context_slot=plan["min_context_slot"],
                expected_endpoint_sha256=rpc.endpoint_sha256,
                expected_genesis_hash=plan["expected_genesis_hash"],
                clock_ms=lambda:time.time_ns()//1_000_000,
                amount_in=plan["amount_in"],
                slippage_bps=plan["slippage_bps"],
                max_slippage_bps=plan["max_slippage_bps"],
                max_price_impact_bps=plan["max_price_impact_bps"],
                compute_unit_limit=plan["compute_unit_limit"],
                priority_fee_micro_lamports=plan["priority_fee_micro_lamports"],
                max_priority_fee_lamports=plan["max_priority_fee_lamports"],
                max_bank_age_ms=plan["max_bank_age_ms"])
        except (ValueError,TypeError,KeyError,RuntimeError) as error:
            # Never convert a failed RPC, wallet mismatch or route validation
            # into a success. Suppress raw exception text (may contain data).
            result=dict(status="REFUSED",reason=safe_refusal_reason(error))
        result["observed_read_only_RPC_calls"]=transport.used
        result["max_allowed_RPC_calls"]=plan["max_rpc_requests"]
        result["diagnostic_phase"]=phase["name"]
        result["rpc_method_trace"]=list(transport.method_trace)
        result["financial_order_submitted"]=False
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",required=True)
    parser.add_argument("--out")
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--validate-only",action="store_true")
    choice.add_argument("--run-readonly",action="store_true")
    args=parser.parse_args(argv)
    plan=json.loads(Path(args.plan).read_text(encoding="utf-8"))
    plan=validate_readonly_plan(plan)
    plan_hash=readonly_plan_sha256(plan)
    if args.validate_only:
        print(json.dumps(dict(plan_status="VALIDATED_OFFLINE",
            plan_sha256=plan_hash,new_RPC_requests=0,
            live_execution_authorized=False),sort_keys=True))
        return 0
    if not args.out:
        parser.error("--out required for read-only network execution")
    path=Path(args.out)
    if path.exists() or not path.parent.is_dir():
        raise ValueError("new_private_evidence_file_required")
    result=asyncio.run(once(plan))
    report,_=make_private_report(plan,result)
    sha=save_private_report(path,report)
    print(json.dumps(dict(status=result.get("status","REFUSED"),
        reason=result.get("reason"),diagnostic_phase=result.get("diagnostic_phase"),
        plan_sha256=plan_hash,
        report_file_sha256=sha,
        requests_used=result["observed_read_only_RPC_calls"],
        financial_order_submitted=False,
        live_ready_to_arm=False),sort_keys=True))
    return 0 if result.get("status")=="UNSIGNED_CPMM_ROUTE_SIMULATED" else 2



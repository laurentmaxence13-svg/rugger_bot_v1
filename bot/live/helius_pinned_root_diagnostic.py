"""Post-hoc diagnostic of ONE pinned cryptographically archived LaunchLab creator.

IMPORTANT: a present-day pool account is NOT its state at the launch decision.
This read-only root probe cannot create as-of S1 data or market profit claims.
"""
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.helius_index_prospective_cohort import _bank
from bot.p3.launchlab import addresses_from_pool, SnapshotEvidenceError
from bot.p3.quotes import SOL_MINT

# Fixed exact public evidence from 41238437873, no addresses from unauthenticated input.
SOURCE_RUN=41238437873
SOURCE_SLOT=463820908
PINNED_SIGNATURE="63Ji1Dk5B1V9Z3rfBegF2d56ztZe7MS8mUABkWZKvzyqnsTFwaehFanHSi7ESotjtfd5a6DeozHVPprpXN8FWHk7"
PINNED_CREATOR="9mbm5SZeQjmiwp5TMGRKiRK5MYmr9hU1KhLBmHVa51jj"
PINNED_MINT="4jKTHT9CqXXTc4YxpBZaDqQ1iC78atD17Ywfi8rak5nP"
PINNED_POOL="5j2XFdGPAbS2daWAoqLjCcWb7nk3fMEXvepmzjMQ96Nj"
REFUSAL_CODES=frozenset((
    "pool_owner_or_executable_invalid","pool_encoding_invalid",
    "pool_unsupported_layout_length","pool_base_mint_mismatch",
    "invalid_public_address"))


def inspect_pinned_root(rpc, *, clock=lambda: datetime.now(timezone.utc).isoformat()):
    if not callable(rpc) or rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("pinned_mainnet_genesis_required")
    slot,accounts=_bank(rpc,[PINNED_POOL],SOURCE_SLOT)
    account=accounts[PINNED_POOL]
    result=dict(schema="rugger-posthoc-pinned-pool-root-v1",
        original_signed_creator_archive_run=SOURCE_RUN,
        original_signed_creator_signature=PINNED_SIGNATURE,
        original_creation_slot=SOURCE_SLOT,
        original_creator=PINNED_CREATOR,
        original_mint=PINNED_MINT,
        original_pool=PINNED_POOL,
        snapshot_slot=slot,
        source_to_current_slot_gap=slot-SOURCE_SLOT,
        inspected_at_utc=clock(),
        status="POOL_ACCOUNT_UNAVAILABLE",
        root_decode_error=None,
        pool_account_present=False,
        pool_current_owner=None,
        pool_current_executable=None,
        pool_data_length_bytes=None,
        decoded_mint_a=None,decoded_mint_b=None,
        current_SOL_quote_account_graph_qualified=False,
        historical_asof_entry_state_verified=False,
        provider_executable_buy_sell_quote_observed=False,
        qualified_market_economic_cycles=0,
        master_net_pnl_lamports=None,
        reference_net_pnl_lamports=None,
        financial_order_submitted=False,
        live_ready_to_arm=False)
    if account is None:
        return result
    if type(account) is not dict:
        raise ValueError("provider_root_shape_invalid")
    result["pool_account_present"]=True
    owner=account.get("owner")
    if type(owner) is str:
        result["pool_current_owner"]=owner
    if type(account.get("executable")) is bool:
        result["pool_current_executable"]=account["executable"]
    data=account.get("data")
    if (type(data) is list and len(data)==2 and data[1]=="base64"
            and type(data[0]) is str and len(data[0])<=20_000):
        try:
            raw=base64.b64decode(data[0],validate=True)
            result["pool_data_length_bytes"]=len(raw)
        except (ValueError,TypeError,base64.binascii.Error):
            pass
    try:
        graph=addresses_from_pool(account,PINNED_MINT,PINNED_POOL)
    except SnapshotEvidenceError as exc:
        code=str(exc)
        result["root_decode_error"]=code if code in REFUSAL_CODES else "unsupported_pool_root"
        result["status"]="CURRENT_ROOT_REFUSED_NOT_PROSPECTIVE"
        return result
    result["decoded_mint_a"]=graph["mint_a"]
    result["decoded_mint_b"]=graph["mint_b"]
    result["current_SOL_quote_account_graph_qualified"]=(graph["mint_b"]==SOL_MINT
                                                          and len(set(graph.values()))==7)
    result["status"]="CURRENT_ROOT_DECODED_NOT_PROSPECTIVE"
    return result


def main():
    if (os.environ.get("GITHUB_ACTIONS")!="true" or
        not os.environ.get("GITHUB_WORKSPACE") or
        not os.environ.get("HELIUS_API_KEY")):
        print(json.dumps(dict(status="ROOT_PROBE_REFUSED",
            financial_order_submitted=False,safe_error_class="MissingAuthorizedEnvironment")))
        return 2
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=2)
        result=inspect_pinned_root(rpc)
        root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        if not (root/"bot/p3/launchlab.py").is_file():
            raise ValueError("repository_root_required")
        directory=root/"paper_artifacts"
        if directory.is_symlink():
            raise ValueError("artifact_symlink_refused")
        directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/f"pinned_root_diagnostic_{os.environ['GITHUB_RUN_ID']}.json"
        with path.open("x",encoding="utf-8") as stream:
            stream.write(json.dumps(result,sort_keys=True,allow_nan=False)+"\n")
        print(json.dumps(dict(status=result["status"],
            root_decode_error=result["root_decode_error"],
            current_owner=result["pool_current_owner"],
            current_data_length=result["pool_data_length_bytes"],
            source_to_current_slot_gap=result["source_to_current_slot_gap"],
            market_pnl_verified=False,financial_order_submitted=False)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="ROOT_PROBE_REFUSED",
            safe_error_class=type(exc).__name__,
            live_ready_to_arm=False,financial_order_submitted=False)))
        return 2


if __name__=="__main__":
    sys.exit(main())

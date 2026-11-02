"""One-shot, public Bitquery four-Parquet official sample evidence audit.

No subscription, wallet, private endpoint, Helius API key, transaction signing,
or historical profitability claim. The four public samples are 100-slot
NON-CONTIGUOUS windows and cannot certify a 48h cohort or causal Master trades.
Manual --network is required. The fixed URLs are vendor-advertised samples.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = "https://bitquery-blockchain-dataset.s3.us-east-1.amazonaws.com/datashare/solana/"
SAMPLES = {
    "launchpad_trades": ("raydium_launchpad/dex_trades/423635600_423635699.parquet",
                         "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj", "trades"),
    "launchpad_pools": ("raydium_launchpad/dex_pools/423635600_423635699.parquet",
                        "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj", "pools"),
    "cpmm_trades": ("raydium_cpmm/dex_trades/423500000_423500099.parquet",
                    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", "trades"),
    "cpmm_pools": ("raydium_cpmm/dex_pools/423500000_423500099.parquet",
                   "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", "pools"),
}
MAX_SAMPLE_BYTES = 12_000_000
SOL_MINTS = ("11111111111111111111111111111111",
             "So11111111111111111111111111111111111111112")
COMMON_REQUIRED = {
    "Block_Slot", "Block_Time", "Transaction_Signature",
    "Transaction_Result_Success", "Transaction_Fee", "Transaction_Signer",
}
REQUIRED = {
    "trades": COMMON_REQUIRED | {
        "Trade_Dex_ProgramAddress", "Trade_Buy_Currency_MintAddress",
        "Trade_Sell_Currency_MintAddress", "Trade_Buy_Amount",
        "Trade_Sell_Amount", "Trade_Market_MarketAddress",
        "Instruction_Index", "Trade_Index",
    },
    "pools": COMMON_REQUIRED | {
        "Pool_Dex_ProgramAddress", "Pool_Market_MarketAddress",
        "Pool_Market_BaseCurrency_MintAddress",
        "Pool_Market_QuoteCurrency_MintAddress",
        "Pool_BaseCurrency_PostAmount", "Pool_QuoteCurrency_PostAmount",
        "Pool_BaseCurrency_ChangeAmount", "Pool_QuoteCurrency_ChangeAmount",
        "Instruction_Index", "PoolEvent_Index",
    },
}


def inspect_columns(columns, kind):
    """A schema mismatch is a blocker, never guessed from a column position."""
    if kind not in REQUIRED:
        raise ValueError("unknown_parquet_table_kind")
    if len(columns) != len(set(columns)):
        raise ValueError("duplicate_parquet_columns")
    missing = sorted(REQUIRED[kind] - set(columns))
    if missing:
        raise ValueError("missing_required_columns:" + ",".join(missing))
    return {"column_count": len(columns), "required_columns_present": True}


def verdict(table_reports):
    """Schema support is not historical full-window availability or an edge."""
    required = set(SAMPLES)
    if set(table_reports) != required:
        raise ValueError("all_four_program_tables_required")
    return {
        "schema": "rugger-bitquery-official-four-table-free-prepurchase-v1",
        "source": "bitquery_public_vendor_samples_100_slot_windows",
        "all_four_samples_structurally_checked": all(
            v.get("schema_validated") is True for v in table_reports.values()),
        "official_sample_slot_windows_are_different": True,
        "full_48h_cohort_verified": False,
        "same_creator_launchlab_to_cpmm_migration_verified": False,
        "signed_creator_verified_from_exact_receipt": False,
        "complete_causal_s1_features_verified": False,
        "conditional_buy_sell_quotes_verified": False,
        "real_master_buy_sell_paper_cycles": 0,
        "master_net_pnl_sol": None,
        "master_reference_edge_sol": None,
        "economic_edge_validated": False,
        "live_trading_enabled": False,
        "financial_order_submitted": False,
        "recommended_paid_data_gate": (
            "REQUIRE_48H_CONTIGUOUS_FOUR_TABLES_PLUS_POST_MIGRATION_TAIL_"
            "MANIFEST_HASHES_AND_HISTORICAL_S1_FEATURE_CLOCK"),
        "samples": table_reports,
    }


def download_sample(url, path, *, opener=urlopen):
    """Strict byte budget and fixed official Amazon S3 HTTPS origin."""
    if not url.startswith(BASE) or not url.endswith(".parquet"):
        raise ValueError("unapproved_bitquery_sample_url")
    req = Request(url, headers={
        "Accept": "application/octet-stream",
        "User-Agent": "RuggerPublicParquetPrepurchaseAudit/1.0",
    }, method="GET")
    with opener(req, timeout=15) as response:
        if response.status != 200:
            raise ValueError("public_sample_http_not_200")
        if urlparse(response.geturl()).netloc != urlparse(BASE).netloc:
            raise ValueError("sample_redirect_host_refused")
        size = response.headers.get("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > MAX_SAMPLE_BYTES):
            raise ValueError("advertised_sample_too_large")
        data = response.read(MAX_SAMPLE_BYTES + 1)
    if not 8 <= len(data) <= MAX_SAMPLE_BYTES:
        raise ValueError("sample_size_out_of_bounds")
    if not data.startswith(b"PAR1") or not data.endswith(b"PAR1"):
        raise ValueError("invalid_parquet_file_magic")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def check_parquet(conn, path, *, expected_program, kind):
    """Read SELECTs only. DuckDB is optional and imported by the CLI caller."""
    escaped = str(path).replace("'", "''")
    relation = "read_parquet('" + escaped + "')"
    desc = conn.execute("DESCRIBE SELECT * FROM " + relation).fetchall()
    schema = inspect_columns([row[0] for row in desc], kind)
    column = "Trade_Dex_ProgramAddress" if kind == "trades" else "Pool_Dex_ProgramAddress"
    base = (
        "SELECT COUNT(*) AS n, MIN(Block_Slot), MAX(Block_Slot), "
        "MIN(Block_Time), MAX(Block_Time), "
        "COUNT(DISTINCT Transaction_Signature), "
        "COUNT(DISTINCT Transaction_Signer), "
        "SUM(CASE WHEN Transaction_Result_Success=FALSE THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN Transaction_Signature IS NULL OR Transaction_Signature='' "
        "THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN " + column + " IS NULL OR " + column +
        " <> ? THEN 1 ELSE 0 END) "
        "FROM " + relation
    )
    n,lo,hi,first,last,sigs,signers,failed,missing,mismatch = conn.execute(
        base, [expected_program]).fetchone()
    if not n or mismatch:
        raise ValueError("empty_or_wrong_program_sample")
    record = {
        **schema,
        "schema_validated": True,
        "rows_in_sample": int(n),
        "earliest_slot": int(lo),
        "latest_slot": int(hi),
        "first_block_time_utc": first.isoformat() if first is not None else None,
        "last_block_time_utc": last.isoformat() if last is not None else None,
        "unique_transaction_signatures": int(sigs),
        "unique_transaction_signers_NOT_creators": int(signers),
        "failed_transaction_rows": int(failed or 0),
        "missing_transaction_signatures": int(missing or 0),
        "wrong_dex_program_rows": int(mismatch or 0),
        "pool_or_curve_reserves_do_not_automatically_imply_executable_quotes": True,
    }
    if kind == "trades":
        sol = ",".join("'" + a + "'" for a in SOL_MINTS)
        buy = "Trade_Buy_Currency_MintAddress"
        sell = "Trade_Sell_Currency_MintAddress"
        fields = (
            "SELECT COUNT(DISTINCT Trade_Market_MarketAddress), "
            "SUM(CASE WHEN (" + buy + " IN (" + sol + ")) <> (" + sell +
            " IN (" + sol + ")) THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN " + buy + " IN (" + sol + ") AND " + sell +
            " NOT IN (" + sol + ") THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN " + sell + " IN (" + sol + ") AND " + buy +
            " NOT IN (" + sol + ") THEN 1 ELSE 0 END) "
            "FROM " + relation
        )
        pools, wsol_total, sold_token_to_sol, bought_token_with_sol = conn.execute(
            fields).fetchone()
        record.update({
            "distinct_trade_pools": int(pools),
            "direct_SOL_pairs_trades": int(wsol_total or 0),
            "sells_token_receives_SOL_rows": int(sold_token_to_sol or 0),
            "buys_token_pays_SOL_rows": int(bought_token_with_sol or 0),
        })
    else:
        (pools, nonnegative) = conn.execute(
            "SELECT COUNT(DISTINCT Pool_Market_MarketAddress), "
            "SUM(CASE WHEN TRY_CAST(Pool_BaseCurrency_PostAmount AS DOUBLE) < 0 OR "
            "TRY_CAST(Pool_QuoteCurrency_PostAmount AS DOUBLE) < 0 THEN 1 ELSE 0 END) "
            "FROM " + relation).fetchone()
        record.update({"distinct_pool_market_addresses": int(pools),
                       "negative_reserve_rows": int(nonnegative or 0)})
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true",
                        help="One-shot download of ONLY four hardcoded public samples")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.network:
        print("OFFLINE_ONLY:--network_REQUIRED_FOR_PUBLIC_SAMPLE_DOWNLOAD")
        return 2
    stage = "start"
    try:
        import duckdb  # deliberately absent from the Render runtime dependency graph
        with tempfile.TemporaryDirectory(prefix="rugger-bitquery-public-") as tmp:
            reports = {}
            for name, (path, program, kind) in SAMPLES.items():
                target = Path(tmp) / (name + ".parquet")
                stage = "download_" + name
                digest = download_sample(BASE + path, target)
                stage = "duckdb_read_" + name
                reports[name] = check_parquet(
                    duckdb.connect(database=":memory:"), target,
                    expected_program=program, kind=kind)
                reports[name]["sample_sha256"] = digest
            report = verdict(reports)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise ValueError("output_must_be_fresh")
        with args.output.open("x", encoding="utf-8") as writer:
            writer.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps({
            "status": "FOUR_OFFICIAL_PUBLIC_SAMPLES_VALIDATED_NOT_PROFITABILITY",
            "rows": {k: v["rows_in_sample"] for k,v in reports.items()},
            "sol_rows": {
                k: v["direct_SOL_pairs_trades"] for k,v in reports.items()
                if "direct_SOL_pairs_trades" in v},
            "economic_edge_validated": False,
            "financial_order_submitted": False,
        }, sort_keys=True))
        return 0
    except Exception as exc:
        # Only type names: no URL, provider response, credentials or body.
        # Only public schema errors are printed, never URLs, provider headers, or keys.
        headline = str(exc).splitlines()[0][:180]
        if type(exc).__name__ not in ("BinderException", "CatalogException", "ValueError"):
            headline = "details_redacted"
        print("PUBLIC_BITQUERY_SAMPLE_AUDIT_REFUSED:" + stage + ":" +
              type(exc).__name__ + ":" + headline)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only official Bitquery Parquet purchase gate, offline unit tests."""
from io import BytesIO

import pytest

from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'tools' / 'bitquery_public_parquet_preflight.py'
spec = spec_from_file_location('rugger_official_bitquery_sample_audit', source)
module = module_from_spec(spec)
spec.loader.exec_module(module)
COMMON_REQUIRED, REQUIRED, SAMPLES = module.COMMON_REQUIRED, module.REQUIRED, module.SAMPLES
inspect_columns, verdict = module.inspect_columns, module.verdict
download_sample, MAX_SAMPLE_BYTES, BASE = module.download_sample, module.MAX_SAMPLE_BYTES, module.BASE


def test_both_programs_two_tables_with_fixed_allowlisted_source():
    assert set(SAMPLES) == {
        "launchpad_trades", "launchpad_pools", "cpmm_trades", "cpmm_pools"}
    for _, (relative, program, kind) in SAMPLES.items():
        assert relative.endswith(".parquet")
        assert kind in REQUIRED
        assert len(program) > 25
        assert not relative.startswith("/") and ".." not in relative


@pytest.mark.parametrize("kind", ["trades", "pools"])
def test_required_columns_are_documented_and_exact(kind):
    names = sorted(REQUIRED[kind] | {"Other_Documented_Column"})
    report = inspect_columns(names, kind)
    assert report["required_columns_present"] is True
    assert report["column_count"] == len(names)


@pytest.mark.parametrize("kind", ["trades", "pools"])
def test_missing_fields_fail_closed(kind):
    with pytest.raises(ValueError, match="missing_required_columns"):
        inspect_columns(sorted(COMMON_REQUIRED), kind)


def test_duplicate_or_unknown_schema_fail_closed():
    cols = sorted(REQUIRED["pools"])
    with pytest.raises(ValueError, match="duplicate"):
        inspect_columns(cols + [cols[0]], "pools")
    with pytest.raises(ValueError, match="unknown"):
        inspect_columns(cols, "other")


def test_incomplete_four_dataset_gate_refused():
    with pytest.raises(ValueError, match="all_four"):
        verdict({"launchpad_trades": {"schema_validated": True}})


def test_even_four_valid_schemas_never_claim_profitable_master():
    outcome = verdict({k: {"schema_validated": True, "rows_in_sample": 12}
                       for k in SAMPLES})
    assert outcome["all_four_samples_structurally_checked"] is True
    assert outcome["full_48h_cohort_verified"] is False
    assert outcome["same_creator_launchlab_to_cpmm_migration_verified"] is False
    assert outcome["complete_causal_s1_features_verified"] is False
    assert outcome["real_master_buy_sell_paper_cycles"] == 0
    assert outcome["master_net_pnl_sol"] is None
    assert outcome["economic_edge_validated"] is False
    assert outcome["live_trading_enabled"] is False
    assert outcome["financial_order_submitted"] is False


def test_download_refuses_third_party_and_large_payload(tmp_path):
    called = []
    def fake_opener(*args, **kwargs):
        called.append(True)
        raise AssertionError("must_not_call")
    with pytest.raises(ValueError, match="unapproved"):
        download_sample("https://example.org/fake.parquet",
                        tmp_path / "never", opener=fake_opener)
    assert called == []


def test_public_sample_download_requires_valid_parquet_magic(tmp_path):
    class Response:
        status = 200
        headers = {"Content-Length": "20"}
        def geturl(self):
            return BASE + SAMPLES["launchpad_trades"][0]
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, n): return b"NOT_AN_ACTUAL_PARQUET"
    with pytest.raises(ValueError, match="invalid_parquet_file_magic"):
        download_sample(BASE + SAMPLES["launchpad_trades"][0],
                        tmp_path / "no.parquet", opener=lambda *a,**k: Response())


def test_public_sample_download_enforces_byte_budget(tmp_path):
    class Response:
        status = 200
        headers = {"Content-Length": str(MAX_SAMPLE_BYTES+1)}
        def geturl(self): return BASE+SAMPLES["launchpad_pools"][0]
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, n): raise AssertionError("must_not_download")
    with pytest.raises(ValueError, match="advertised_sample_too_large"):
        download_sample(BASE + SAMPLES["launchpad_pools"][0],
                        tmp_path / "no.parquet", opener=lambda *a,**k: Response())

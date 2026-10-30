"""Real free sample NO-GO must survive attempts to label selected winners."""
import copy
import json
from pathlib import Path
import pytest
from bot.p3.free_sample_readiness import evaluate_data_source_readiness

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "validation/live_readonly/FREE_PARQUET_P3P4_GATE_2026-10-30.json")


def test_audited_free_sample_has_zero_qualified_Sol_cycle():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    report = evaluate_data_source_readiness(source)
    assert report["source_integrity_verified_files"] == 23
    assert report["raw_sampled_wsol_event_matches"] == {"buy": 2, "sell": 0}
    assert report["raw_sampled_wsol_historical_pairs"] == 0
    assert report["checks"]["wsol_buy_and_sell_events_present"] is False
    assert report["checks"]["creator_disjoint_holdout_50_receipts"] is False
    assert report["result"] == "NO_GO_DATA_INSUFFICIENT"
    assert report["economic_edge_validated"] is False
    assert report["LIVE_READY_TO_ARM"] is False


def test_hundred_creators_and_observed_wsol_pairs_are_not_an_edge():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source.update(distinct_creator_claims=1000,historical_pairs_wsol=300)
    source["wsol_instruction_event_matched"]={"buy":1000,"sell":1000}
    report = evaluate_data_source_readiness(source)
    assert report["result"] == "NO_GO_DATA_INSUFFICIENT"
    assert report["eligible_P4_strategy_economic_cycles"] == 0
    assert report["realized_profitability_validated"] is False


def test_even_complete_tape_has_to_be_replayed_and_externally_audited():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source.update(
        full_creation_denominator_verified=True,
        complete_wallet_history_verified=True,
        after_migration_CPMM_swaps_present=True,
        all_fees_reconciled=True,
        at_decision_master_reference_observed=True,
        creator_disjoint_holdout_50_verified=True,
        source_trades_are_independent_short_per_table_samples=False,
        historical_pairs_wsol=500,
        wsol_instruction_event_matched={"buy":500,"sell":500})
    report = evaluate_data_source_readiness(source)
    assert report["result"] == "DATA_READY_FOR_PROSPECTIVE_REPLAY_ONLY"
    assert report["economic_edge_validated"] is False
    assert report["realized_profitability_validated"] is False
    assert report["LIVE_READY_TO_ARM"] is False


@pytest.mark.parametrize("bad",[
    None,{},{"schema":"unsupported"},
    {"schema":"rugger-free-Parquet-prepurchase-readiness-v1",
     "distinct_creator_claims":True,"manifest_files_sha256_verified":23,
     "wsol_instruction_event_matched":{"buy":2,"sell":0},
     "historical_pairs_wsol":0}])
def test_malformed_or_bool_instead_of_int_rejected(bad):
    with pytest.raises(ValueError):
        evaluate_data_source_readiness(bad)

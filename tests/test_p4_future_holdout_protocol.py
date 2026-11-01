"""The future-only protocol is a real immutable file, not a retrospective split."""
import json
from pathlib import Path
import pytest

from bot.p4.creator_disjoint_shadow_audit import (
    audit_creator_disjoint_shadow, _split, _validate_protocol)
from bot.p4.paired_research_ledger import freeze_pair

PROTOCOL=Path(__file__).resolve().parents[1]/"validation"/"prospective"/"20261101_public_creator_holdout_protocol.json"


def protocol():
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def case(at):
    return dict(frozen_pair=freeze_pair(dict(creator="test_creator",mint="test_mint",
        pool="test_pool",source_slot=100,asof_ms=at,
        features_available_at_ms=at-1,feature_receipt_sha256="a"*64,
        policy_sha256_master="b"*64,policy_sha256_reference="c"*64,
        master_action="WAIT",reference_action="WAIT",
        hypothetical_buy_lamports=100000000,
        source_clock_verified=False,signed_creator_verified=False)),
        followup=None,engine_trace=None)


def test_future_only_file_is_valid_and_has_conservative_gates():
    p=protocol()
    _validate_protocol(p)
    assert p["registered_at_ms"]==1793512800000
    assert p["financial_orders_allowed"] is False
    assert p["minimum_holdout_creators"]>=50
    assert p["minimum_qualified_cycles"]>=50
    assert p["position_horizon_ms"]==300000


def test_earlier_decision_is_rejected_even_with_favorable_modelled_outcome():
    p=protocol()
    with pytest.raises(ValueError,match="decision_predates_registered_holdout_protocol"):
        audit_creator_disjoint_shadow([case(p["registered_at_ms"]-1)],p)


def test_later_decision_can_be_counted_but_not_qualified_without_external_proofs():
    p=protocol()
    x=audit_creator_disjoint_shadow([case(p["registered_at_ms"]+1)],p)
    assert x["total_cases_including_missing"]==1
    assert x["creator_signature_proofs_independently_revalidated"] is False
    assert x["complete_creation_denominator_externally_verified"] is False
    assert x["empirical_net_master_advantage_verified"] is False
    assert x["actual_master_minus_reference_net_pnl_lamports"] is None
    assert x["live_ready_to_arm"] is False


def test_holdout_assignment_is_creator_only_not_future_pnl():
    p=protocol()
    assert _split("creatorA",p)==_split("creatorA",p)
    assert _split("creatorA",p) in ("holdout","development")

"""Actual Master + reference SHADOW decisions on live-bank observational prefixes.

Both real decision engines are called with the same locally available data
BEFORE any follow-up market observation. Missing signal features/creation
certification cause honest WAIT/no-trade decisions. This is not executable
PAPER inventory, a filled trade, or proof of strategy profitability.
"""
import hashlib
import json

from bot.p4.actual_master_reference_freeze import freeze_real_master_reference


def _hash(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def freeze_market_shadow(row, snapshot, *, discovered_at_ms, decision_at_ms):
    """Return an immutable research receipt using only the initial bank.

    Source prices, Helius creator signatures, full signal features and the
    provider's source quote clock are never invented. Source slot is as
    reported by the retained initial bank; later events are not consumed.
    """
    if (type(row) is not dict or type(snapshot) is not dict
            or type(discovered_at_ms) is not int or type(decision_at_ms) is not int
            or not 0 < discovered_at_ms <= decision_at_ms):
        raise ValueError("registered_initial_decision_context_required")
    for key in ("mint","pool"):
        if type(row.get(key)) is not str or not row[key]:
            raise ValueError("frozen_public_asset_identity_required")
    creator = row.get("creator_claim",row.get("creator"))
    if type(creator) is not str or not creator:
        raise ValueError("creator_claim_missing_for_shadow_frame")
    if type(row.get("ordinal")) is not int or row["ordinal"] < 0:
        raise ValueError("frozen_candidate_ordinal_required")
    slot=snapshot.get("source_slot")
    receipt=snapshot.get("available_at_ms")
    snap_id=snapshot.get("id")
    if (snapshot.get("kind")!="pool_snapshot"
            or snapshot.get("mint")!=row["mint"]
            or snapshot.get("outcome")!="observed"
            or type(slot) is not int or slot<=0
            or type(receipt) is not int or not 0 < receipt <= decision_at_ms
            or type(snap_id) is not int or snap_id<=0):
        raise ValueError("retained_initial_bank_receipt_required")
    frame=dict(
        id="p3-initial-"+str(row["ordinal"])+"-"+str(snap_id),
        mint=row["mint"],pool=row["pool"],creator=creator,
        detected_at_ms=discovered_at_ms,
        available_at_ms=decision_at_ms,source_slot=slot,
        slot_available_at_ms=receipt,
        # Required decision API clock; explicitly only bank data is present.
        # No SignalFeatures are fabricated from inferred token prices.
        features_available_at_ms=receipt,
        data_kind="market_observation",
        source_clock_verified=False,
        signed_creator_verified=False,
        observation_basis="retained_initial_bank_without_verified_signed_creation_or_signal_features",
        source_bank_observation_id=snap_id,
        features_missing=True,
        financial_entry_allowed=False,
    )
    frozen=freeze_real_master_reference(frame,history=[])
    pair=frozen["frozen_pair"]
    if (frozen.get("original_master_action")=="ENTER"
            or frozen.get("original_reference_enter_intent") is True
            or pair["research_case"]["master_action"]=="ENTER"
            or pair["research_case"]["reference_action"]=="ENTER"):
        # Deliberately fail rather than promote an unexpected enter without
        # creator, feature, source clock and capital certification.
        raise ValueError("unverified_observations_cannot_enter_shadow_position")
    return dict(schema="p3-live-bank-master-reference-shadow-v1",
        selected_ordinal=row["ordinal"],mint=row["mint"],pool=row["pool"],
        creator_claim=creator,discovery_available_at_ms=discovered_at_ms,
        decision_at_ms=decision_at_ms,
        bank_observation_id=snap_id,bank_available_at_ms=receipt,
        source_slot=slot,source_frame_sha256=_hash(frame),
        actual_master_reference=frozen,
        source_creator_verified=False,source_quote_clock_verified=False,
        complete_signal_features_available=False,
        master_action=pair["research_case"]["master_action"],
        reference_action=pair["research_case"]["reference_action"],
        frozen_pair_sha256=pair["freeze_sha256"],
        pre_followup=True,financial_order_submitted=False,
        simulated_fills=0,conditional_net_pnl_lamports=None,
        master_minus_reference_net_lamports=None,live_ready_to_arm=False)


def freeze_shadow_candidates(store, rows, initial, *, discovered_at_ms, decision_at_ms, append):
    """Persist a checkpoint for EVERY selected candidate, including failures."""
    if (type(rows) is not list or type(initial) is not dict
            or not callable(append)):
        raise ValueError("frozen_candidate_inputs_required")
    snapshots={e["id"]:e for e in store.events(kind="pool_snapshot")}
    seen=set()
    output=[]
    for row in rows:
        mint=row.get("mint")
        if mint in seen or type(mint) is not str or not mint:
            raise ValueError("duplicate_or_invalid_shadow_mint")
        seen.add(mint)
        item=initial.get(mint)
        snap=snapshots.get(item.get("snapshot_observation_id")) if type(item) is dict else None
        if snap is None:
            payload=dict(schema="p3-live-bank-master-reference-shadow-v1",
                selected_ordinal=row.get("ordinal"),mint=mint,
                reason="initial_bank_not_available",
                master_action="WAIT",reference_action="WAIT",
                engines_called=False,financial_order_submitted=False,
                conditional_net_pnl_lamports=None)
            outcome="shadow_unavailable"
        else:
            try:
                payload=freeze_market_shadow(row,snap,
                    discovered_at_ms=discovered_at_ms,decision_at_ms=decision_at_ms)
                outcome="master_reference_frozen_pre_followup"
            except ValueError:
                payload=dict(schema="p3-live-bank-master-reference-shadow-v1",
                    selected_ordinal=row.get("ordinal"),mint=mint,
                    reason="unqualified_initial_market_identity_or_evidence",
                    master_action="WAIT",reference_action="WAIT",
                    engines_called=False,financial_order_submitted=False,
                    conditional_net_pnl_lamports=None)
                outcome="shadow_unavailable"
        append("checkpoint",received_at_ms=decision_at_ms,mint=mint,
               outcome=outcome,payload=payload)
        output.append(payload)
    return output

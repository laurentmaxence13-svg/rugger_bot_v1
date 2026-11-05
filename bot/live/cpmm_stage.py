"""Non-financial CPMM liquidation staging from a held LaunchLab position.

The live journal indexes inventory by mint+original pool. After graduation the
migrated CPMM pool is different, but no trade changes the owned SPL tokens.
This bridge binds the original owned position to a separately observed CPMM
SELL, using an explicit structural migration transaction, then simulates the
complete unsigned wire. It NEVER migrates or spends journal inventory, signs,
arms, sends, or certifies the trustworthiness of historical RPC transport.

Do NOT use its successful PREPARED state as financial authorization. The future
LIVE path must add independent authenticated migration provenance, cross-pool
ledger reservations, finalized settlement and full fresh-risk admission.
"""
import hashlib
import json

from bot.p3.certification import _decode
from .cpmm_exit import PreparedCpmmExit, validate_cpmm_exit
from .migration_evidence import validate_migrate_to_cpswap_transaction
from .unsigned_preflight import check_unsigned_order
from .engine import order_record
from .journal import ACTIVE, canonical
from .safety import Mode


async def stage_cpmm_exit(engine, *, decision_id, original_pool, order,
                          migration_transaction, migration_signature,
                          expected_genesis_hash, expected_endpoint_sha256,
                          now_ms):
    """Stage a migration-linked order only in nonfinancial LIVE_PREPARED mode.

    This is explicitly NOT the LIVE_ENABLED execution path. A positive result
    proves that the historical *structure* and unsigned route agree with the
    journal, not that the RPC transport, historical signature or execution is
    independently verified. Staged orders have zero financial reservations.
    """
    if engine.mode is not Mode.LIVE_PREPARED:
        raise ValueError('CPMM_staging_requires_nonfinancial_LIVE_PREPARED')
    if (type(decision_id) is not str or not 1<=len(decision_id)<=128
            or type(now_ms) is not int or now_ms<=0):
        raise ValueError('explicit_stable_staging_identity_and_clock_required')
    _decode(original_pool)
    order=validate_cpmm_exit(order)
    request=json.loads(order.rebuild_request_json)
    if (request['decision_id']!=decision_id or original_pool==order.pool
            or order.side!='SELL' or order.transaction.required_signers!=(order.user,)):
        raise ValueError('CPMM_migrated_exit_decision_or_signer_mismatch')
    engine.journal.verify_audit()
    original=engine.journal.con.execute(
        'SELECT * FROM positions WHERE mint=? AND pool=?',
        (order.mint,original_pool)).fetchone()
    if (original is None or original['quantity_atomic']<=0
            or original['quantity_atomic']!=order.base_balance_before
            or order.input_amount!=original['quantity_atomic']):
        raise ValueError('CPMM_full_exit_requires_exact_original_owned_inventory')
    other=engine.journal.con.execute(
        'SELECT COUNT(*) FROM positions WHERE mint=? AND pool=? AND quantity_atomic>0',
        (order.mint,order.pool)).fetchone()[0]
    if other:
        raise ValueError('CPMM_pool_aliases_an_existing_distinct_position')
    for entry in engine.journal.con.execute(
            "SELECT order_json FROM orders WHERE state IN (%s)" %
            ','.join('?' for _ in ACTIVE),ACTIVE):
        if json.loads(entry[0])['mint']==order.mint:
            raise ValueError('CPMM_position_has_unresolved_orders')
    migration=validate_migrate_to_cpswap_transaction(
        migration_transaction,signature=migration_signature,
        mint=order.mint,launchlab_pool=original_pool,cpmm_pool=order.pool,
        observed_at_slot=order.source_slot)
    if migration['status']!='STRUCTURAL_MIGRATION_RECEIPT':
        raise ValueError('CPMM_origin_to_migrated_pool_not_structurally_verified')
    confirmed=[
        json.loads(row['reconciliation_json'])['slot']
        for row in engine.journal.con.execute(
            "SELECT order_json,reconciliation_json FROM orders WHERE state='RECONCILED'")
        if json.loads(row['order_json'])['mint']==order.mint
        and json.loads(row['order_json'])['pool']==original_pool
        and json.loads(row['reconciliation_json'])['chain_error'] is None
    ]
    if not confirmed or max(confirmed)>=migration['migration_slot']:
        raise ValueError('CPMM_migration_must_follow_original_finalized_position')
    result=await check_unsigned_order(engine.rpc,order,
        expected_genesis_hash=expected_genesis_hash,
        expected_endpoint_sha256=expected_endpoint_sha256,now_ms=now_ms)
    if result['result']!='SIMULATION_SUCCEEDED_UNSENT':
        return dict(stage_status='REFUSED',reason=result['reason'],
                    simulation=result,engine_state_unchanged=True,
                    live_execution_allowed=False)
    record=order_record(order)
    record.update(
        original_launchlab_pool=original_pool,
        migration_signature=migration_signature,
        migration_structure_sha256=migration['retained_transaction_sha256'],
        migration_origin_slot=migration['migration_slot'],
        cpmm_simulation_slot=result['simulation_slot'],
        cpmm_simulation_message_sha256=result['message_sha256'],
        cpmm_source_transport_authenticated=False,
        financial_submissions_allowed=False,
    )
    inserted=engine.journal.create(decision_id,record,now_ms)
    if inserted:
        engine.journal.transition(decision_id,('PREPARED',),'SIMULATED',
                                  now_ms)
    else:
        current=engine.journal.get(decision_id)
        if current['state']!='SIMULATED':
            raise ValueError('CPMM_staging_duplicate_not_in_simulated_state')
    return dict(stage_status='SIMULATED_UNSIGNED_ONLY',
        decision_id=decision_id,original_pool=original_pool,
        migrated_cpmm_pool=order.pool,mint=order.mint,
        held_inventory_atomic=original['quantity_atomic'],
        migrated_exit_input_atomic=order.input_amount,
        migration_structure_sha256=migration['retained_transaction_sha256'],
        simulation=result,
        audit_sha256=engine.journal.verify_audit(),
        original_position_remains_unchanged=True,
        position_transferred_to_cpmm=False,
        financial_reservation_created=False,
        source_transport_authenticated=False,
        historical_signature_cryptographically_verified=False,
        live_execution_allowed=False,
        live_ready_to_arm=False)

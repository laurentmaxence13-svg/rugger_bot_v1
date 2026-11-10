"""Explicit dispatch between two independently validated execution routes.

The inventory identity remains its original LaunchLab pool. A CPMM execution
pool is a separate address, bound by the journal's retained migration receipt.
Dispatching a route confers neither provenance nor financial authority.
"""
import re

from bot.p3.certification import PROGRAM,_decode
from .route import PreparedLaunchLabOrder,validate_prepared_order
from .cpmm_exit import PreparedCpmmExit,validate_cpmm_exit
from .cpmm_swap import CPMM_PROGRAM
from .cleanup import PreparedBaseAccountCleanup
from .route import TOKEN_PROGRAM


def validate_execution_order(order):
    if type(order) is PreparedLaunchLabOrder:return validate_prepared_order(order)
    if type(order) is PreparedCpmmExit:return validate_cpmm_exit(order)
    raise ValueError('explicit_supported_execution_route_required')


def route_kind(order):
    if type(order) is PreparedLaunchLabOrder:return 'LAUNCHLAB'
    if type(order) is PreparedCpmmExit:return 'CPMM'
    # Not a trade: validate_execution_order above keeps refusing it. Only the
    # engine's distinct cleanup route validates and names this kind.
    if type(order) is PreparedBaseAccountCleanup:return 'BASE_ACCOUNT_CLEANUP'
    raise ValueError('explicit_supported_execution_route_required')


def execution_program(order):
    if route_kind(order)=='BASE_ACCOUNT_CLEANUP':return TOKEN_PROGRAM
    return CPMM_PROGRAM if route_kind(order)=='CPMM' else PROGRAM


def order_inventory_pool(record):
    """Resolve only explicitly bound CPMM records; never guess a migration."""
    if type(record) is not dict:raise ValueError('exact_execution_record_required')
    pool=record.get('pool');_decode(pool)
    kind=record.get('route_kind')
    if kind=='CPMM':
        inventory=record.get('inventory_pool');_decode(inventory)
        digest=record.get('migration_binding_sha256')
        if (record.get('program_id')!=CPMM_PROGRAM or record.get('side')!='SELL'
                or inventory==pool or type(digest) is not str
                or re.fullmatch('[0-9a-f]{64}',digest) is None):
            raise ValueError('explicit_bound_CPMM_inventory_identity_required')
        return inventory
    if kind not in (None,'LAUNCHLAB'):
        raise ValueError('unsupported_execution_record_route')
    if record.get('inventory_pool',pool)!=pool:
        raise ValueError('cross_pool_inventory_requires_CPMM_migration_binding')
    return pool

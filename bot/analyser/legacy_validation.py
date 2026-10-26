"""Explicit scope contract for historical diagnostics without causal validation."""


def legacy_validation_metadata(route):
    """Keep exploratory outputs ineligible regardless of their simulated profit.

    The legacy row filters/splits do not demonstrate transaction-group separation,
    training-label availability, or point-in-time price provenance. Their numeric
    diagnostics remain useful, but cannot qualify a model or a P2 evaluation.
    """
    return {
        'route': route,
        'validation_status': 'excluded_legacy_temporal_integrity',
        'validated': False,
        'model_eligible': False,
        'eligible_for_p2': False,
        'paper_only': True,
        'real_orders_enabled': False,
        'exclusion_reasons': [
            'transaction_timestamp_partition_not_certified',
            'training_label_availability_not_purged',
            'point_in_time_price_provenance_not_verified',
        ],
    }

"""paperstream 0.5.2 -- a synthetic COLLECTED SOL/USD series of W1 size, for PERFORMANCE and IDENTITY TESTS ONLY.

``write(path, n)``: n points (W1: 21 937), strictly increasing chain positions, ending exactly with the one point of the
dayj selfcheck series (slot _FIRST_SLOT - 50), so that every decision on the frozen pack has a fresh point AND every
``as_of`` scans the whole series, as on W1. Never an input of any W1 or P0 run.
"""
import json

from bot.p4 import sol_usd_series as sus
from w1aux import dayj

W1_POINTS = 21_937


def write(path, n=W1_POINTS):
    if type(n) is not int or n < 1:
        raise ValueError('n_must_be_a_positive_integer')
    last_slot, last_time = dayj._FIRST_SLOT - 50, dayj._FIRST_TIME - 12
    points = []
    for i in range(n):
        back = n - 1 - i
        points.append(dict(schema=sus.POINT_SCHEMA, slot=last_slot - 3 * back, transaction_index=0,
                           block_time=last_time - back, received_at_ms=None, publish_time=last_time - back - 1,
                           price=15_000_000_000 + (i % 7), exponent=-8, confidence=7_500_000,
                           source_kind='pyth_onchain_account', source_ref='synthetic-test-account',
                           evidence_sha256='0' * 64, signature=None))
    with open(path, 'w') as handle:
        json.dump(dict(schema=sus.SERIES_SCHEMA, label='COLLECTED', points=points,
                       acceptance=dict(max_age_ms=120_000, max_confidence_ppm=1_000)), handle)
    return path

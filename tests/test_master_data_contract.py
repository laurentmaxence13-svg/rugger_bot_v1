import unittest
from bot import master_data_contract as c

SHA = 'a' * 64
GOOD_FEES = dict(quote_amounts_net_of_pool_fees=True, extra_fees_exclude_pool_fees=True, provenance='synthetic',
                 entry_extra_lamports=5000, exit_extra_lamports=5000, failed_attempt_lamports=[5000])
GOOD_EV = dict(available_at_ms=10, training_end_ms=5, policy_sha256=SHA, qualified_economic_cycles=50,
               independent_creator_groups=20, gross_proceeds_return_lower_bound=0.1, report_sha256='b' * 64)


class Contract(unittest.TestCase):
    def test_fees(self):
        self.assertEqual(c.validate_fees(GOOD_FEES), [])
        self.assertIn('fees_missing', c.validate_fees(None))
        bad = dict(GOOD_FEES, exit_extra_lamports=None, failed_attempt_lamports=[-1])
        self.assertEqual(set(c.validate_fees(bad)), {'exit_extra_lamports_invalid', 'failed_attempt_lamports_invalid'})
        self.assertIn('quote_amounts_net_of_pool_fees_not_true', c.validate_fees(dict(GOOD_FEES, quote_amounts_net_of_pool_fees=False)))

    def test_evidence_boundaries(self):
        self.assertEqual(c.validate_evidence(GOOD_EV, 10, SHA), [])
        self.assertIn('cycles_below_minimum', c.validate_evidence(dict(GOOD_EV, qualified_economic_cycles=49), 10, SHA))
        self.assertIn('creator_groups_below_minimum', c.validate_evidence(dict(GOOD_EV, independent_creator_groups=19), 10, SHA))
        self.assertIn('timestamps_not_causal', c.validate_evidence(dict(GOOD_EV, available_at_ms=11), 10, SHA))
        self.assertIn('policy_hash_mismatch', c.validate_evidence(GOOD_EV, 10, 'c' * 64))
        self.assertIn('report_sha256_invalid', c.validate_evidence(dict(GOOD_EV, report_sha256='B' * 64), 10, SHA))
        self.assertIn('return_bound_invalid', c.validate_evidence(dict(GOOD_EV, gross_proceeds_return_lower_bound=float('nan')), 10, SHA))

    def test_bank_state(self):
        ok = dict(identity_qualified=True, supply_verified=True, creation_verified=True)
        self.assertEqual(c.validate_bank_state(ok), [])
        self.assertEqual(c.validate_bank_state(dict(ok, supply_verified=1)), ['supply_verified_not_true'])
        self.assertEqual(c.validate_bank_state(None), ['bank_state_missing'])

    def test_event_time(self):
        e = dict(source_time_ms=1, received_at_ms=2, available_at_ms=3, source_slot=9)
        self.assertEqual(c.validate_event_time(e, 3), [])
        self.assertEqual(c.validate_event_time(e, 2), ['timestamps_not_causal'])
        self.assertEqual(c.validate_event_time(dict(e, source_slot=0), 3), ['timestamp_or_slot_missing'])

    def test_trades_and_migration_and_coverage(self):
        ok = dict(signature='s1', mint='m', side='BUY', status='ok', available_at_ms=1)
        failed = dict(signature='s2', mint='m', side='SELL', status='chain_failed', available_at_ms=2)
        self.assertEqual(c.validate_trades([ok]), [])
        d = c.validate_trades([ok, ok, failed])
        self.assertIn('duplicate_signature:s1', d)
        self.assertIn('failed_tx_fee_or_owner_missing:s2', d)
        self.assertEqual(c.validate_trades([dict(failed, fee_lamports=5000, owner='w')]), [])
        m = dict(mint='m', launchlab_pool='a', cpmm_pool='b', launchlab_available_at_ms=1, cpmm_available_at_ms=2)
        self.assertEqual(c.validate_migration(m), [])
        self.assertEqual(c.validate_migration(dict(m, cpmm_available_at_ms=0)), ['migration_order_invalid'])
        self.assertEqual(c.validate_coverage(dict(launchlab=3)), ['venue_absent:cpmm'])
        self.assertEqual(c.validate_coverage(dict(launchlab=3, cpmm=1)), [])

    def test_lifts_and_matrix(self):
        frame = dict(buy_context=dict(fees=GOOD_FEES), research_evidence=GOOD_EV,
                     bank_state=dict(identity_qualified=True, supply_verified=True, creation_verified=True))
        self.assertTrue(all(c.lifts(frame, 10, SHA).values()))
        self.assertFalse(any(c.lifts({}, 10, SHA).values()))
        causes = {row[1] for row in c.MATRIX}
        for b in ('additional_costs_unknown', 'qualified_past_edge_evidence_unavailable', 'source_identity_supply_creation_unqualified'):
            self.assertIn(b, causes)


if __name__ == '__main__':
    unittest.main()

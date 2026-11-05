import json, os, unittest
from pathlib import Path
from bot.p3 import pilot24h as p, pilot24h_offline as o

FIX = Path(os.environ.get('OBSERVER_FIXTURE_DIR', 'tests/fixtures/launchlab_trades'))


def row(**kw):
    d = dict(signature='s', slot=10, event_index=0, pool='P', kind='launchlab_trade_buy',
             program='X', recv_utc='2026-11-06T00:00:10.000000Z', chain_time=1793923200,
             causality='ok', decoded=1, slippage_bps=None, slippage_status='unknown', payload_json='{}')
    d.update(kw)
    return d


class AdapterTests(unittest.TestCase):
    def test_clean_row_ok_and_missing_fields_stay_none(self):
        self.assertEqual(o.validate_observer_row(row()), [])
        a = o.adapt_observer_row(row())
        for f in o.OBSERVER_MISSING:
            self.assertIsNone(a[f])
        self.assertEqual(a['side'], 'buy')

    def test_lookahead_and_causality_rejected(self):
        early = row(recv_utc='2026-11-06T00:00:00.000000Z', chain_time=1793923300)
        self.assertIn('lookahead_recv_before_chain_time', o.validate_observer_row(early))
        self.assertIn('causality_violation_recv_before_chain', o.validate_observer_row(row(causality='violation_recv_before_chain')))

    def test_slippage_never_zero_by_default(self):
        self.assertIn('slippage_defaulted_to_zero', o.validate_observer_row(row(slippage_bps=0)))

    def test_missing_columns_and_float_slot(self):
        self.assertTrue(o.validate_observer_row({'slot': 1})[0].startswith('missing_columns'))
        self.assertIn('slot_not_nonneg_int', o.validate_observer_row(row(slot=1.0)))

    def test_observer_output_cannot_qualify_any_cycle(self):
        rep = o.qualification_report([row(), row(kind='launchlab_trade_sell', slot=11)])
        self.assertEqual((rep['qualified_cycles'], rep['independent_creators']), (0, 0))
        self.assertEqual(p.verdict([], [])['status'], 'INSUFFICIENT DATA')

    def test_readonly_db(self):
        import sqlite3, tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'o.db')
            c = sqlite3.connect(path)
            c.execute('CREATE TABLE events(signature,slot,event_index,pool,kind,program,recv_utc,chain_time,causality,decoded,slippage_bps,slippage_status,payload_json)')
            c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row().values()))
            c.commit(); c.close()
            self.assertEqual(len(o.read_observer_events(path)), 1)

    @unittest.skipUnless(FIX.is_dir() and any(FIX.glob('*.json')), 'unaltered observer fixtures absent (PR #184/#191 not in this base)')
    def test_real_unaltered_fixtures_roundtrip(self):
        try:
            from bot.market import observer24h as ob
        except Exception as e:  # aiohttp missing etc.
            self.skipTest('observer not importable: %r' % (e,))
        n = 0
        for f in sorted(FIX.glob('*.json')):
            res = json.loads(f.read_text())['result']
            evs, _ = ob.normalise_transaction(res, '2099-01-01T00:00:00.000000Z')
            for e in evs:
                self.assertEqual(o.validate_observer_row(e), [], f.name)
                n += 1
        self.assertGreater(n, 0)


class CausalLedgerTests(unittest.TestCase):
    OBS = [dict(signature='a', event='buy', mint='M', slot=10)]

    def test_causal_check(self):
        ok = [dict(obs=('a', 'buy', 'M'), data_max_slot=10)]
        self.assertEqual(o.check_decisions_causal(ok, self.OBS), [])
        for bad in (dict(obs=('a', 'buy', 'M'), data_max_slot=11), dict(obs=('z', 'buy', 'M'), data_max_slot=1),
                    dict(obs=('a', 'buy', 'M'))):
            self.assertEqual(len(o.check_decisions_causal([bad], self.OBS)), 1)

    def _cyc(self, unknown=False):
        costs = {f: 5 for f in p.COST_FIELDS}
        s = dict(costs, slot=20, sol_lamports=1500, failed=False, signature='sx', received_utc='t2')
        if unknown:
            s['ata_rent_lamports'] = None
        return {'creator': 'C', 'creator_authenticated': True,
                'buy': dict(costs, slot=10, sol_lamports=1000, failed=False, signature='bx', received_utc='t1'), 'sell': s}

    def test_ledger_requires_prereg_and_flags_unknown(self):
        dec = [{'engine': 'MASTER', 'action': 'BUY'}]
        h = p.freeze(dec)
        cy = {'MASTER': [self._cyc(), self._cyc(unknown=True)], 'REF': []}
        led = o.build_ledger(dec, h, cy, 'synthetic')
        self.assertEqual(led['rows'][0]['net_lamports'], 500 - 60)
        self.assertIsNone(led['rows'][1]['net_lamports'])
        self.assertFalse(led['rows'][1]['qualified'])
        self.assertEqual(o.recompute_ledger(led, cy), [])
        led['rows'][0]['net_lamports'] += 1
        self.assertEqual(o.recompute_ledger(led, cy), [0])
        dec[0]['action'] = 'WAIT'
        with self.assertRaises(p.ProtocolError):
            o.build_ledger(dec, h, cy, 'synthetic')

    def test_synthetic_never_evaluable(self):
        many = [self._cyc() | {'creator': 'C%d' % i} for i in range(60)]
        self.assertEqual(p.verdict(many, many, provenance='synthetic')['status'], 'INSUFFICIENT DATA')


if __name__ == '__main__':
    unittest.main()

import unittest
from bot.p3 import pilot24h as p

COSTS = {f: 5 for f in p.COST_FIELDS}


def leg(side, slot, sol, **kw):
    d = dict(COSTS, side=side, slot=slot, sol_lamports=sol, failed=False)
    d.update(kw)
    return d


def cycle(i, **kw):
    c = {'creator': 'C%d' % i, 'creator_authenticated': True,
         'buy': leg('buy', 10, 1000), 'sell': leg('sell', 20, 1500)}
    c.update(kw)
    return c


def obs(**kw):
    d = dict(signature='s1', slot=1, received_utc='2026-11-06T00:00:00Z',
             venue='LAUNCHLAB', event='buy', side='buy', mint='M')
    d.update(kw)
    return d


class PilotTests(unittest.TestCase):
    def test_unknown_costs_flagged_not_zeroed(self):
        _, unknown = p.validate_observation(obs(network_fee_lamports=5))
        self.assertEqual(len(unknown), len(p.COST_FIELDS) - 1)

    def test_float_and_bad_rows_rejected(self):
        for bad in (obs(sol_lamports=1.5), obs(venue='X'), obs(mint=''), obs(side='sell')):
            with self.assertRaises(p.ProtocolError):
                p.validate_observation(bad)

    def test_dedup(self):
        out, dup = p.dedup([obs(), obs(), obs(signature='s2')])
        self.assertEqual((len(out), dup), (2, 1))

    def test_freeze_detects_tampering(self):
        d = [{'engine': 'MASTER', 'action': 'WAIT', 'cause': 'x'}]
        h = p.freeze(d)
        self.assertTrue(p.verify_frozen(d, h))
        d[0]['action'] = 'BUY'
        self.assertFalse(p.verify_frozen(d, h))

    def test_wait_by_cause(self):
        d = [{'engine': 'MASTER', 'action': 'WAIT', 'cause': 'additional_costs_unknown'},
             {'engine': 'MASTER', 'action': 'WAIT'},
             {'engine': 'REF', 'action': 'WAIT', 'cause': 'z'}]
        self.assertEqual(p.wait_by_cause(d), {'additional_costs_unknown': 1, 'cause_missing': 1})

    def test_disqualified_cycles(self):
        bad = [cycle(1, creator_authenticated=False),
               cycle(2, buy=leg('buy', 10, 1000, failed=True)),
               cycle(3, sell=leg('sell', 10, 1500)),
               cycle(4, sell=dict(leg('sell', 20, 1500), ata_rent_lamports=None)),
               {'creator': 'C5', 'creator_authenticated': True, 'buy': leg('buy', 1, 1)}]
        self.assertEqual(p.qualified_cycles(bad), [])

    def test_net_pnl_includes_all_costs(self):
        self.assertEqual(p.net_pnl_lamports(cycle(1)), 500 - 12 * 5)

    def test_insufficient_when_zero_or_synthetic_or_below_minimum(self):
        self.assertEqual(p.verdict([], [])['status'], 'INSUFFICIENT DATA')
        many = [cycle(i) for i in range(60)]
        self.assertEqual(p.verdict(many, many, provenance='synthetic')['status'], 'INSUFFICIENT DATA')
        self.assertEqual(p.verdict(many[:19], many)['status'], 'INSUFFICIENT DATA')
        same_creator = [cycle(0) for _ in range(30)]
        self.assertEqual(p.verdict(same_creator, same_creator)['status'], 'INSUFFICIENT DATA')

    def test_evaluable_only_at_thresholds(self):
        many = [cycle(i) for i in range(50)]
        v = p.verdict(many, many)
        self.assertEqual(v['status'], 'EVALUABLE')
        self.assertEqual(v['master_net_lamports'], 50 * 440)


if __name__ == '__main__':
    unittest.main()

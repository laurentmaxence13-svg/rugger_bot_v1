import glob, json, unittest
from bot.market import launchlab_program_decoder as D
from bot.market.launchlab_events import EventDecodeError
from bot.market.signature_backfill import BackfillError, BackfillState, run_backfill


def _tx(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return d.get('result', d)


class DecoderTests(unittest.TestCase):
    def test_fixture_verified_discriminators(self):
        seen = set()
        for p in glob.glob('tests/fixtures/launchlab_trades/*.json') + ['launchlab_tx.json']:
            for dec, _, pid in D.classify_transaction(_tx(p)):
                self.assertEqual(pid, D.LAUNCHLAB_PROGRAM)
                seen.add(dec.kind)
                self.assertNotEqual(dec.kind, 'unknown')
        self.assertEqual(seen, {'buy', 'sell', 'trade_event'})

    def test_unproven_names_never_classified_known(self):
        for n in ('initialize', 'initialize_v2', 'migrate_to_amm', 'migrate_to_cpswap'):
            d = D.decode_instruction(D.LAUNCHLAB_PROGRAM, D.anchor_ix(n) + b'\0' * 4)
            self.assertEqual((d.kind, d.evidence), ('unproven', D.DERIVED_UNVERIFIED))
        d = D.decode_instruction(D.CPMM_PROGRAM, D.anchor_ix('swap_base_input') + b'\0' * 16)
        self.assertEqual(d.kind, 'unproven')

    def test_fail_closed(self):
        self.assertEqual(D.decode_instruction('x' * 32, b'\0' * 16).kind, 'unknown')
        self.assertEqual(D.decode_instruction(D.LAUNCHLAB_PROGRAM, b'\1' * 16).kind, 'unknown')
        self.assertEqual(D.decode_instruction(D.LAUNCHLAB_PROGRAM, b'\1').kind, 'unknown')
        with self.assertRaises(EventDecodeError):
            D.classify_transaction({'foo': 1})

    def test_failed_tx_ignored_and_links(self):
        tx = _tx('launchlab_tx.json')
        tx = json.loads(json.dumps(tx)); tx['meta']['err'] = {'x': 1}
        self.assertEqual(D.classify_transaction(tx), [])
        links = D.link_evidence(D.classify_transaction(_tx('launchlab_tx.json')))
        self.assertEqual(links['trade'], 'proven')
        for k in ('creation', 'graduation', 'migration', 'cpmm_pool'):
            self.assertEqual(links[k], 'unproven')

    def test_known_hashes(self):  # recomputed independently of fixtures
        self.assertEqual(D.anchor_ix('buy_exact_in').hex(), 'faea0d7bd59c13ec')
        self.assertEqual(D.anchor_ix('sell_exact_in').hex(), '9527de9bd37c981a')


def _chain(n, start_slot=10000):
    return [{'signature': 's%05d' % i, 'slot': start_slot - i // 2, 'err': 'E' if i % 7 == 0 else None}
            for i in range(n)]            # newest first


def _fetcher(rows, calls=None):
    def fetch(addr, before, until, limit):
        if calls is not None: calls.append(before)
        i = 0 if before is None else next(k for k, r in enumerate(rows) if r['signature'] == before) + 1
        return rows[i:i + limit]
    return fetch


class BackfillTests(unittest.TestCase):
    def test_gap_over_1000_then_resume_and_idempotent(self):
        rows = _chain(2500)
        st = BackfillState('A')
        run_backfill(st, _fetcher(rows), max_pages=2)
        self.assertFalse(st.complete); self.assertTrue(st.gap)
        self.assertEqual(st.pages, 2)
        st2 = BackfillState.from_dict(st.to_dict())   # resume from persisted cursor
        run_backfill(st2, _fetcher(rows), max_pages=5)
        self.assertTrue(st2.complete)
        self.assertEqual(len(st2.seen) + len(st2.failed), 2500)
        before = dict(st2.seen)
        st3 = BackfillState('A'); run_backfill(st3, _fetcher(rows), max_pages=5)
        self.assertEqual(st3.seen, before)            # replay from scratch = same result

    def test_order_and_ambiguous_slots(self):
        st = BackfillState('A'); run_backfill(st, _fetcher(_chain(10)))
        slots = [s for _, s in st.ordered()]
        self.assertEqual(slots, sorted(slots))
        self.assertTrue(st.ambiguous_slots())

    def test_exact_page_boundary_needs_empty_page(self):
        st = BackfillState('A'); run_backfill(st, _fetcher(_chain(1000)), max_pages=1)
        self.assertFalse(st.complete)
        run_backfill(st, _fetcher(_chain(1000)), max_pages=1)
        self.assertTrue(st.complete)

    def test_fail_closed_non_monotonic_and_limits(self):
        rows = [{'signature': 'a', 'slot': 5, 'err': None}, {'signature': 'b', 'slot': 9, 'err': None}]
        with self.assertRaises(BackfillError):
            run_backfill(BackfillState('A'), lambda *a: rows)
        with self.assertRaises(BackfillError):
            run_backfill(BackfillState('A'), lambda *a: [], page_size=1001)


if __name__ == '__main__':
    unittest.main()

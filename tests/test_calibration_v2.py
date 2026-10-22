import unittest
from bot.analyser.final_decision_engine import SignalFeatures, decide


def feat(**kw):
    base = dict(
        mint='m', creator='c', signal_time=1, observed_at=100,
        prior_launches=0, behavior_known=True, relevant_transactions=1,
        dev_sales=0, relay_transfers=0, bundle_transactions=0,
        bundle_wallets=0, liquidity_usd=12000.0, price_usd=1e-5,
        quote_count=6, momentum_60s=0.10, momentum_300s=0.10,
        volume_5m_usd=7000.0, tx_buys_5m=20, tx_sells_5m=10,
        market_data_quality='partial', holder_count=20,
        top_holder_share=0.40, holder_data_known=True,
        linked_wallets=0, wallet_link_count=0, same_slot_wallets=0,
        wallet_graph_transactions=0,
    )
    base.update(kw)
    return SignalFeatures(**base)

class CalibrationV2Tests(unittest.TestCase):
    def test_viable_new_creator_can_enter_paper(self):
        d = decide(feat())
        self.assertTrue(d.enter)
        self.assertGreaterEqual(d.score, 45)

    def test_coordination_is_penalty_not_automatic_veto(self):
        d = decide(feat(bundle_transactions=3, bundle_wallets=3,
                        same_slot_wallets=4, wallet_link_count=6,
                        top_holder_share=.52, momentum_60s=.20))
        self.assertTrue(d.enter)
        self.assertIn('coordination_wallets_possible', d.risk_flags)

    def test_dev_sale_remains_hard_reject(self):
        self.assertFalse(decide(feat(dev_sales=1)).enter)

    def test_bad_liquidity_remains_hard_reject(self):
        self.assertFalse(decide(feat(liquidity_usd=50)).enter)

    def test_extreme_concentration_remains_hard_reject(self):
        self.assertFalse(decide(feat(top_holder_share=.95)).enter)

    def test_collapse_remains_hard_reject(self):
        self.assertFalse(decide(feat(momentum_60s=-.30)).enter)

if __name__ == '__main__': unittest.main()

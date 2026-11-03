"""No-network falsification tests for S1/S2 market markout sidecar."""
import copy
import unittest
from bot.p3.conditional_market_markout import audit_report


class CausalMarkoutTests(unittest.TestCase):
    def early(self):
        return dict(schema="rugger-early-confirmed-signed-S1S2-paper-v1",
            financial_order_submitted=False, live_ready_to_arm=False,
            master_net_pnl_lamports=None, reference_net_pnl_lamports=None,
            attempts=[dict(signature="example-real-public-signature", source_slot=100,
                creator="creator-one",mint="mint-one",pool="pool-one",
                signed_outer_creations=[{"creator":"creator-one"}],
                s1_slot=101,s2_slot=102,s1_received_ms=1000,s2_received_ms=2000,
                finality_verified=True,s1_model_buy_output_atomic="10000000",
                frozen_pre_S2=dict(decision_at_ms=1200,
                    master_action="WAIT",reference_action="NOT_EVALUABLE_NO_CAUSAL_FEATURES",
                    future_S2_consumed=False,financial_order_submitted=False),
                s2_conditional_proceeds_lamports="1200000000",
                s1_s2_conditional_markout_lamports="200000000")])

    def test_readonly_conditional_markout_reconciles_no_false_master_pnl(self):
        out = audit_report(self.early())
        self.assertEqual(out["denominator_observations"],1)
        self.assertEqual(out["independently_identified_model_opportunities"],1)
        row = out["conditional_model_opportunities"][0]
        self.assertEqual(row["conditional_model_markout_before_external_costs_lamports"],"200000000")
        self.assertEqual(row["assumed_extra_cost_stress"][1]["conditional_result_lamports"],"199000000")
        self.assertIsNone(out["master_net_pnl_lamports"])
        self.assertEqual(out["verified_market_paper_cycles"],0)
        self.assertFalse(out["profitability_verified"])

    def test_signer_same_id_is_not_double_counted(self):
        item=self.early()
        item["attempts"].append(copy.deepcopy(item["attempts"][0]))
        rows=audit_report(item)["conditional_model_opportunities"]
        self.assertEqual(rows[1]["reason"],"duplicate_source_signature")

    def test_two_signatures_same_creator_are_not_independent(self):
        item=self.early()
        second=copy.deepcopy(item["attempts"][0]);second["signature"]="other-signature"
        item["attempts"].append(second)
        rows=audit_report(item)["conditional_model_opportunities"]
        self.assertEqual(rows[1]["reason"],"missing_or_duplicate_creator")

    def test_future_leakage_is_refused(self):
        item=self.early()
        item["attempts"][0]["frozen_pre_S2"]["decision_at_ms"] = 2200
        with self.assertRaisesRegex(ValueError,"noncausal"):
            audit_report(item)

    def test_model_entry_mismatch_is_refused(self):
        item=self.early()
        item["attempts"][0]["s1_s2_conditional_markout_lamports"] = "9999"
        with self.assertRaisesRegex(ValueError,"nonreconciled"):
            audit_report(item)

    def test_claim_of_executed_master_entry_is_refused(self):
        item=self.early()
        item["attempts"][0]["frozen_pre_S2"]["master_action"]="ENTER"
        with self.assertRaisesRegex(ValueError,"cannot_replace_authorized"):
            audit_report(item)

    def test_no_S2_keeps_denominator_but_not_profit(self):
        item=self.early()
        del item["attempts"][0]["s2_conditional_proceeds_lamports"]
        del item["attempts"][0]["s1_s2_conditional_markout_lamports"]
        out=audit_report(item)
        self.assertEqual(out["denominator_observations"],1)
        self.assertEqual(out["independently_identified_model_opportunities"],0)

    def test_github_early_artifact_wrapper_keeps_ledger_hash_scope(self):
        source=self.early()
        out=audit_report({"events":[],"report":source})
        self.assertEqual(out["independently_identified_model_opportunities"],1)
        self.assertEqual(len(out["source_sha256"]),64)

    def test_signed_creator_bank_schema(self):
        src=self.early();r=src["attempts"][0]
        r["cryptographic_creation"]=True
        r["s1_buy_model"]={"buy_output_atomic":"10000000"}
        r["frozen_decision_before_S2"]={"at_ms":1200,"master_action":"WAIT",
            "reference_action":"WAIT_FOR_FEATURES","future_S2_used":False,"real_order":False}
        r["s2_same_exact_qty_conditional_sell_lamports"]="1200000000"
        r["s1_to_s2_conditional_curve_markout_lamports"]="200000000"
        src["schema"]="rugger-signed-creator-asof-paired-paper-v1"
        src["observations"]=[r];del src["attempts"]
        out=audit_report(src)
        self.assertEqual(out["independently_identified_model_opportunities"],1)
        self.assertIsNone(out["master_minus_reference_lamports"])

    def test_fake_profit_in_input_refused(self):
        src=self.early();src["master_net_pnl_lamports"]="50000"
        with self.assertRaisesRegex(ValueError,"input_not_readonly"):
            audit_report(src)


if __name__=="__main__":
    unittest.main()

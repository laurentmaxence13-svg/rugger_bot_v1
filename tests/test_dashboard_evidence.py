"""Safety and integration tests for the real PAPER terminal evidence adapters."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from bot.dashboard.evidence import (
    LEDGER,PROBE,SIGNED,INTEGRATED,load_local,load_uploaded,
    parse_documents,synthetic_demo,
)


def paper_ledger():
    return dict(schema=LEDGER,accounts={
        "master":dict(closed_trades=[dict(case_id="case-1",mint="REAL-MINT-A",
            paper_only=True,model_conditioned_price=True,
            gross_entry_spend_lamports=50_000_000,
            market_exit_lamports=48_000_000,
            entry_cost_lamports=10_000,exit_cost_lamports=5_000,
            net_pnl_lamports=-2_015_000)],open_inventory=[]),
        "reference":dict(closed_trades=[],open_inventory=[])},
        policy_paired_model_net_edge_lamports=-2_015_000,
        events=[dict(type="PRECOMMITTED_DECISION",case_id="case-1",
                     decisions=dict(master="ENTER",reference="WAIT"),at_ms=1793540000000)])


def network_probe():
    return dict(schema=PROBE,financial_order_submitted=False,
        paper_model_report=dict(status="REAL_SOL_S1S2_PAPER_MODEL_MARKOUTS",
            cases=[dict(mint="SOURCE-MINT",pool="SOURCE-POOL",
                actual_Master_action="WAIT",actual_reference_action="WAIT",
                S1_slot=400,hypothetical_probe_size_lamports=50_000_000,
                own_buy_overlay_sell_lamports="48511249",
                conditional_S2_sell_lamports=None)]))


class DashboardEvidenceTest(unittest.TestCase):
    def test_real_helius_nested_probe_is_never_a_master_trade(self):
        parsed=parse_documents([("helius-probe.json",network_probe())])
        self.assertEqual(len(parsed["projections"]),1)
        p=parsed["projections"][0]
        self.assertEqual(p["variation_brute_sol"],-.001488751)
        self.assertEqual(p["statut"],"HYPOTHÈSE, JAMAIS UN TRADE")
        self.assertIsNone(p["pnl_master_reel"])
        self.assertEqual(parsed["cycles"],[])
        self.assertEqual([x["decision"] for x in parsed["decisions"]],
                         ["WAIT","WAIT"])

    def test_paper_ledger_close_only_and_calculate_net(self):
        parsed=parse_documents([("paper.json",paper_ledger())])
        self.assertEqual(len(parsed["cycles"]),1)
        c=parsed["cycles"][0]
        self.assertEqual(c["resultat_net_sol"],-0.002015)
        self.assertEqual(c["frais_sol"],0.000015)
        self.assertEqual(c["qualification"],"MODÈLE CONDITIONNEL")
        self.assertIs(c["ordre_reel"],False)
        self.assertEqual(len(parsed["decisions"]),2)

    def test_open_inventory_does_not_become_completed_cycle(self):
        ledger=paper_ledger()
        ledger["accounts"]["master"]["closed_trades"]=[]
        ledger["accounts"]["master"]["open_inventory"]=[dict(
            mint="REAL-MINT-A",entry_slot=500,entry_at_ms=1793550000000)]
        parsed=parse_documents([("open.json",ledger)])
        self.assertEqual(parsed["cycles"],[])
        self.assertIn("POSITION PAPER OUVERTE",[d["decision"]
                       for d in parsed["decisions"]])

    def test_signed_wait_not_bought(self):
        doc=dict(schema=SIGNED,observations=[dict(mint="SIGNED-MINT",
            pool="SIGNED-POOL",
            frozen_decision_before_S2=dict(master_action="WAIT",
                reference_action="WAIT_FOR_FEATURES",source_slot=25,
                at_ms=1793560000000))])
        parsed=parse_documents([("signed.json",doc)])
        self.assertEqual(len(parsed["decisions"]),2)
        self.assertEqual(parsed["cycles"],[])

    def test_integrated_summary_no_trades_from_telemetry(self):
        doc=dict(schema=INTEGRATED,log_events_retained=67,
            supported_native_SOL_graphs=2,paper_portfolio_closed_positions=0,
            financial_order_submitted=False)
        result=parse_documents([("summary.json",doc)])
        self.assertEqual(result["cycles"],[])
        self.assertEqual(len(result["summary"]),3)

    def test_zip_download_parses_without_extraction(self):
        payload=json.dumps(network_probe()).encode("utf-8")
        f=io.BytesIO()
        with zipfile.ZipFile(f,"w") as zipf:
            zipf.writestr("sample/data.json",payload)
            zipf.writestr("../unsafe.json",payload)
            zipf.writestr(".env","secret_DO_NOT_READ")
        docs=load_uploaded("download-from-actions.zip",f.getvalue())
        self.assertEqual(len(docs),1)
        self.assertEqual(len(parse_documents(docs)["projections"]),1)

    def test_local_symlink_and_unknown_schema_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"data.json").write_text(json.dumps(network_probe()),encoding="utf-8")
            (root/"unknown.json").write_text(json.dumps({"schema":"unknown",
                "secret":"API_KEY_DO_NOT_READ"}),encoding="utf-8")
            try:
                (root/"link.json").symlink_to(root/"data.json")
            except (NotImplementedError,OSError):
                pass
            docs=load_local(root)
            self.assertEqual(len(docs),1)

    def test_demo_only_on_opt_in(self):
        actual=parse_documents([])
        self.assertEqual(actual["cycles"],[])
        self.assertEqual(actual["projections"],[])
        demo=synthetic_demo()
        self.assertEqual(len(demo["cycles"]),2)
        self.assertTrue(all(x["source"]=="DÉMO SYNTHÉTIQUE"
                            for x in demo["cycles"]))

    def test_oversize_zip_refused(self):
        with self.assertRaisesRegex(ValueError,"volumineux"):
            load_uploaded("file.zip",b"x"*16_000_001)

    def test_deduplicate_same_source(self):
        one=paper_ledger()
        p=parse_documents([("dup.json",one),("dup.json",one)])
        self.assertEqual(len(p["cycles"]),1)

    def test_no_fabricated_master_gain_for_empty_ledger(self):
        doc=paper_ledger()
        doc["accounts"]["master"]["closed_trades"]=[]
        doc["policy_paired_model_net_edge_lamports"]=None
        parsed=parse_documents([("wait.json",doc)])
        self.assertFalse(parsed["cycles"])
        self.assertEqual(parsed["summary"][0]["valeur"],"Indisponible")


if __name__=="__main__":
    unittest.main()

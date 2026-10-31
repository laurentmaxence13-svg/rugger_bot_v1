"""No fabricated profits: signed-creation forward bank causal controls."""
import copy
import unittest

from bot.p3.signed_creation_forward_bank import (_select, signed_creator_asof_paper)
from tools.master_prospective_gate import _sha


def capture():
    e={"signature":"2"*88,"slot":463809741,"reception_utc_ns":1793475669308381840,
       "reception_monotonic_ns":1234567,"untrusted_initialize_log_hint":True,
       "on_chain_transaction_failed":False,"filled":False}
    return {"events":[e],"report":{"schema":"rugger-helius-program-log-forward-paper-v1",
           "events_received_unique":1,"signature_ledger_sha256":_sha({"previous":"0"*64,"event":e}),
           "financial_order_submitted":False}}


def verification(c):
    return {"schema":"rugger-mainnet-forward-captured-creation-check-v1",
        "source_log_chain_sha256":c["report"]["signature_ledger_sha256"],
        "first_phase_captured_logs":1,"status":"CAPTURE_VERIFIED_AND_RPC_INSPECTED",
        "signed_creation_candidate_transactions":1,
        "distinct_creator_claims_from_signed_transactions":1,
        "financial_order_submitted":False,
        "records":[{"signature":c["events"][0]["signature"],
                    "status":"SIGNED_OUTER_CREATION_CANDIDATE"}]}


MINT="5AWBTmZzYZ3twtKQLe1eziWw9yMcUyUiR6iRnCpXPv7f"
POOL="EwZxoy5QpQBxo13AHp9fvh11f49CanyFJXXmpSjVtpbP"
CREATOR="26H5Js9rJRQvg9wWoPZHzs8tbk1XdwfQUrGZ2Rxsk9RY"


def signed_pair():
    c=capture()
    v=verification(c)
    v["records"][0].update(
        cryptographic_signature_verified=True,slot=c["events"][0]["slot"],
        reception_utc_ns=c["events"][0]["reception_utc_ns"],
        launches=[{"creator":CREATOR,"mint":MINT,"pool":POOL}])
    return c,v


class SignedForwardBankTest(unittest.TestCase):
    def test_real_verified_creation_precedes_bank(self):
        c,v=signed_pair()
        rows,denominator=_select(c,v)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(denominator),1)
        self.assertTrue(rows[0]["cryptographic_creation"])

    def test_wrong_signature_is_refused(self):
        c,v=signed_pair()
        v["records"][0]["signature"]="6"*88
        with self.assertRaisesRegex(ValueError,"not_in_capture"):
            _select(c,v)

    def test_finalized_slot_mismatch_is_refused(self):
        c,v=signed_pair()
        v["records"][0]["slot"]+=1
        with self.assertRaisesRegex(ValueError,"identity_mismatch"):
            _select(c,v)

    def test_unsigned_creation_cannot_be_promoted(self):
        c,v=signed_pair()
        v["records"][0]["cryptographic_signature_verified"]=False
        with self.assertRaisesRegex(ValueError,"cryptographic_proof"):
            _select(c,v)

    def test_deduplicate_creator_before_source_calls(self):
        c,v=signed_pair()
        other=copy.deepcopy(c["events"][0])
        other["signature"]="3"*88
        c["events"].append(other)
        from tools.master_prospective_gate import _sha
        h="0"*64
        for e in c["events"]:h=_sha({"previous":h,"event":e})
        c["report"]["signature_ledger_sha256"]=h
        c["report"]["events_received_unique"]=2
        v["source_log_chain_sha256"]=h
        v["first_phase_captured_logs"]=2
        v["signed_creation_candidate_transactions"]=2
        r=copy.deepcopy(v["records"][0])
        r["signature"]=other["signature"]
        v["records"].append(r)
        rows,denominator=_select(c,v)
        self.assertEqual(len(rows),1)
        self.assertEqual(denominator[-1]["reason"],"duplicate_creator_mint_or_pool")

    def test_no_creation_does_not_call_rpc(self):
        c,v=signed_pair()
        v["records"][0]["status"]="VERIFIED_NON_CREATION"
        v["records"][0].pop("launches")
        v["signed_creation_candidate_transactions"]=0
        v["distinct_creator_claims_from_signed_transactions"]=0
        def forbidden(*args):raise AssertionError("RPC must not be contacted")
        out=signed_creator_asof_paper(c,v,forbidden)
        self.assertEqual(out["status"],"NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE")
        self.assertIsNone(out["master_net_pnl_lamports"])
        self.assertEqual(out["qualified_market_cycles"],0)

    def test_rpc_wrong_genesis_blocked(self):
        c,v=signed_pair()
        with self.assertRaisesRegex(ValueError,"incorrect_mainnet_genesis"):
            signed_creator_asof_paper(c,v,lambda method,params:"bad-genesis")
    
    def test_signed_creator_s1_frozen_before_s2_and_no_profit_promotion(self):
        from unittest.mock import patch
        import bot.p3.signed_creation_forward_bank as m
        from bot.p3.certification import _encode
        from bot.p3.quotes import SOL_MINT
        from bot.live.readonly_plan import MAINNET_GENESIS
        c,v=signed_pair()
        def addr(n):return _encode(bytes([n])*32)
        graph=dict(pool=POOL,config=addr(31),platform=addr(32),
                   mint_a=MINT,mint_b=SOL_MINT,vault_a=addr(33),vault_b=addr(34))
        frozen={"yes":False}
        def snap(accounts,**kw):
            if kw.get("compute_projection") is False:
                return dict(evidence_profile="published_metadata_v1",blocking_reasons=[],
                    risk_flags=[],facts=dict(pool=dict(status=0),config=dict(
                    trade_fee_rate_ppm=2500,curve_type=0),platform=dict(
                    platform_fee_rate_ppm=0,creator_fee_rate_ppm=0),
                    quote_vault=dict(amount_atomic="1000000000")))
            return dict(evidence_profile="published_metadata_v1",
                blocking_reasons=[],risk_flags=[],
                conditional_projection=dict(buy_output_atomic="200"))
        class Rpc:
            def __init__(self):self.count=0
            def __call__(self,method,params):
                self.count+=1
                if self.count==1:
                    self_test.assertEqual(method,"getGenesisHash")
                    return MAINNET_GENESIS
                self_test.assertEqual(method,"getMultipleAccounts")
                if self.count==2:return dict(context=dict(slot=463809742),
                                              value=[dict(root=1)])
                if self.count==3:return dict(context=dict(slot=463809743),
                    value=[dict(state="S1") for _ in params[0]])
                self_test.assertTrue(frozen["yes"])
                self_test.assertEqual(self.count,4)
                self_test.assertEqual(params[1]["minContextSlot"],463809744)
                return dict(context=dict(slot=463809744),
                    value=[dict(state="S2") for _ in params[0]])
        self_test=self
        def stop_before_s2(seconds):
            self.assertEqual(seconds,1)
            frozen["yes"]=True
        with (patch.object(m,"addresses_from_pool",return_value=graph),
              patch.object(m,"analyze_snapshot",side_effect=snap),
              patch.object(m,"observed_sell_projection",return_value=dict(
                 output_lamports="900000000"))):
            result=m.signed_creator_asof_paper(c,v,Rpc(),
                sleep=stop_before_s2,clock_ms=lambda:1793475669400,
                delay_seconds=1)
        self.assertEqual(result["status"],
            "TWO_CLOCK_MODEL_CAPTURE_COMPLETE_NOT_PROFITABILITY")
        row=result["observations"][0]
        self.assertTrue(result["freeze_completed_before_S2"])
        self.assertEqual(row["frozen_decision_before_S2"]["reference_action"],
            "WAIT_FOR_FEATURES")
        self.assertNotEqual(row["frozen_decision_before_S2"]["master_action"],"ENTER")
        self.assertEqual(row["s1_to_s2_conditional_curve_markout_lamports"],
            "-100000000")
        self.assertIsNone(result["master_net_pnl_lamports"])
        self.assertIsNone(result["comparative_master_edge_lamports"])
        self.assertFalse(result["promotion_allowed"])

    def test_master_missing_features_is_actual_blocking_policy(self):
        from bot.master_decision import MasterDecisionOrchestrator
        from tools.master_prospective_gate import _sha
        at=1793475669309
        frame=dict(id="unknown-s1-"+_sha([MINT,at]),mint=MINT,pool=POOL,
            creator=CREATOR,detected_at_ms=at-1000,
            available_at_ms=at,source_slot=463809850,
            slot_available_at_ms=at,data_kind="market_observation",
            features=None,features_available_at_ms=None,health=None,
            independent_buyers=None,bank_state=None)
        result=MasterDecisionOrchestrator().evaluate(frame,[],inventory=None,
            health=None,capital=None)
        self.assertNotEqual(result["action"],"ENTER")
        self.assertIn("features_unknown",result["reasons"])

    def test_no_sleep_for_empty_cohort(self):
        c,v=signed_pair()
        v["records"][0]["status"]="VERIFIED_NON_CREATION"
        v["records"][0].pop("launches")
        v["signed_creation_candidate_transactions"]=0
        v["distinct_creator_claims_from_signed_transactions"]=0
        def forbidden(*args):raise AssertionError("should never run")
        signed_creator_asof_paper(c,v,forbidden,sleep=forbidden)


if __name__=="__main__":
    unittest.main()

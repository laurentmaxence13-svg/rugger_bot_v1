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

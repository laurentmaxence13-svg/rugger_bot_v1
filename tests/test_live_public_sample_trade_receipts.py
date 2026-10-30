"""No-network historical sample receipt verification contract."""
import pytest
from bot.live import public_sample_trade_receipts as mod
from bot.live.readonly_plan import MAINNET_GENESIS


class Fake:
    def __init__(self,bad=False,wrong_chain=False):
        self.calls=[]
        self.bad=bad
        self.wrong_chain=wrong_chain
    def __call__(self,method,params):
        self.calls.append(method)
        if method=="getGenesisHash":
            return "wrong" if self.wrong_chain else MAINNET_GENESIS
        assert method=="getTransaction"
        assert params[1]==mod.OPTIONS
        for sample in mod.SAMPLES:
            for side in ("buy","sell"):
                if params[0]==sample[side+"_sig"]:
                    return dict(slot=sample[side+"_slot"],
                        meta=dict(err=None),transaction=dict(
                            signatures=[params[0]],message=dict(
                                accountKeys=[],header=dict(
                                    numRequiredSignatures=1))))
        raise AssertionError("unbounded_signature")


def test_no_mainnet_genesis_no_signed_transaction_request():
    fake=Fake(wrong_chain=True)
    with pytest.raises(ValueError,match="genesis"):
        mod.verify_public_sample_receipts(fake)
    assert fake.calls==["getGenesisHash"]


def test_wrong_source_signature_identity_never_qualifies():
    fake=Fake()
    with pytest.raises(ValueError,match="missing"):
        # Simulated Ed25519 verifies, but normalized keys omit claimed
        # public pool and signed payer: fail closed.
        from unittest.mock import patch
        with patch.object(mod,"verify_compiled_rpc_signatures",
                return_value=dict(cryptographic_signatures_verified=True,
                                  exact_message_sha256="a"*64)):
            with patch.object(mod,"normalized_compiled_transaction",
                    return_value=dict(transaction=dict(message=dict(
                        accountKeys=[])))):
                mod.verify_public_sample_receipts(fake)
    assert fake.calls==["getGenesisHash","getTransaction"]


def test_missing_historical_transaction_is_not_a_finished_cycle():
    class Missing(Fake):
        def __call__(self,method,params):
            if method=="getGenesisHash":return MAINNET_GENESIS
            return None
    with pytest.raises(ValueError,match="mismatch"):
        mod.verify_public_sample_receipts(Missing())


def test_only_two_pinned_chronological_pairs_not_a_holdout():
    assert len(mod.SAMPLES)==2
    assert sum(s["sampled_buy_token_atomic"]==s["sampled_sell_token_atomic"]
               for s in mod.SAMPLES)==1
    assert all(s["buy_slot"]<s["sell_slot"] for s in mod.SAMPLES)

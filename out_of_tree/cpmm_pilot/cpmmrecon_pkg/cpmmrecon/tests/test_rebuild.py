"""cpmmrecon 0.1: synthetic transactions (every refusal path) and REAL pre-T0 transactions of the 3 N1 / G2-3 pilot
pools (A2r pages, R03 ecd1098: the truncated ones and their neighbours, sha checked)."""
import hashlib
import json
import struct
from pathlib import Path

import pytest

from cpmmcost import model as CC
from cpmmpilot.store import read_gz_page
from cpmmrecon import rebuild as RB
from cpmmx import curve, events, timeline as TL
from cpmmx.tests.test_cpmmx import BASE_B58, POOL_B58, Sim, logs, tx

FEES = curve.Fees(2_500, 0, 120_000, 40_000)
WV, BV, AUTH, CPMM, TOKEN = 'WsolVault', 'BaseVault', 'Authority', events.CPMM_PROGRAM, 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
KEYS = ['Payer', POOL_B58, WV, BV, CPMM, TOKEN, AUTH, 'UserW', 'UserB', 'Aggregator']
IX = {k: i for i, k in enumerate(KEYS)}


def _ix(program, accounts, data, height=None):
    out = dict(programIdIndex=IX[program], accounts=[IX[a] for a in accounts], data=events.b58encode(data))
    if height is not None:
        out['stackHeight'] = height
    return out


def _transfer(src, dst, amount, height, checked=True):
    if checked:
        return _ix(TOKEN, [src, 'Mint', dst, AUTH] if 'Mint' in IX else [src, src, dst, AUTH],
                   bytes([12]) + struct.pack('<Q', amount) + bytes([9]), height)
    return _ix(TOKEN, [src, dst, AUTH], bytes([3]) + struct.pack('<Q', amount), height)


class Market:
    """A pool, its vault balances, and raw transactions: decoded swaps or log-truncated swaps with instructions."""

    def __init__(self):
        self.sim = Sim(10 ** 15, 100 * 10 ** 9, FEES, True)
        self.bal = {WV: 100 * 10 ** 9, BV: 10 ** 15}
        self.txs, self.n = {}, 0

    def _balances(self, before, after):
        rows = lambda b: [dict(accountIndex=IX[v], mint=(TL.WSOL if v == WV else BASE_B58), owner=AUTH,
                               uiTokenAmount=dict(amount=str(b[v]))) for v in (WV, BV)]
        return rows(before), rows(after)

    def swap(self, side, amount, *, truncated=False, exact_in=True, swaps=1, extra=None, err=None, height=True,
             tamper=0, checked=True, donation=0):
        sig, slot = 'sig%03d' % self.n, 1000 + 3 * self.n
        before, lines, children, tops = dict(self.bal), [], [], []
        for k in range(swaps):
            payload, got = self.sim.swap(side, amount, exact_in=exact_in)
            lines += logs(payload)
            vin, vout = (WV, BV) if side == 'buy' else (BV, WV)
            uin, uout = ('UserW', 'UserB') if side == 'buy' else ('UserB', 'UserW')
            self.bal[vin] += got.input_amount
            self.bal[vout] -= got.output_amount
            data = RB._disc('swap_base_input' if exact_in else 'swap_base_output') + bytes(16)
            children += [_ix(CPMM, ['Payer', AUTH, 'Aggregator', POOL_B58, WV, BV], data, 2 if height else None),
                         _transfer(uin, vin, got.input_amount, 3 if height else None, checked),
                         _transfer(vout, uout, got.output_amount + (tamper if k == 0 else 0), 3 if height else None,
                                   checked)]
        if tamper:
            self.bal[vout] -= tamper
        after = dict(self.bal, **{WV: self.bal[WV] + donation})            # a direct deposit, not a swap transfer
        children += extra or []
        raw = tx(slot, self.n, lines, when=slot, err=err)
        if truncated:
            pre, post = self._balances(before, after)
            raw['meta'].update(logMessages=['Program %s invoke [1]' % CPMM, 'Log truncated'], preTokenBalances=pre,
                               postTokenBalances=post, innerInstructions=[dict(index=0, instructions=children)],
                               loadedAddresses=dict(writable=[], readonly=[]))
            raw['transaction'] = dict(signatures=[sig], message=dict(accountKeys=KEYS, instructions=[
                _ix('Aggregator', ['Payer'], b'\x01', 1)]))
        self.txs[sig] = raw
        self.n += 1
        return sig

    def line(self):
        return TL.build(POOL_B58, self.txs, base_mint=BASE_B58)


def _rebuild(m):
    line = m.line()
    return line, *RB.rebuild(line, m.txs, wsol_vault=WV, fees=FEES, on_input=True)


def test_a_truncated_swap_is_rebuilt_exactly_and_the_chain_closes():
    m = Market()
    for i in range(6):
        m.swap('buy' if i % 2 else 'sell', 10 ** 8 if i % 2 else 10 ** 12, truncated=(i == 3))
    line, new, rep = _rebuild(m)
    assert line.skipped == (('sig003', 'log_truncated'),) and rep == {'sig003': 'rebuilt:1'}
    assert new.skipped == () and len(new.swaps) == 6
    gate = CC.pool_gate(new, dict(trade_fee_rate=2_500, protocol_fee_rate=120_000, fund_fee_rate=40_000,
                                  sha256='ab' * 32, slot=1))
    assert gate['admitted'] is True and gate['continuity_breaks'] == 0 and gate['exact'] == 6
    full = Market()
    for i in range(6):
        full.swap('buy' if i % 2 else 'sell', 10 ** 8 if i % 2 else 10 ** 12)
    assert [s.event for s in new.swaps] == [s.event for s in full.line().swaps]           # the true events


def test_several_swaps_in_one_transaction_and_exact_output():
    m = Market()
    m.swap('sell', 10 ** 12)
    m.swap('buy', 10 ** 8, truncated=True, swaps=3)
    m.swap('sell', 10 ** 8, truncated=True, exact_in=False)
    m.swap('buy', 10 ** 8)
    line, new, rep = _rebuild(m)
    assert rep == {'sig001': 'rebuilt:3', 'sig002': 'rebuilt:1'} and new.skipped == ()
    assert [s.order for s in new.swaps if s.signature == 'sig001'] == [0, 1, 2]
    assert [s.event.base_input for s in new.swaps if s.signature == 'sig002'] == [False]
    assert all(s.depth == 2 for s in new.swaps if s.signature in ('sig001', 'sig002'))
    assert TL.continuity(new, 120_000, 40_000) == []


def test_every_refusal_keeps_the_transaction_undecoded():
    cases = {
        'kept:other_cpmm_instruction_on_the_pool': dict(extra=[_ix(CPMM, [POOL_B58], RB._disc('deposit'), 2)]),
        'kept:transfers_differ_from_the_vault_balances': dict(donation=5),
        'kept:swap_transfers_not_identified': dict(extra=[]),          # replaced below: two transfers in
        'kept:inner_instruction_without_stack_height': dict(height=False),
        'kept:amounts_not_reproduced': dict(tamper=1),
    }
    for want, kw in cases.items():
        m = Market()
        m.swap('sell', 10 ** 12)
        sig = m.swap('buy', 10 ** 8, truncated=True, **kw)
        if want == 'kept:swap_transfers_not_identified':
            inner = m.txs[sig]['meta']['innerInstructions'][0]['instructions']
            inner.insert(2, _transfer('UserW', WV, 0, 3))
        m.swap('sell', 10 ** 12)
        line, new, rep = _rebuild(m)
        assert rep == {sig: want}, (want, rep)
        assert new.skipped == line.skipped and new.swaps == line.swaps


def test_a_failed_transaction_is_never_rebuilt():
    m = Market()
    m.swap('sell', 10 ** 12)
    sig = m.swap('buy', 10 ** 8, truncated=True)
    m.txs[sig]['meta']['err'] = {'InstructionError': [0, 'x']}
    line = m.line()                                       # cpmmx leaves a failed transaction out of the line
    assert line.skipped == ()
    forced = TL.Timeline(line.pool, line.base_mint, line.quote_mint, line.swaps, line.lp_changes,
                         ((sig, 'log_truncated'),))
    assert RB.rebuild(forced, m.txs, wsol_vault=WV, fees=FEES, on_input=True)[1] == {sig: 'kept:failed_transaction'}


def test_no_state_before_and_other_causes_are_kept():
    m = Market()
    first = m.swap('buy', 10 ** 8, truncated=True)                      # nothing before it
    m.swap('sell', 10 ** 12)
    line, new, rep = _rebuild(m)
    assert rep == {first: 'kept:no_state_before'} and new.skipped == line.skipped
    fake = TL.Timeline(line.pool, line.base_mint, line.quote_mint, line.swaps, line.lp_changes,
                       ((first, 'legacy_swap_event_without_mints'),))
    assert RB.rebuild(fake, m.txs, wsol_vault=WV, fees=FEES, on_input=True)[1] == {
        first: 'kept:legacy_swap_event_without_mints'}
    lp = TL.Timeline(line.pool, line.base_mint, line.quote_mint, line.swaps, ((900, 0, 0, None),), line.skipped)
    m2 = Market()
    m2.swap('sell', 10 ** 12)
    s2 = m2.swap('buy', 10 ** 8, truncated=True)
    l2 = m2.line()
    l2 = TL.Timeline(l2.pool, l2.base_mint, l2.quote_mint, l2.swaps, ((l2.swaps[0].slot, 5, 0, None),), l2.skipped)
    assert RB.rebuild(l2, m2.txs, wsol_vault=WV, fees=FEES, on_input=True)[1] == {s2: 'kept:no_state_before'}
    assert lp.lp_changes


def test_vault_identification_and_plain_transfers():
    m = Market()
    m.swap('sell', 10 ** 12)
    sig = m.swap('buy', 10 ** 8, truncated=True, checked=False)
    m.swap('sell', 10 ** 12)
    assert RB.vaults(m.txs[sig], WV, BASE_B58) == {WV: TL.WSOL, BV: BASE_B58}
    assert _rebuild(m)[2] == {sig: 'rebuilt:1'}
    with pytest.raises(RB.ReconError, match='wsol_vault_not_in'):
        RB.vaults(m.txs[sig], 'Other', BASE_B58)
    with pytest.raises(RB.ReconError, match='base_vault_not_identified'):
        RB.vaults(m.txs[sig], WV, 'OtherMint')
    assert RB.b58decode(events.b58encode(b'\0\0abc')) == b'\0\0abc'
    no_swap = dict(m.txs[sig])
    no_swap['meta'] = dict(no_swap['meta'], innerInstructions=[])
    with pytest.raises(RB.ReconError, match='no_swap_on_the_pool'):
        RB.pool_swaps(no_swap, POOL_B58, RB.vaults(m.txs[sig], WV, BASE_B58))


# -- real pre-T0 transactions --------------------------------------------------------------------------------------
_REAL = Path(__file__).parent / 'data_real'


def test_real_truncated_pre_t0_swaps_of_the_three_pilot_pools_are_rebuilt_and_close_the_chain():
    meta = json.loads((_REAL / 'META.json').read_text())
    cfg = dict(meta['amm_config'], sha256=meta['amm_config']['raw_sha256'])
    fees = CC.fees_from_amm_config(cfg)
    assert fees.creator_fee_rate == 0                                    # flag 0, anchored 6c3ed74
    total = multi = 0
    for pool, m in sorted(meta['pools'].items()):
        page = _REAL / pool / 'page_00000.json.gz'
        assert hashlib.sha256(page.read_bytes()).hexdigest() == m['page_sha256']
        txs = {t['transaction']['signatures'][0]: t for t in read_gz_page(page)['data']}
        line = TL.build(pool, txs, base_mint=m['base_mint'])
        assert set(m['chosen']) <= {s for s, _w in line.skipped} and {w for _s, w in line.skipped} == {'log_truncated'}
        side = CC.creator_side(line, len(line.swaps) - 1)
        new, rep = RB.rebuild(line, txs, wsol_vault=m['wsol_vault'], fees=fees, on_input=side)
        assert new.skipped == () and all(r.startswith('rebuilt:') for r in rep.values()) and len(rep) == len(line.skipped)
        multi += sum(1 for r in rep.values() if r != 'rebuilt:1')
        # every rebuilt transaction is followed by a logged swap whose reserves equal the rebuilt ones
        swaps = list(new.swaps)
        for k, s in enumerate(swaps[:-1]):
            if s.signature in rep and swaps[k + 1].signature not in rep:
                after = TL.after_swap(s, fees.protocol_fee_rate, fees.fund_fee_rate)
                assert after == (swaps[k + 1].base_before, swaps[k + 1].quote_before)
        rebuilt = [s for s in new.swaps if s.signature in rep]
        assert TL.reproduce(TL.Timeline(pool, line.base_mint, line.quote_mint, tuple(rebuilt), (), ()),
                            {k: (fees, side) for k in ('buy', 'sell')})['exact'] == len(rebuilt)
        total += len(rep)
    assert total >= 64 and multi == 1                                     # incl. the 4-swap G8kgi7 transaction


def test_exact_output_and_multi_swap_events_equal_the_true_ones():
    plan = [('sell', 10 ** 12, {}), ('buy', 10 ** 11, dict(exact_in=False)), ('buy', 10 ** 8, dict(swaps=3)),
            ('sell', 10 ** 8, dict(exact_in=False)), ('buy', 10 ** 8, {})]        # 10**11 base out: input rounded up
    m, full = Market(), Market()
    for side, amount, kw in plan:
        m.swap(side, amount, truncated=bool(kw), **kw)
        full.swap(side, amount, **kw)
    _line, new, _rep = _rebuild(m)
    assert [s.event for s in new.swaps] == [s.event for s in full.line().swaps]
    assert TL.reproduce(new, {k: (FEES, True) for k in ('buy', 'sell')})['exact'] == len(new.swaps)


def test_a_grandchild_transfer_is_not_a_swap_transfer():
    m = Market()
    m.swap('sell', 10 ** 12)
    sig = m.swap('buy', 10 ** 8, truncated=True)
    m.txs[sig]['meta']['innerInstructions'][0]['instructions'].insert(2, _transfer('UserW', WV, 0, 4))
    m.swap('sell', 10 ** 12)
    assert _rebuild(m)[2] == {sig: 'rebuilt:1'}


def test_after_a_failed_rebuild_the_next_one_has_no_state():
    m = Market()
    m.swap('sell', 10 ** 12)
    bad = m.swap('buy', 10 ** 8, truncated=True, tamper=1)
    nxt = m.swap('buy', 10 ** 8, truncated=True)
    m.swap('sell', 10 ** 12)
    assert _rebuild(m)[2] == {bad: 'kept:amounts_not_reproduced', nxt: 'kept:no_state_before'}

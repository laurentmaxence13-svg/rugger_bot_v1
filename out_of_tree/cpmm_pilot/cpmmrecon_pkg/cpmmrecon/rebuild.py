"""cpmmrecon 0.1 -- COMPLEMENTARY DECODER of the CPMM swaps whose log is truncated ('Log truncated', so cpmmx cannot read
the event), voie (ii) of R02 (12:20Z) / decision R04-14. cpmmx and cpmmcost are untouched; G-0 is unchanged: the
rebuilt line is judged by cpmmcost.pool_gate as any other (exact reproduction, no reserves break).

FOR EACH UNDECODED TRANSACTION of the pool (reason log_truncated, transaction not failed):
  1. the swaps on the pool are the CPMM instructions (Anchor discriminators swap_base_input / swap_base_output) whose
     accounts include the pool, in execution order (top-level instruction, then its inner instructions); ANY other CPMM
     instruction on the pool (deposit, withdraw, ...) leaves the transaction undecoded;
  2. the amounts of each swap are the token transfers it makes (its children, stack height + 1): exactly one transfer
     INTO a pool vault (the input) and one OUT OF the other vault (the output), Token transfer / transferChecked only;
  3. the transfers of all the pool's swaps must equal the vaults' pre/post token balance changes (cross-check);
  4. the reserves before are those after the previous swap of the pool (logged or rebuilt) -- none after an LP event:
     the transaction then stays undecoded;
  5. the swap is recomputed by cpmmx.curve with the AmmConfig rates (cpmmcost 0.3.1: creator rate of the pool) in the
     mode of its instruction; the recomputed amounts must equal the transferred ones EXACTLY, else undecoded.
A transaction is rebuilt whole or not at all. Nothing is guessed: whatever fails a check stays in ``skipped``.
"""
import hashlib
import struct
from dataclasses import replace

from cpmmx import curve, events as EV, timeline as TL

TOKEN_PROGRAMS = frozenset({'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'})
TRANSFER, TRANSFER_CHECKED = 3, 12
REBUILT_CAUSE = 'log_truncated'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class ReconError(ValueError):
    pass


def _disc(name):
    return hashlib.sha256(('global:' + name).encode()).digest()[:8]


SWAP_MODES = {_disc('swap_base_input'): True, _disc('swap_base_output'): False}      # True: exact input


def b58decode(text):
    number = 0
    for c in text:
        number = number * 58 + _B58.index(c)
    body = number.to_bytes((number.bit_length() + 7) // 8, 'big') if number else b''
    return b'\0' * (len(text) - len(text.lstrip('1'))) + body


def account_keys(tx):
    message, meta = tx['transaction']['message'], tx.get('meta') or {}
    keys = [k if isinstance(k, str) else k['pubkey'] for k in message.get('accountKeys') or []]
    loaded = meta.get('loadedAddresses') or {}
    return keys + list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])


def _flat(tx):
    """(top index, stack height, instruction) in execution order."""
    inner = {group['index']: group['instructions'] for group in (tx.get('meta') or {}).get('innerInstructions') or []}
    for k, ix in enumerate(tx['transaction']['message']['instructions']):
        yield k, ix.get('stackHeight') or 1, ix
        for child in inner.get(k, ()):
            if child.get('stackHeight') is None:
                raise ReconError('inner_instruction_without_stack_height')
            yield k, child['stackHeight'], child


def vaults(tx, wsol_vault, base_mint):
    """{vault address: mint} of the pool: the WSOL vault and the base-mint account of the same owner (the authority)."""
    keys, meta = account_keys(tx), tx.get('meta') or {}
    balances = list(meta.get('preTokenBalances') or []) + list(meta.get('postTokenBalances') or [])
    owners = {b.get('owner') for b in balances if keys[b['accountIndex']] == wsol_vault}
    if len(owners) != 1:
        raise ReconError('wsol_vault_not_in_the_token_balances')
    owner = owners.pop()
    base = {keys[b['accountIndex']] for b in balances if b['mint'] == base_mint and b.get('owner') == owner}
    if len(base) != 1:
        raise ReconError('base_vault_not_identified')
    return {wsol_vault: TL.WSOL, base.pop(): base_mint}


def _balance_changes(tx, vault_set):
    keys, meta = account_keys(tx), tx['meta']
    def amounts(side):
        return {keys[b['accountIndex']]: int(b['uiTokenAmount']['amount']) for b in meta.get(side) or []
                if keys[b['accountIndex']] in vault_set}
    pre, post = amounts('preTokenBalances'), amounts('postTokenBalances')
    return {v: post.get(v, 0) - pre.get(v, 0) for v in vault_set}


def pool_swaps(tx, pool, vault_mints):
    """[(exact_input, depth, input vault, amount in, output vault, amount out)] of the pool's swaps, in order."""
    keys = account_keys(tx)
    seq = list(_flat(tx))
    found = []
    for n, (top, height, ix) in enumerate(seq):
        if keys[ix['programIdIndex']] != EV.CPMM_PROGRAM or pool not in [keys[i] for i in ix['accounts']]:
            continue
        mode = SWAP_MODES.get(b58decode(ix['data'])[:8])
        if mode is None:
            raise ReconError('other_cpmm_instruction_on_the_pool')
        ins, outs = [], []
        for top2, h2, child in seq[n + 1:]:
            if top2 != top or h2 <= height:
                break
            if h2 != height + 1 or keys[child['programIdIndex']] not in TOKEN_PROGRAMS:
                continue
            data = b58decode(child['data'])
            accts = [keys[i] for i in child['accounts']]
            if data[0] == TRANSFER:
                src, dst = accts[0], accts[1]
            elif data[0] == TRANSFER_CHECKED:
                src, dst = accts[0], accts[2]
            else:
                continue
            amount = struct.unpack_from('<Q', data, 1)[0]
            if dst in vault_mints:
                ins.append((dst, amount))
            if src in vault_mints:
                outs.append((src, amount))
        if len(ins) != 1 or len(outs) != 1 or ins[0][0] == outs[0][0]:
            raise ReconError('swap_transfers_not_identified')
        found.append((mode, height, ins[0][0], ins[0][1], outs[0][0], outs[0][1]))
    if not found:
        raise ReconError('no_swap_on_the_pool')
    changes = _balance_changes(tx, set(vault_mints))
    net = {v: 0 for v in vault_mints}
    for _m, _h, vin, a_in, vout, a_out in found:
        net[vin] += a_in
        net[vout] -= a_out
    if net != changes:
        raise ReconError('transfers_differ_from_the_vault_balances')
    return found


def _rebuild_one(line, sig, tx, planned, reserves, fees, on_input, vault_mints):
    """The Swap objects of one transaction, chained from ``reserves`` = (base, quote); ReconError if inexact."""
    out = []
    for order, (exact_in, depth, vin, a_in, vout, a_out) in enumerate(planned):
        base, quote = reserves
        buy = vault_mints[vin] == line.quote_mint
        iv, ov = (quote, base) if buy else (base, quote)
        try:
            got = (curve.swap_base_input(a_in, iv, ov, fees, on_input) if exact_in
                   else curve.swap_base_output(a_out, iv, ov, fees, on_input))
        except curve.CurveError as exc:
            raise ReconError('curve:%s' % exc)
        if (got.input_amount, got.output_amount) != (a_in, a_out):
            raise ReconError('amounts_not_reproduced')
        event = EV.SwapEvent(line.pool, iv, ov, a_in, a_out, 0, 0, exact_in, vault_mints[vin], vault_mints[vout],
                             got.trade_fee, got.creator_fee, got.creator_fee_on_input)
        out.append(TL.Swap(sig, tx['slot'], tx['blockTime'], tx['transactionIndex'], order, 'buy' if buy else 'sell',
                           base, quote, event, depth))
        new_in, new_out = curve.reserves_after(iv, ov, got)
        reserves = (new_out, new_in) if buy else (new_in, new_out)
    return out, reserves


def rebuild(line, txs, *, wsol_vault, fees, on_input):
    """(rebuilt line, report). Only 'log_truncated' transactions are tried; the others stay as they are."""
    report, plans = {}, {}
    for sig, why in line.skipped:
        if why != REBUILT_CAUSE:
            report[sig] = 'kept:%s' % why
            continue
        tx = txs[sig]
        if (tx.get('meta') or {}).get('err') is not None:
            report[sig] = 'kept:failed_transaction'
            continue
        try:
            vm = vaults(tx, wsol_vault, line.base_mint)
            plans[sig] = (vm, pool_swaps(tx, line.pool, vm))
        except ReconError as exc:
            report[sig] = 'kept:%s' % exc
    items = [(s.key, 'swap', s) for s in line.swaps] + [(r[:3], 'lp', r) for r in line.lp_changes]
    items += [((txs[sig]['slot'], txs[sig]['transactionIndex'], -1), 'plan', sig) for sig in plans]
    items.sort(key=lambda row: row[0])
    rebuilt, reserves = [], None
    for _key, kind, obj in items:
        if kind == 'swap':
            reserves = TL.after_swap(obj, fees.protocol_fee_rate, fees.fund_fee_rate)
        elif kind == 'lp':
            reserves = None
        elif reserves is None:
            report[obj] = 'kept:no_state_before'
        else:
            vm, planned = plans[obj]
            try:
                swaps, reserves = _rebuild_one(line, obj, txs[obj], planned, reserves, fees, on_input, vm)
            except ReconError as exc:
                report[obj] = 'kept:%s' % exc
                reserves = None
            else:
                rebuilt += swaps
                report[obj] = 'rebuilt:%d' % len(swaps)
    done = {sig for sig, r in report.items() if r.startswith('rebuilt')}
    new = replace(line, swaps=tuple(sorted(line.swaps + tuple(rebuilt), key=lambda s: s.key)),
                  skipped=tuple((sig, why) for sig, why in line.skipped if sig not in done))
    return new, dict(sorted(report.items()))

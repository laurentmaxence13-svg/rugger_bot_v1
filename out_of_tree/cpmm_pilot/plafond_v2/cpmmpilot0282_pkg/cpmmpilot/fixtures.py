"""Deterministic SYNTHETIC chain for the rehearsal (no real address, no real transaction): AmmConfigs, CPMM pools,
WSOL vaults, creation transactions and swaps whose SwapEvents are computed with the frozen cpmmx.curve arithmetic,
so that the frozen decoder, timeline and cost model read them exactly as real ones."""
import base64
import hashlib
import random
import struct

from cpmmx import curve
from cpmmx.events import CPMM_PROGRAM, SWAP_DISCRIMINATOR

from . import layout as L
from .rpc import FakeChain
from .u2 import LAUNCHLAB_PROGRAM

TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
DAY = 86_400
SLOT_S = 0.4


def _key(rng):
    while True:
        raw = bytes(rng.getrandbits(8) for _ in range(32))
        if raw[0]:
            return L.b58encode(raw)


def config_account(index, trade_fee_rate):
    data = bytearray(L.CONFIG_ACCOUNT_SIZE)
    data[:8] = L.CONFIG_DISCRIMINATOR
    data[8], data[9] = 255, 0
    struct.pack_into('<H', data, 10, index)
    struct.pack_into('<Q', data, 12, trade_fee_rate)
    return bytes(data)


def pool_account(keys, *, status=0, lp_supply=10 ** 12):
    data = bytearray(L.POOL_ACCOUNT_SIZE)
    data[:8] = L.POOL_DISCRIMINATOR
    for i, k in enumerate(L.POOL_KEYS):
        data[8 + i * 32:40 + i * 32] = L.b58decode(keys[k])
    data[329] = status
    struct.pack_into('<Q', data, 333, lp_supply)
    return bytes(data)


def token_account(mint, amount):
    data = bytearray(165)
    data[:32] = L.b58decode(mint)
    struct.pack_into('<Q', data, 64, amount)
    return bytes(data)


def _tx(sig, slot, index, when, logs, err=None):
    return dict(slot=slot, transactionIndex=index, blockTime=when, version=0,
                meta=dict(err=err, logMessages=logs), transaction=dict(signatures=[sig], message={}))


def swap_payload(pool, in_before, out_before, res, mint_in, mint_out):
    head = struct.pack('<32s6Q?', L.b58decode(pool), in_before, out_before, res.input_amount, res.output_amount,
                       0, 0, True)
    tail = struct.pack('<32s32s2Q?', L.b58decode(mint_in), L.b58decode(mint_out), res.trade_fee, res.creator_fee,
                       res.creator_fee_on_input)
    return SWAP_DISCRIMINATOR + head + tail


def build(*, seed=20261123, n_pools=40, t0_time=1_795_000_000, t0_slot=400_000_000, window_days=2,
          swaps_per_day=200, gtfa_refused=False, truncate=False, specials=True):
    """Returns (FakeChain, spec). Pools 0..5 are the exclusion cases when ``specials`` (status 4, lp 0, Token-2022,
    small reserve, LaunchLab creation, younger than 7 days); the others are valid candidates."""
    rng = random.Random(seed)
    accounts, history, spec = {}, {}, dict(pools=[], seed=seed)
    cfg0, cfg1 = L.config_pda(0), L.config_pda(1)
    accounts[cfg0] = dict(owner=CPMM_PROGRAM, data=config_account(0, 2_500))
    accounts[cfg1] = dict(owner=CPMM_PROGRAM, data=config_account(1, 10_000))
    fees = curve.Fees(2_500)
    end_time = t0_time + window_days * DAY
    for k in range(n_pools):
        pool, base = _key(rng), _key(rng)
        wsol_first = k % 2 == 0
        mint0, mint1 = (L.WSOL, base) if wsol_first else (base, L.WSOL)
        keys = dict(amm_config=cfg0 if k != n_pools - 1 else cfg1, pool_creator=_key(rng),
                    token_0_vault=L.vault_pda(pool, mint0), token_1_vault=L.vault_pda(pool, mint1),
                    lp_mint=_key(rng), token_0_mint=mint0, token_1_mint=mint1, token_0_program=TOKEN,
                    token_1_program=TOKEN, observation_key=_key(rng))
        kind = ('status4', 'lp0', 'token2022', 'small', 'launchlab', 'young')[k] if specials and k < 6 else 'valid'
        if kind == 'token2022':
            keys['token_1_program'] = L.TOKEN_2022
        accounts[pool] = dict(owner=CPMM_PROGRAM, data=pool_account(
            keys, status=4 if kind == 'status4' else 0, lp_supply=0 if kind == 'lp0' else 10 ** 12))
        quote = (40 if kind == 'small' else rng.randint(120, 900)) * 10 ** 9
        basev = rng.randint(10 ** 14, 10 ** 15)
        accounts[L.vault_pda(pool, L.WSOL)] = dict(owner=TOKEN, data=token_account(L.WSOL, quote))
        accounts[L.vault_pda(pool, base)] = dict(owner=TOKEN, data=token_account(base, basev))
        created = t0_time - (3 * DAY if kind == 'young' else rng.randint(10, 60) * DAY)
        cslot = t0_slot - int((t0_time - created) / SLOT_S)
        if kind == 'launchlab':
            logs = ['Program %s invoke [1]' % LAUNCHLAB_PROGRAM, 'Program %s invoke [2]' % CPMM_PROGRAM,
                    'Program log: Instruction: Initialize', 'Program %s success' % CPMM_PROGRAM,
                    'Program %s success' % LAUNCHLAB_PROGRAM]
        else:
            logs = ['Program %s invoke [1]' % CPMM_PROGRAM, 'Program log: Instruction: Initialize',
                    'Program %s success' % CPMM_PROGRAM]
        txs = [_tx(hashlib.sha256(b'create' + pool.encode()).hexdigest(), cslot, 0, created, logs)]
        # swaps from T0 - 8 d to T0 + window: steady flow plus bursts (>= 20 swaps in 600 s) with +-4 % moves
        t, rq, rb = max(t0_time - 8 * DAY, created + 3600), quote, basev
        n = 0
        while t < end_time:
            burst = rng.random() < 0.02
            for _ in range(25 if burst else 1):
                buy = rng.random() < (0.2 if burst and n % 2 else 0.5)
                if buy:
                    amount = rng.randint(1, 3) * 10 ** 8 * (6 if burst else 1)
                    res = curve.swap_base_input(amount, rq, rb, fees, True)
                    payload = swap_payload(pool, rq, rb, res, L.WSOL, base)
                    rq, rb = rq + res.input_amount, rb - res.output_amount
                else:
                    amount = rb // (2000 // (6 if burst else 1))
                    res = curve.swap_base_input(amount, rb, rq, fees, True)
                    payload = swap_payload(pool, rb, rq, res, base, L.WSOL)
                    rb, rq = rb + res.input_amount, rq - res.output_amount
                slot = t0_slot + int((t - t0_time) / SLOT_S)
                logs = ['Program %s invoke [1]' % CPMM_PROGRAM, 'Program log: Instruction: SwapBaseInput',
                        'Program data: ' + base64.b64encode(payload).decode(), 'Program %s success' % CPMM_PROGRAM]
                txs.append(_tx(hashlib.sha256(b'swap%d' % n + pool.encode()).hexdigest(), slot, n % 50, int(t), logs))
                n += 1
                t += 10 if burst else 0
            t += rng.expovariate(swaps_per_day / DAY)
        history[pool] = txs
        spec['pools'].append(dict(pool=pool, kind=kind, base_mint=base, wsol_first=wsol_first, swaps=n))
    chain = FakeChain(accounts, history, slot=t0_slot + int(window_days * DAY / SLOT_S) + 10, block_time=end_time,
                      gtfa_refused=gtfa_refused, truncate_program_accounts=truncate)
    spec.update(t0_time=t0_time, t0_slot=t0_slot, window_days=window_days)
    return chain, spec

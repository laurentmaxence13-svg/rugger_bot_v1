"""P3bis (R01, déclaré à R02 avant lecture) : meta.fee réel et CloseAccount dans la même transaction que la vente, pages
pré-T0 6e27bf5 des pools nommés. Aucun rendement. python -B p3bis.py U2.json ROOT OUT_JSON"""
import hashlib
import json
import sys
from pathlib import Path

from cpmmpilot import step1 as PILOT
from g23run import run as G

START, END = 1794910886, 1795515686
LOW, HIGH = 50_000_000, 200_000_000
FROZEN_TX = 105_000
TOKEN_PROGRAMS = {'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'}
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
CLOSE_ACCOUNT = 9


def first_byte(data):
    n = 0
    for c in data:
        n = n * 58 + ALPHABET.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
    pad = len(data) - len(data.lstrip('1'))
    raw = b'\0' * pad + raw
    return raw[0] if raw else None


def closes(tx):
    m = tx['transaction']['message']
    la = tx['meta'].get('loadedAddresses') or {}
    keys = list(m['accountKeys']) + list(la.get('writable', [])) + list(la.get('readonly', []))
    ins = list(m['instructions'])
    for inner in tx['meta'].get('innerInstructions') or []:
        ins += inner['instructions']
    return sum(1 for i in ins if keys[i['programIdIndex']] in TOKEN_PROGRAMS and first_byte(i['data']) == CLOSE_ACCOUNT)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def summ(xs):
    return dict(n=len(xs), p10=pct(xs, 0.1), p50=pct(xs, 0.5), p90=pct(xs, 0.9),
                mean=sum(xs) / len(xs) if xs else None, share_at_most_frozen=(sum(x <= FROZEN_TX for x in xs) / len(xs))
                if xs else None)


def main(u2_path, root, out):
    u2 = json.loads(Path(u2_path).read_text())
    selected = {r['pool']: r for r in u2['selected'] if r['pool'] in G.POOLS}
    res = dict(window=[START, END], frozen_tx_fee=FROZEN_TX, band=[LOW, HIGH], pools={})
    for pool in G.POOLS:
        line, txs = G.window_line(pool, selected[pool]['base_mint'], Path(root) / pool, start=START, end=END)
        side = {}
        for s in line.swaps:                              # one transaction may hold several swaps: first one decides
            amt = s.event.input_amount if s.side == 'buy' else s.event.output_amount
            side.setdefault(s.signature, (s.side, LOW <= amt <= HIGH))
        fees = {k: [] for k in ('buy', 'sell', 'buy_band', 'sell_band', 'failed')}
        close = dict(sell=[], sell_band=[])
        for sig, (sd, band) in side.items():
            tx = txs[sig]
            fee = tx['meta']['fee']
            if tx['meta'].get('err') is not None:
                fees['failed'].append(fee)
                continue
            fees[sd].append(fee)
            if band:
                fees[sd + '_band'].append(fee)
            if sd == 'sell':
                n = closes(tx)
                close['sell'].append(n)
                if band:
                    close['sell_band'].append(n)
        res['pools'][pool] = dict(
            fee={k: summ(v) for k, v in fees.items()},
            close_account={k: dict(n=len(v), at_least_1=(sum(x >= 1 for x in v) / len(v)) if v else None,
                                   at_least_2=(sum(x >= 2 for x in v) / len(v)) if v else None)
                           for k, v in close.items()})
    text = json.dumps(res, indent=1, sort_keys=True) + '\n'
    Path(out).write_text(text)
    print(out, hashlib.sha256(text.encode()).hexdigest())


if __name__ == '__main__':
    main(*sys.argv[1:4])

"""Synthetic TIMELINE packs for v4sim (protocol V4 v2, C-6): generated APART, hashed, then read as files.

Stand-alone: imports the frozen curve arithmetic only (never v4sim, w1aux, v3lab or dayj). No real data:
every pool, actor, signature and amount is produced by a seeded pseudo-random generator.

  python -B gen_pack.py random <out> --pools 500 --seed 20261110
  python -B gen_pack.py stress <out> --pools 100 --seed 20261110

``random``: buys and sells of a few actors, some sales made with tokens received by transfer
            (external inventory), on curves of the real LaunchLab shape.
``stress``: after the order written in each pool entry (``our_order``), the other holders buy again,
            then EVERY one of them sells everything it holds (the case that broke the frozen engine:
            artefact L1).
"""
import argparse
import hashlib
import json
import random
from pathlib import Path

from bot.market.launchlab_curve import CurveError, CurveState, buy_exact_in, sell_exact_in

SCHEMA = 'v4-synthetic-timeline-pack-v1'
VIRTUAL_BASE, VIRTUAL_QUOTE, TOTAL_BASE_SELL = 1_073_025_605_596_382, 30_000_852_951, 793_100_000_000_000
RATES = (10_000, 12_500, 17_500, 25_000, 37_500)
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _name(rng, length=44):
    return ''.join(rng.choice(B58) for _ in range(length))


def _event(rng, pool, slot, time, actor, fill, rate):
    return dict(signature=_name(rng, 88), slot=slot, block_time=time, event_index=0, fee_payer=actor, pool=pool,
                side=fill.side, exact_in=True, pool_status=0, total_base_sell=fill.before.total_base_sell,
                virtual_base=fill.before.virtual_base, virtual_quote=fill.before.virtual_quote,
                real_base_before=fill.before.real_base, real_quote_before=fill.before.real_quote,
                real_base_after=fill.after.real_base, real_quote_after=fill.after.real_quote,
                amount_in=fill.amount_in, amount_out=fill.amount_out if fill.side == 'buy' else fill.amount_out,
                protocol_fee=fill.fee, platform_fee=0, creator_fee=0, share_fee=0)


class Pool:
    def __init__(self, rng):
        self.rng, self.pool, self.rate = rng, _name(rng), rng.choice(RATES)
        self.state = CurveState(VIRTUAL_BASE, VIRTUAL_QUOTE, 0, 0, TOTAL_BASE_SELL)
        self.slot, self.time = 400_000_000 + rng.randrange(10 ** 6), 1_790_000_000 + rng.randrange(10 ** 6)
        self.held, self.events = {}, []          # held: tokens really held (transfers included)

    def _tick(self):
        step = self.rng.choice((0, 0, 1, 1, 2, 5, 40))
        self.slot += step
        self.time += (step * 2 + 2) // 5

    def buy(self, actor, quote):
        try:
            fill = buy_exact_in(self.state, quote, self.rate)
        except CurveError:
            return False
        self._tick()
        self.events.append(_event(self.rng, self.pool, self.slot, self.time, actor, fill, self.rate))
        self.state = fill.after
        self.held[actor] = self.held.get(actor, 0) + fill.amount_out
        return True

    def sell(self, actor, tokens):
        if tokens <= 0:
            return False
        try:
            fill = sell_exact_in(self.state, tokens, self.rate)
        except CurveError:
            return False
        self._tick()
        self.events.append(_event(self.rng, self.pool, self.slot, self.time, actor, fill, self.rate))
        self.state = fill.after
        self.held[actor] -= tokens
        return True

    def transfer(self, source, target, tokens):
        """Invisible to the pool timeline: the target later sells tokens its ledger does not explain."""
        self.held[source] -= tokens
        self.held[target] = self.held.get(target, 0) + tokens


def random_pool(rng, n_events):
    pool, actors = Pool(rng), [_name(rng) for _ in range(rng.randrange(2, 7))]
    pool.buy(actors[0], rng.choice((2, 5, 20, 90)) * 10 ** 8 * rng.randrange(1, 10))
    while len(pool.events) < n_events:
        actor, roll = rng.choice(actors), rng.random()
        holders = [a for a in actors if pool.held.get(a, 0) > 0]
        if roll < 0.55 or not holders:
            pool.buy(actor, rng.randrange(10 ** 6, 3 * 10 ** 9))
        elif roll < 0.92:
            seller = rng.choice(holders)
            share = rng.choice((1, 1, 2, 4))
            pool.sell(seller, pool.held[seller] // share)
        else:
            source = rng.choice(holders)
            pool.transfer(source, rng.choice(actors), pool.held[source] // rng.choice((1, 2, 3)))
    return pool


def stress_pool(rng):
    """A few holders buy, OUR order is expected after event ``decision``, then every holder sells all."""
    pool, actors = Pool(rng), [_name(rng) for _ in range(rng.randrange(2, 6))]
    for actor in actors:
        pool.buy(actor, rng.randrange(10 ** 8, 5 * 10 ** 9))
    for _ in range(rng.randrange(0, 4)):
        pool.buy(rng.choice(actors), rng.randrange(10 ** 7, 10 ** 9))
    decision = len(pool.events) - 1
    pool.slot += 50                            # our order lands before any later event
    for _ in range(rng.randrange(2, 7)):       # later buyers get FEWER tokens once our order is in
        pool.buy(rng.choice(actors), rng.randrange(10 ** 7, 3 * 10 ** 9))
    for actor in rng.sample(actors, len(actors)):
        if rng.random() < 0.3 and pool.held.get(actor, 0) > 3:
            pool.sell(actor, pool.held[actor] // 3)
        pool.sell(actor, pool.held.get(actor, 0))
    order = dict(decision_index=decision, amount_lamports=rng.choice((50_000_000, 100_000_000, 500_000_000, 1_000_000_000)),
                 exit_after_events=len(pool.events) - 1 - decision)
    return pool, order


def write_pack(out, pools, kind, seed):
    out = Path(out)
    if out.exists():
        raise SystemExit('output_directory_already_exists')
    out.mkdir(parents=True)
    entries = []
    for pool, order in pools:
        blob = (json.dumps(dict(pool=pool.pool, events=pool.events), sort_keys=True, separators=(',', ':')) + '\n').encode()
        (out / f'{pool.pool}.json').write_bytes(blob)
        entry = dict(pool=pool.pool, file=f'{pool.pool}.json', sha256=hashlib.sha256(blob).hexdigest(),
                     events=len(pool.events), fee_rate_ppm=pool.rate)
        if order is not None:
            entry['our_order'] = order
        entries.append(entry)
    manifest = dict(schema=SCHEMA, kind=kind, seed=seed, purpose='SIMULATOR_TESTS_ONLY_NO_REAL_DATA',
                    pools=sorted(entries, key=lambda e: e['pool']))
    raw = (json.dumps(manifest, indent=1, sort_keys=True) + '\n').encode()
    (out / 'MANIFEST.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('random', 'stress'))
    parser.add_argument('out', type=Path)
    parser.add_argument('--pools', type=int, default=100)
    parser.add_argument('--seed', type=int, default=20261110)
    a = parser.parse_args(argv)
    rng = random.Random(f'{a.kind}:{a.seed}')
    if a.kind == 'random':
        pools = [(random_pool(rng, rng.randrange(8, 60)), None) for _ in range(a.pools)]
    else:
        pools = [stress_pool(rng) for _ in range(a.pools)]
    print(json.dumps(dict(kind=a.kind, pools=len(pools), seed=a.seed, manifest_sha256=write_pack(a.out, pools, a.kind, a.seed))))


if __name__ == '__main__':
    main()

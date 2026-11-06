"""Sampled read-only collection of a SOL/USDC pool for the causal SOL/USD series.

A full download of a busy SOL/USDC pool would exceed the L2 credit cap. The L1 rule
(spec T-0031 @ 1c28f76) only needs, for a decision in second B, a point published in
seconds B-4 .. B-1. So:

1. list the pool's signatures over the window (``getSignaturesForAddress``, the same
   committed listing phase as :class:`bot.market.backfill.Backfill`);
2. for each second ``g`` of a grid (every 4 s by default, 2 s optional), select the
   LAST successful signature whose ``blockTime <= g``;
3. fetch only those transactions (``getTransaction``). If the selected transaction is
   not a swap of the pool vaults, step back to the previous successful signature, at
   most ``MAX_FALLBACK`` times and never past the previous selection.

The selection depends only on the committed listing, so a resume selects the same
signatures. Caps, the spend ledger written before every send, segments, state and
manifest are those of ``Backfill``; a separate ``--out`` directory gives the SOL/USD
source its own ledger and cap. The resulting window feeds ``sol-usd-series``.
"""
import json

from bot.market.backfill import Backfill, BackfillError, _write_atomic, read_segment
from bot.market.collector import MAX_TX_VERSION, BudgetExhausted
from bot.market.sol_usd_collect import describe_filter, point_from_transaction

MAX_FALLBACK = 3
SAMPLE_SEGMENT_ROWS = 500
GRIDS = (2, 4)


def select_targets(rows, grid_seconds):
    """Indices (in ascending chain order) of the last successful row at each grid second."""
    if grid_seconds not in GRIDS:
        raise BackfillError('grid_seconds_must_be_2_or_4')
    timed = [i for i, r in enumerate(rows)
             if r.get('err') is None and type(r.get('blockTime')) is int]
    if not timed:
        return []
    first, last = rows[timed[0]]['blockTime'], rows[timed[-1]]['blockTime']
    targets, cursor = [], -1
    seconds = list(range(first, last + 1, grid_seconds))
    if seconds[-1] != last:
        seconds.append(last)          # the window's last second is always covered
    for second in seconds:
        while cursor + 1 < len(timed) and rows[timed[cursor + 1]]['blockTime'] <= second:
            cursor += 1
        if cursor >= 0 and (not targets or targets[-1] != timed[cursor]):
            targets.append(timed[cursor])
    return targets


class SampledBackfill(Backfill):
    """Listing phase, then a grid-sampled getTransaction phase (no full body download)."""

    def __init__(self, rpc, window, out, *, pool, sol_vault, usdc_vault, swap_filter,
                 grid_seconds=4, segment_pages=50, endpoint='unset', before_signature=None):
        if window.address != pool:
            raise BackfillError('window_address_is_not_the_pool')
        if grid_seconds not in GRIDS:
            raise BackfillError('grid_seconds_must_be_2_or_4')
        super().__init__(rpc, window, out, bodies='rpc', check=False,
                         segment_pages=segment_pages, endpoint=endpoint,
                         before_signature=before_signature)
        sampling = {'grid_seconds': grid_seconds, 'pool': pool, 'sol_vault': sol_vault,
                    'usdc_vault': usdc_vault, 'swap_filter': describe_filter(swap_filter)}
        if self.state.setdefault('sampling', sampling) != sampling:
            raise BackfillError('resume_sampling_parameters_differ_from_state')
        self.pool, self.sol_vault, self.usdc_vault = pool, sol_vault, usdc_vault
        self.grid_seconds, self.swap_filter = grid_seconds, swap_filter

    def _listed_ascending(self):
        rows = [r for s in self.state['segments'] if s['kind'] == 'sig'
                for r in read_segment(self.out / s['path'])]
        return list(reversed(rows))          # the listing is stored newest first

    def _is_swap(self, body, signature):
        return point_from_transaction(dict(body, signature=signature), pool=self.pool,
                                      sol_vault=self.sol_vault, usdc_vault=self.usdc_vault,
                                      swap_filter=self.swap_filter) is not None

    def _sample_phase(self):
        current = self._phase('sample')
        if current['done']:
            return
        rows = self._listed_ascending()
        targets = select_targets(rows, self.grid_seconds)
        stats = self.state.setdefault('sample_stats', {'targets': len(targets), 'fetched': 0,
                                                       'fallbacks': 0, 'no_swap_found': 0})
        done_signatures = {r['signature'] for s in self.state['segments'] if s['kind'] == 'tx'
                           for r in read_segment(self.out / s['path'])}
        start, batch = current['cursor'] or 0, []
        previous = targets[start - 1] if start else -1
        for position in range(start, len(targets)):
            index, attempts, kept = targets[position], 0, False
            while index > previous and attempts <= MAX_FALLBACK:
                row = rows[index]
                if row.get('err') is None and row['signature'] not in done_signatures:
                    body = self.rpc.call('getTransaction', [row['signature'], {
                        'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
                        'commitment': 'finalized'}])
                    stats['fetched'] += 1
                    if body is not None and self._is_swap(body, row['signature']):
                        if type(body.get('transactionIndex')) is not int and \
                                type(row.get('transactionIndex')) is int:
                            body = dict(body, transactionIndex=row['transactionIndex'])
                        batch.append(dict(body, signature=row['signature']))
                        done_signatures.add(row['signature'])
                        kept = True
                        break
                    attempts += 1
                    stats['fallbacks'] += 1
                elif row['signature'] in done_signatures:
                    kept = True
                    break
                index -= 1
            if not kept:
                stats['no_swap_found'] += 1
            previous = targets[position]
            # Small sample segments (500 bodies by default): an interruption re-fetches
            # at most one segment (R02 observation O1 on T-0033); spend stays capped.
            if len(batch) >= SAMPLE_SEGMENT_ROWS:
                self._commit('tx', batch, 'sample', position + 1, False)
                batch = []
        self._commit('tx', batch, 'sample', len(targets), True)

    def run(self):
        stop = None
        try:
            self._gsfa_phase()
            self._sample_phase()
        except BudgetExhausted as exc:
            stop = str(exc)
            budget = self.rpc.budget
            self.state['budget_used'] = {'requests': budget.used, 'credits': budget.credits}
            _write_atomic(self.out / 'state.json',
                          json.dumps(self.state, indent=1, sort_keys=True).encode())
        manifest = self.write_manifest(stop)
        manifest['sampling'] = dict(self.state['sampling'],
                                    **self.state.get('sample_stats', {}))
        _write_atomic(self.out / 'manifest.json',
                      json.dumps(manifest, indent=1, sort_keys=True).encode())
        return manifest


def plan_sample(window, costs, *, expected_tx_per_slot, grid_seconds=4, slot_ms=400,
                fallback_share=0.10):
    """Pre-run estimate (no network): listing pages + sampled getTransaction calls."""
    if grid_seconds not in GRIDS or expected_tx_per_slot <= 0:
        raise BackfillError('invalid_sample_plan')
    slots = window.slot_max - window.slot_min + 1
    seconds = slots * slot_ms // 1000
    pages = -(-int(round(slots * expected_tx_per_slot)) // 1000) or 1
    fetches = int(round(seconds / grid_seconds * (1 + fallback_share)))
    credits = pages * costs['getSignaturesForAddress'] + fetches * costs['getTransaction']
    return {'window': window.to_json(), 'slots': slots, 'seconds_estimate': seconds,
            'grid_seconds': grid_seconds, 'assumed_tx_per_slot': expected_tx_per_slot,
            'requests': {'getSignaturesForAddress': pages, 'getTransaction': fetches},
            'total_requests': pages + fetches, 'credits': credits,
            'note': 'estimate only; listing pages newer than slot_max are extra unless an '
                    'anchor signature is given'}

"""paperstream 0.5 -- OPT-IN memoization of the pure per-transaction helpers of the frozen analyser (performance only).

Measured (R01, 21/11, fixtures): the replay engine is negligible; ~100 % of the time is the frozen observer, which for
EVERY decision re-runs, over ALL the pool's past transactions, helpers whose result depends only on one transaction and
fixed arguments: ``final_decision_engine._contains_mint`` (``str(tx)``), ``classify_creator_behavior``,
``behavior_pipeline._owner_balances``, ``_is_swap`` (``str(tx).lower()``) and the ``json.dumps(tx, separators=(',', ':'))``
of ``wallet_graph_snapshot``. Within ``memoized()`` each of them is computed once per (transaction OBJECT, arguments):
- key = (helper, id(tx), arguments) and the entry keeps a strong reference to tx, served only if ``entry_tx is tx``
  (an address can never be reused while the entry lives);
- mutable results (the dicts of ``classify_creator_behavior`` and ``_owner_balances``) are returned as fresh copies;
- the JSON shim memoizes ONLY ``dumps(dict, separators=(',', ':'))`` and delegates everything else to ``json``;
- one memo per pool (``per_pool``): nothing is kept between pools;
- ``verify=True`` recomputes every served value and raises on any difference (tests);
- the frozen functions are restored on exit. No frozen file is modified.
Byte identity (bundle_sha256 AND the strict canonical JSON) with the frozen run is a test, not an assumption.
"""
import contextlib
import json as _json

from bot.analyser import behavior_pipeline as bp
from bot.analyser import final_decision_engine as fde

STATS = {'hits': 0, 'misses': 0, 'pools': 0}


class Memo:
    def __init__(self, verify=False):
        self.store, self.verify = {}, verify

    def get(self, name, tx, args, compute, copy=None):
        key = (name, id(tx), args)
        found = self.store.get(key)
        if found is not None and found[0] is tx:
            STATS['hits'] += 1
            value = found[1]
            if self.verify and compute() != value:
                raise AssertionError('memo_differs:' + name)
            return copy(value) if copy else value
        STATS['misses'] += 1
        value = compute()
        self.store[key] = (tx, value)
        return copy(value) if copy else value


class JsonShim:
    """``behavior_pipeline.json`` within the block: dumps(tx, separators=(',', ':')) memoized, the rest delegated."""

    def __init__(self, memo):
        self._memo = memo

    def dumps(self, obj, **kwargs):
        if type(obj) is dict and kwargs == {'separators': (',', ':')}:
            return self._memo.get('dumps', obj, (), lambda: _json.dumps(obj, separators=(',', ':')))
        return _json.dumps(obj, **kwargs)

    def __getattr__(self, name):
        return getattr(_json, name)


@contextlib.contextmanager
def memoized(verify=False):
    memo = Memo(verify)
    saved = dict(cm=fde._contains_mint, ccb=fde.classify_creator_behavior, ob=bp._owner_balances, sw=bp._is_swap,
                 js=bp.json)
    fde._contains_mint = lambda tx, mint: memo.get('contains', tx, (mint,), lambda: saved['cm'](tx, mint))
    fde.classify_creator_behavior = lambda tx, mint, creator: memo.get(
        'classify', tx, (mint, creator), lambda: saved['ccb'](tx, mint, creator), copy=dict)
    bp._owner_balances = lambda tx, mint, field: memo.get(
        'balances', tx, (mint, field), lambda: saved['ob'](tx, mint, field), copy=dict)
    bp._is_swap = lambda tx: memo.get('swap', tx, (), lambda: saved['sw'](tx))
    bp.json = JsonShim(memo)
    try:
        yield memo
    finally:
        fde._contains_mint, fde.classify_creator_behavior = saved['cm'], saved['ccb']
        bp._owner_balances, bp._is_swap, bp.json = saved['ob'], saved['sw'], saved['js']


def per_pool(original, verify=False):
    """Per-pool function: the given replay_pool inside a FRESH memo (nothing survives the pool)."""
    def replay_pool(*args, **kwargs):
        STATS['pools'] += 1
        with memoized(verify):
            return original(*args, **kwargs)
    return replay_pool


@contextlib.contextmanager
def fast_replay_pool(hrr, verify=False):
    original = hrr.replay_pool
    hrr.replay_pool = per_pool(original, verify)
    try:
        yield
    finally:
        hrr.replay_pool = original

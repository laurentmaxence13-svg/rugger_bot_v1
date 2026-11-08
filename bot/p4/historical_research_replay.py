"""Offline, deterministic HISTORICAL_REPLAY of the Master scorers on committed pools.

Turns the committed SOL-quoted LaunchLab archives into research PAPER
BUY->SELL cycles, or into an exact per-decision WAIT journal. Integrity rules:

* **As-of inputs** -- the decision at trade event ``k`` sees only
  ``events[:k+1]`` and the fixture transactions whose ``(slot,
  transactionIndex)`` is not later than that event's transaction. Creator,
  vault authority and base decimals come from the creation transaction alone;
  the archived pool account (fetched at collection time) is never an input.
* **Modelled clocks** -- fixtures hold no receipt clocks: ``modelled receipt =
  block_time * 1000 + receipt_latency_ms`` and ``source_clock_verified`` stays
  False. ``block_time`` is the 1 s chain clock.
* **No invented proof** -- ``signed_creator_verified`` requires valid Ed25519
  signatures, an OUTER creation instruction and a signing creator. SOL/USD is
  absent from the fixtures: without a declared rate every decision WAITs with
  ``sol_usd_rate_unavailable``; a declared rate is labelled with its
  provenance and never marked verified. Creator history is unknown and enters
  the scorer as ``prior_launches=0``.
* **Separation** -- cycles are HISTORICAL_REPLAY research only: never fed to
  the PAPER ledger, ``research_evidence`` or the Master's 50-cycle /
  20-creator gate, and never an operational Master trade.

* **Migration and exclusions (P0 fix)** -- a history whose only defect is
  the buy that crosses the migration boundary ends just before that buy; a
  position still open there is ``migrated_unpriced`` (no P&L). Any other
  incomplete history excludes the pool, listed in ``excluded_pools`` with its
  reasons; every MANIFEST pool is either replayed or listed.
* **Accounting** -- only a ``closed`` cycle has ``pnl_lamports``; an open or
  migrated position keeps its mark apart (``mark_pnl_lamports``), outside
  every P&L total.
* **Fees (P0 fix)** -- our own fills use the causal interval estimate of
  :func:`bot.market.replay.causal_fee_rate` (events up to the decision only).
* **Optional exits** -- :class:`ExitOptions` (trailing stop, maximum hold, clock horizon)
  are off by default and recorded in the bundle when enabled.
* **Arms** -- with ``prior_launches=0`` the union of the Master scorer's
  strategy intents equals ``early_sniping`` at every decision, so both arms
  are identical; no independent operational Master rule is available offline
  (see docs/research/L1_P0_FIXES.md).

Fills, latency, own impact and fees follow :mod:`bot.market.replay`.
Failed-attempt fees are unmodelled by default (0 lamports); about a third of
the fixture signatures failed on chain. No network, wall clock or I/O beyond
reading the fixture directory.
"""
from collections import Counter
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path

from bot.analyser.final_decision_engine import build_features
from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.market.collector import PoolArchive, summarize
from bot.market.pool_timeline import PoolTimeline
from bot.market.replay import ExecutionModel, Strategy, replay
from bot.master_decision import MasterDecisionOrchestrator
from bot.p4.native_asof_signal_bridge import NativeQuote
from bot.p4_experiment import POLICY as P4_POLICY, decide_prefix
from bot.p4.sol_usd_series import (MAX_AGE_MS as SOL_USD_MAX_AGE_MS, VERIFICATION as SOL_USD_VERIFICATION,
                                    available_ms as sol_usd_available_ms, price_usd)

CATEGORY = 'HISTORICAL_REPLAY'
SCHEMA = 'rugger-historical-research-replay-v1'
ENTRY_LAMPORTS = 100_000_000
ARMS = ('master', 'reference')
REFERENCE_STRATEGY = 'early_sniping'
RESEARCH_EVIDENCE_STATUS = 'PENDING_R02_QUALIFICATION'
CLOCK_MODEL = ('modelled_receipt_ms = block_time * 1000 + receipt_latency_ms; '
               'block_time is the 1 s chain clock; the fixtures hold no receipt clocks')
# Mirror of the critical set inside final_decision_engine.decide, used only to
# label journal entries; the scorer's own ``enter`` remains the decision.
CRITICAL_RISKS = frozenset((
    'vente_developpeur', 'transfert_relais', 'liquidite_insuffisante', 'funding_launchlab_absent',
    'concentration_extreme', 'momentum_effondrement', 'tendance_5m_effondrement', 'fomo_extreme',
    'slippage_estime_extreme'))
_DEFAULT_MODEL = ExecutionModel()
# The LaunchLab timeline ends at the buy that crosses the migration boundary: that
# buy and everything after it trade on another venue (CPMM), not on this curve.
MIGRATION_VIOLATION = 'violations:curve_refused:buy_crosses_migration_boundary'
MIGRATION_RULE = ('LaunchLab timeline ends before the buy that crosses the migration boundary; '
                  'a position still open there is migrated_unpriced (no P&L, never a closed cycle)')
EXCLUSION_RULE = ('a pool whose history is not complete for a reason other than its migration is '
                  'excluded and listed with its reasons; it is never replayed partially')


CLOCK_SLOT_MS = 215   # mean slot time (P0 measured 214.5 ms) that turns latency slots into whole seconds


def clock_exit_latency_s(latency_slots):
    """Whole seconds after a clock deadline during which real events still land before our sale."""
    return max(1, -(-(latency_slots * CLOCK_SLOT_MS) // 1000))


def clock_exit_row(row, result, events, params):
    """Trade row of a timed sale (replay ``clock_exit``): no real event carries it.

    Its block time is the landing time; its slot is estimated on the slot floor (most slots, so
    window and migration checks stay conservative), from the last real event applied, with one
    more second for the truncation of block_time (R02 O-A), plus the landing latency.
    """
    last = events[result.clock_exit['last_index']]
    landing = result.clock_exit['landing_time']
    return dict(row, exit_signature=None, exit_block_time=landing,
                exit_slot=last.slot + slots_for_ms((landing + 1 - last.block_time) * 1000) + params.latency_slots)


@dataclass(frozen=True)
class ExitOptions:
    """Optional exits from the scorer's frozen plan; all disabled by default.

    ``trailing_stop``: exit when the curve spot price falls to ``1 - trailing_stop_pct``
    of its peak since entry, once that peak is above the entry price (the rule of
    ``bot.master_positions.choose_frozen_position_action``). ``max_hold``: exit once
    ``hold_seconds`` of the plan have elapsed since entry. Both read the scorer's
    plan at the entry decision; neither is tuned on observed results.

    Prices are the spot of the observed real events (own impact excluded); the
    entry price is the spot after the real event our buy lands behind. Trigger
    precedence follows ``choose_frozen_position_action``: stop loss, trailing
    stop, maximum hold, take profit, then the research ``exit_horizon_ms``.
    The scorer's ``hold_seconds`` (900 to 2700 s) exceeds the default 30 s
    horizon, so ``max_hold`` only acts with a longer, explicitly hashed horizon.

    ``clock_horizon`` (W1 protocol, R1; R02 Q1: faithful application of a rule defined in
    time): the research ``exit_horizon_ms`` is enforced by the clock instead of at the next
    real trade. The sale is sent at entry block_time + ceil(exit_horizon_ms / 1000) s and
    lands ``clock_exit_latency_s`` later, on the shifted curve left by every real event whose
    block_time is at or before the landing second. Limit: block_time has a 1 s resolution, so
    real events up to 1 s after the exact landing instant may be applied before our sale (it
    only moves the price of the timed sale; no decision reads the future). The event-driven
    ``exit_horizon`` trigger is then off; stop loss, take profit and the other options are
    unchanged. A timed sale landing at or after a migration boundary is migrated_unpriced.
    """
    trailing_stop: bool = False
    max_hold: bool = False
    clock_horizon: bool = False

    def __post_init__(self):
        if (type(self.trailing_stop) is not bool or type(self.max_hold) is not bool
                or type(self.clock_horizon) is not bool):
            raise ValueError('invalid_exit_options')

    @property
    def enabled(self):
        return self.trailing_stop or self.max_hold or self.clock_horizon

    def record(self):
        """Bundle record; ``clock_horizon`` appears only when on, so older bundles hash as before."""
        data = asdict(self)
        if not self.clock_horizon:
            del data['clock_horizon']
        return data


def _canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(doc):
    return hashlib.sha256(_canonical(doc).encode()).hexdigest()


@dataclass(frozen=True)
class ReplayParams:
    """Pre-registered replay parameters; hashed into every bundle."""
    latency_slots: int = _DEFAULT_MODEL.latency_slots
    receipt_latency_ms: int = 400
    sol_usd: float = None
    sol_usd_provenance: str = None
    exclude_launchlab_vault: bool = False
    exit_horizon_ms: int = P4_POLICY['exit_horizon_ms']
    base_fee_lamports: int = _DEFAULT_MODEL.base_fee_lamports
    priority_fee_lamports: int = _DEFAULT_MODEL.priority_fee_lamports
    failed_attempt_fee_lamports: int = 0     # per own transaction; 0 = unmodelled

    def __post_init__(self):
        for name in ('latency_slots', 'exit_horizon_ms', 'base_fee_lamports',
                     'priority_fee_lamports', 'failed_attempt_fee_lamports'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f'invalid_{name}')
        # Sub-second, so the modelled creation receipt stays in the creation's
        # chain second (the scorer's ``signal_time``).
        if type(self.receipt_latency_ms) is not int or not 0 <= self.receipt_latency_ms < 1000:
            raise ValueError('invalid_receipt_latency_ms')
        if self.sol_usd is None:
            if self.sol_usd_provenance is not None:
                raise ValueError('sol_usd_provenance_without_rate')
        elif (type(self.sol_usd) not in (int, float) or not math.isfinite(self.sol_usd)
                or self.sol_usd <= 0):
            raise ValueError('invalid_sol_usd')
        elif type(self.sol_usd_provenance) is not str or not self.sol_usd_provenance.strip():
            raise ValueError('sol_usd_provenance_required')
        else:
            object.__setattr__(self, 'sol_usd', float(self.sol_usd))   # 150 and 150.0 hash alike
        if type(self.exclude_launchlab_vault) is not bool:
            raise ValueError('invalid_exclude_launchlab_vault')

    def execution_model(self):
        # Causal fee estimate for our own fills (P0 fix): never the smallest rate of a
        # single tiny decision event.
        return ExecutionModel(latency_slots=self.latency_slots, fee_rate_ppm=None,
                              base_fee_lamports=self.base_fee_lamports,
                              priority_fee_lamports=self.priority_fee_lamports,
                              fee_rate_estimator='causal_interval')


# Lower bound of a Solana slot: faster slots need more of them to cover a horizon, so
# window gaps and embargoes are sized on this floor (T-0031 O1). The committed fixtures
# (slots 4646xxxxx) measure 210-222 ms per slot, not the nominal 400 ms: the former 350 ms
# floor let horizons overrun their windows (tests/test_master_v2_slot_horizon.py).
# Measured on P0 by RUGGER 03 with the 1 s block_time bound, the floor holds at 200 ms
# for spans of 60 s or more; shorter spans use 190 ms (R02 decision C1, finding C3).
SLOT_MS_FLOOR = 200
SLOT_MS_FLOOR_SHORT = 190
SHORT_HORIZON_MS = 60_000


def slots_for_ms(duration_ms):
    """Most slots a duration can span, on the floor that applies to its length."""
    floor = SLOT_MS_FLOOR_SHORT if duration_ms < SHORT_HORIZON_MS else SLOT_MS_FLOOR
    return -(-duration_ms // floor)


def collection_window(entry, manifest, params):
    """Optional collection window from the MANIFEST (pool entry overrides top level).

    ``entry_cutoff_slot``: no research entry is admitted after it; ``window_slot_max``:
    an exit counts as a closed cycle only if it lands at or before it (anti survival
    bias, R02 observation M1). Both or neither; None when absent (fixtures unchanged).
    """
    source = entry if ('entry_cutoff_slot' in entry or 'window_slot_max' in entry) else manifest
    cutoff, end = source.get('entry_cutoff_slot'), source.get('window_slot_max')
    if cutoff is None and end is None:
        return None
    if type(cutoff) is not int or type(end) is not int or not 0 < cutoff < end:
        raise ValueError('invalid_collection_window')
    minimum_gap = slots_for_ms(params.exit_horizon_ms) + 2 * params.latency_slots
    if end - cutoff < minimum_gap:
        raise ValueError('collection_window_gap_shorter_than_exit_horizon')
    return dict(entry_cutoff_slot=cutoff, window_slot_max=end, minimum_gap_slots=minimum_gap)


def load_fixtures(directory):
    """Return (manifest_sha256, {file: sha256}, [(entry, archive)], manifest); refuse any mismatch."""
    directory = Path(directory)
    raw = (directory / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    digests, pools = {}, []
    for entry in sorted(manifest['pools'], key=lambda item: item['pool']):
        if entry['file'] != f"{entry['pool']}.json.gz":
            raise ValueError(f"fixture_file_name_mismatch:{entry['file']}")
        data = (directory / entry['file']).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f"fixture_sha256_mismatch:{entry['file']}")
        # Parse the very bytes that were hashed.
        archive = PoolArchive.from_json(json.loads(gzip.decompress(data)))
        if archive.pool != entry['pool']:
            raise ValueError(f"fixture_pool_mismatch:{entry['file']}")
        digests[entry['file']] = digest
        pools.append((entry, archive))
    return hashlib.sha256(raw).hexdigest(), digests, pools, manifest


def _tx_key(tx):
    index = tx.get('transactionIndex')
    if type(tx.get('slot')) is not int or type(index) is not int or type(tx.get('blockTime')) is not int:
        raise ValueError('transaction_slot_index_or_block_time_missing')
    return tx['slot'], index


def creation_facts(archive):
    """Identity facts derived from the earliest stored transaction only."""
    signature, tx = min(archive.transactions.items(), key=lambda item: _tx_key(item[1]))
    facts = dict(creation_signature=signature, creation_slot=tx['slot'],
                 creation_block_time=tx['blockTime'], mint=None, creator=None,
                 vault_authority=None, base_decimals=None, signed_creator_verified=False)
    try:
        launches = [row for row in compiled_launchlab_creations(tx) if row['pool_state'] == archive.pool]
    except ValueError as exc:
        return dict(facts, signed_creator_reason=f'creation_decode_refused:{exc}')
    if len(launches) != 1:
        return dict(facts, signed_creator_reason='earliest_stored_transaction_is_not_this_pool_creation')
    mint, creator = launches[0]['mint'], launches[0]['creator']
    balances = [b for b in tx['meta'].get('postTokenBalances') or [] if b.get('mint') == mint]
    holders = sorted((int(b['uiTokenAmount']['amount']), b.get('owner')) for b in balances
                     if b.get('owner') and b.get('owner') != creator)
    decimals = {b['uiTokenAmount']['decimals'] for b in balances}
    facts.update(mint=mint, creator=creator, vault_authority=holders[-1][1] if holders else None,
                 base_decimals=decimals.pop() if len(decimals) == 1 else None)
    reasons = []
    try:
        verify_compiled_rpc_signatures(tx)
    except (ValueError, KeyError, IndexError, TypeError, RuntimeError):
        reasons.append('ed25519_signatures_not_verified')
    outer = compiled_launchlab_creations(dict(tx, meta=dict(tx['meta'], innerInstructions=[])))
    if not any((row['pool_state'], row['mint'], row['creator']) == (archive.pool, mint, creator)
               for row in outer):
        reasons.append('creation_is_inner_cpi_not_in_signed_outer_message')
    keys = normalized_compiled_transaction(tx)['transaction']['message']['accountKeys']
    if creator not in {key['pubkey'] for key in keys if key['signer']}:
        reasons.append('creator_not_a_transaction_signer')
    if facts['base_decimals'] is None:
        reasons.append('base_decimals_not_in_creation_transaction')
    facts['signed_creator_verified'] = not reasons
    facts['signed_creator_reason'] = ';'.join(reasons) or 'ed25519_valid_outer_creation_signed_by_creator'
    return facts


def _vetoes(flags):
    return [flag for flag in flags or () if flag in CRITICAL_RISKS]


class _PoolObserver:
    """Causal frames and scorer outputs per decision index, shared by both arms."""

    def __init__(self, archive, timeline, facts, params, sol_usd_series=None):
        self.pool, self.facts, self.params = archive.pool, facts, params
        self.series = sol_usd_series
        self.transactions = sorted((_tx_key(tx), signature, tx)
                                   for signature, tx in archive.transactions.items())
        self.keys = {signature: key for key, signature, _tx in self.transactions}
        self.events_per_tx = Counter(event.signature for event in timeline.events)
        self.orchestrator = MasterDecisionOrchestrator()
        self.frames, self.results = {}, {}

    def observe(self, history):
        index = len(history) - 1
        if index not in self.results:
            self.results[index] = self._evaluate(tuple(history))
        return self.results[index]

    def _quote(self, event, sol):
        state = event.state_after()
        spot = Fraction(state.quote_reserve * 10 ** self.facts['base_decimals'],
                        state.base_reserve * 10 ** 9)
        return float(spot * sol), float(Fraction(state.real_quote, 10 ** 9) * sol)

    def _past_prices(self, events, sol):
        """Past (time, price_usd, liquidity_usd); with a series each event uses its own as-of rate."""
        if self.series is None:
            return [(e.block_time, *self._quote(e, sol)) for e in events]
        rows = []
        for e in events:
            point, _age, refusal = self.series.as_of(
                slot=e.slot, transaction_index=self.keys[e.signature][1],
                decision_ms=e.block_time * 1000 + self.params.receipt_latency_ms)
            if refusal is None:
                rows.append((e.block_time, *self._quote(e, price_usd(point))))
        return rows

    def _evaluate(self, history):
        event, facts, params = history[-1], self.facts, self.params
        index, key = len(history) - 1, self.keys[event.signature]
        at = event.block_time * 1000 + params.receipt_latency_ms
        inputs = [(tx['blockTime'], signature, tx)
                  for tx_key, signature, tx in self.transactions if tx_key <= key]
        last = max(self.keys[signature] for _time, signature, _tx in inputs)
        shared = dict(index=index, signature=event.signature, slot=event.slot,
                      transaction_index=key[1], block_time=event.block_time, modelled_receipt_ms=at,
                      inputs=dict(transactions=len(inputs), max_slot=last[0], max_transaction_index=last[1],
                                  signatures_sha256=_sha(sorted(s for _t, s, _x in inputs))),
                      inputs_causal=(last <= key and all(self.keys[e.signature] <= key for e in history)),
                      features_sha256=None, score=None, risk_flags=None, vetoes=None,
                      strategy_intents=None, operational_master_action=None,
                      operational_master_reasons=None)
        common = ['signed_creator_unverified'] if not facts['signed_creator_verified'] else []
        blocked = None
        if facts['creator'] is None or facts['base_decimals'] is None:
            blocked = ['creation_identity_unavailable']
        elif sum(e.signature == event.signature for e in history) < self.events_per_tx[event.signature]:
            blocked = ['intra_transaction_event_not_last']
        elif self.series is None and params.sol_usd is None:
            blocked = ['sol_usd_rate_unavailable']
        elif self.series is not None:
            point, age, refusal = self.series.as_of(slot=event.slot, transaction_index=key[1],
                                                    decision_ms=at)
            if refusal:
                blocked = [refusal]
            else:
                shared['sol_usd_point'] = dict(
                    slot=point['slot'], transaction_index=point['transaction_index'],
                    source_kind=point['source_kind'], source_ref=point['source_ref'],
                    evidence_sha256=point['evidence_sha256'], age_ms=age,
                    available_ms=sol_usd_available_ms(point), verification=SOL_USD_VERIFICATION)
        if blocked:
            wait = dict(intent='WAIT', blocking_reasons=blocked + common)
            return dict(shared=shared, decisions={arm: wait for arm in ARMS}, exit_conditions=None)
        sol = price_usd(point) if self.series is not None else Fraction(str(params.sol_usd))
        detected = facts['creation_block_time'] * 1000 + params.receipt_latency_ms
        price, funding = self._quote(event, sol)
        features = build_features(
            inputs, facts['mint'], facts['creator'], detected // 1000, at // 1000,
            self._past_prices(history[:-1], sol),
            NativeQuote(price_usd=price, liquidity_usd=funding), prior_launches=0,
            excluded_holder_owners=([facts['vault_authority']] if params.exclude_launchlab_vault
                                    and facts['vault_authority'] else ()))
        buyers = {e.fee_payer for e in history if e.side == 'buy' and e.fee_payer != facts['creator']}
        frame = dict(id=f'{CATEGORY}:{self.pool}:{index}', mint=facts['mint'], creator=facts['creator'],
                     pool=self.pool, detected_at_ms=detected, available_at_ms=at,
                     features_available_at_ms=at, source_slot=event.slot, slot_available_at_ms=at,
                     independent_buyers=len(buyers), data_kind='market_observation',
                     source_clock_verified=False,
                     signed_creator_verified=facts['signed_creator_verified'],
                     features=features.to_dict())
        past = [self.frames[i] for i in sorted(self.frames)
                if self.frames[i]['available_at_ms'] < at][-self.orchestrator.policy['max_history']:]
        self.frames[index] = frame
        master = self.orchestrator.evaluate(frame, past)
        reference = decide_prefix(REFERENCE_STRATEGY, frame, past, decision_at_ms=at)
        evidence = master['decision_evidence']
        alternatives = {row['strategy']: row for row in master['alternatives']}
        priority = evidence['frozen_strategy_priority']
        shared.update(features_sha256=_sha(frame['features']), score=evidence['score'],
                      risk_flags=evidence['risk_flags'], vetoes=_vetoes(evidence['risk_flags']),
                      strategy_intents={name: dict(entry_intent=alternatives[name]['entry_intent'],
                                                   reason=alternatives[name]['reason'])
                                        for name in priority},
                      operational_master_action=master['action'],
                      operational_master_reasons=master['reasons'],
                      inputs_causal=(shared['inputs_causal']
                                     and features.observed_at * 1000 <= at
                                     and all(f['available_at_ms'] < at for f in past)))
        detail = ['critical_veto:' + flag for flag in shared['vetoes']]
        if evidence['reference_score_intent'] is False and not detail:
            detail = ['score_below_minimum']
        intents = [name for name in priority if alternatives[name]['entry_intent'] is True]
        decisions = {}
        for arm, intent, reasons in (
                ('master', bool(intents), sorted({alternatives[n]['reason'] for n in priority})),
                ('reference', reference['enter'] is True, [reference['reason']])):
            enter = intent and facts['signed_creator_verified']
            decisions[arm] = dict(intent='ENTER' if enter else 'WAIT', blocking_reasons=(
                [] if enter else ([] if intent else reasons + detail) + common))
        plan = evidence['reference_exit_conditions']
        return dict(shared=shared, decisions=decisions, scorer_exit_plan=plan, exit_conditions=(
            None if plan is None else {k: plan[k] for k in ('tp_pct', 'sl_pct')}))


class ResearchArm(Strategy):
    """One research arm: journal every decision, enter once, pre-registered exit."""

    def __init__(self, arm, observer, params, window=None, exit_options=None):
        if arm not in ARMS:
            raise ValueError('unknown_research_arm')
        self.arm, self.observer, self.params, self.window = arm, observer, params, window
        self.exit_options = exit_options or ExitOptions()
        self.journal, self.exit_plan, self.exit_trigger = [], None, None
        self.entry_price = self.peak_price = None

    def entry(self, history):
        if self.exit_plan is not None:
            return None
        result = self.observer.observe(history)
        decision = result['decisions'][self.arm]
        if self.window is not None and history[-1].slot > self.window['entry_cutoff_slot']:
            decision = dict(intent='WAIT', blocking_reasons=(
                [r for r in decision['blocking_reasons']] + ['after_entry_cutoff_slot']))
        self.journal.append(dict(result['shared'], arm=self.arm, **decision))
        if decision['intent'] != 'ENTER' or result['exit_conditions'] is None:
            return None
        plan = dict(result['exit_conditions'])
        scorer = result.get('scorer_exit_plan') or {}
        if self.exit_options.trailing_stop:
            plan['trailing_stop_pct'] = scorer.get('trailing_stop_pct')
        if self.exit_options.max_hold:
            plan['hold_seconds'] = scorer.get('hold_seconds')
        self.exit_plan = plan
        return ENTRY_LAMPORTS

    def exit_deadline(self, position):
        """Block time at which the clock sends the horizon sale (only with ``clock_horizon``)."""
        if not self.exit_options.clock_horizon:
            return None
        return position.entry_time + -(-self.params.exit_horizon_ms // 1000)

    def exit(self, history, position, mark):
        take = Fraction(str(self.exit_plan['tp_pct'])) / 100
        stop = Fraction(str(self.exit_plan['sl_pct'])) / 100
        elapsed_ms = (history[-1].block_time - position.entry_time) * 1000
        trailing_pct = self.exit_plan.get('trailing_stop_pct')
        hold_seconds = self.exit_plan.get('hold_seconds')
        trailing = False
        if type(trailing_pct) in (int, float) and trailing_pct > 0:   # only when enabled
            if self.entry_price is None:
                self.entry_price = self.peak_price = _spot(history[position.entry_index])
            price = _spot(history[-1])
            self.peak_price = max(self.peak_price, price)
            trailing = (self.peak_price > self.entry_price
                        and price <= self.peak_price * (1 - Fraction(str(trailing_pct)) / 100))
        held = type(hold_seconds) is int and hold_seconds > 0 and elapsed_ms >= hold_seconds * 1000
        # Precedence of choose_frozen_position_action; take profit and stop loss
        # cannot both hold (tp_pct, sl_pct > 0), so the default exits are unchanged.
        trigger = ('stop_loss' if mark <= position.spent * (1 - stop) else
                   'trailing_stop' if trailing else
                   'max_hold' if held else
                   'take_profit' if mark >= position.spent * (1 + take) else
                   'exit_horizon' if (not self.exit_options.clock_horizon
                                      and elapsed_ms >= self.params.exit_horizon_ms) else None)
        if trigger:
            self.exit_trigger = dict(reason=trigger, index=len(history) - 1, mark=mark)
        return trigger is not None


def _trade(result, events, arm, params):
    def at(index, name):
        return None if index is None else getattr(events[index], name)

    own_transactions = 2 if result.priced else 1 if result.entry_index is not None else 0
    failed = params.failed_attempt_fee_lamports * own_transactions
    value = result.received - result.spent - result.tx_costs - failed if result.priced else None
    # Only a closed cycle has a P&L; a position valued at its last mark keeps that
    # value apart (mark_pnl_lamports) and never enters a P&L total.
    pnl = value if result.outcome == 'closed' else None
    cost = result.spent + result.tx_costs + failed
    row = dict(outcome=result.outcome, spent=result.spent, tokens=result.tokens,
               received=result.received, tx_costs=result.tx_costs, failed_attempt_costs=failed,
               pnl_lamports=pnl, net_return=None if pnl is None or not cost else pnl / cost,
               hold_slots=result.hold_slots, fee_rate_ppm=result.fee_rate_ppm,
               fee_rate_source=result.fee_rate_source, exit_conditions=arm.exit_plan,
               exit_trigger=arm.exit_trigger, notes=list(result.notes))
    for stage in ('decision', 'entry', 'exit'):
        index = getattr(result, f'{stage}_index')
        row.update({f'{stage}_index': index, f'{stage}_signature': at(index, 'signature'),
                    f'{stage}_slot': at(index, 'slot'), f'{stage}_block_time': at(index, 'block_time')})
    if result.exit_landing_slot is not None:
        # An event-driven sale lands at the latest at trigger slot + latency, not at the last
        # real event applied before it: the conservative slot for the migration and window checks (R02 B2).
        row['exit_slot'] = result.exit_landing_slot
    if result.outcome == 'open_at_end':
        row['mark_pnl_lamports'] = value
    if result.fee_rate_evidence is not None:
        row['fee_rate_evidence'] = result.fee_rate_evidence
    return row


def _spot(event):
    """Curve spot price after a real event (quote per base, exact)."""
    state = event.state_after()
    return Fraction(state.quote_reserve, state.base_reserve)


def _exit_after_migration(row, migration):
    """A sale whose conservative landing slot is at or after the migration boundary is unpriced (R02 B1, B2).

    The timeline ends just before the buy that crosses the boundary, so a sale still pending
    there would otherwise be filled on a curve that had already migrated.
    """
    if migration is None or row['outcome'] != 'closed' or row['exit_slot'] < migration['boundary_slot']:
        return row
    return dict(row, outcome='migrated_unpriced', pnl_lamports=None, net_return=None,
                notes=row['notes'] + ['exit_after_migration'])


def _migrated(row):
    """A position still open when the pool migrated cannot be priced on this curve."""
    if row['outcome'] != 'open_at_end':
        return row
    return dict(row, outcome='migrated_unpriced', pnl_lamports=None, net_return=None)


def _apply_window(row, window):
    """A cycle counts only if its exit lands at or before window_slot_max (Q6, M1)."""
    if window is None or row['outcome'] not in ('closed', 'open_at_end'):
        return row
    if row['outcome'] == 'closed' and row['exit_slot'] <= window['window_slot_max']:
        return row
    mark = row['mark_pnl_lamports'] if row['outcome'] == 'open_at_end' else row['pnl_lamports']
    return dict(row, outcome='open_at_window_end', mark_pnl_lamports=mark, pnl_lamports=None, net_return=None)


class PoolExcluded(ValueError):
    """The pool cannot be replayed; ``reasons`` says why (listed in the bundle)."""

    def __init__(self, reasons):
        super().__init__('pool_excluded:' + ';'.join(reasons))
        self.reasons = list(reasons)


def usable_timeline(archive, summary, timeline):
    """Return ``(timeline, migration)`` for replay, or raise PoolExcluded.

    A complete history is used as is. A history whose only defect is the buy that
    crosses the migration boundary ends just before it, provided no valid event of
    this pool comes after that buy. Anything else excludes the pool.
    """
    if summary['complete']:
        return timeline, None
    reasons = []
    if not summary['signatures_complete']:
        reasons.append('signatures_incomplete')
    if summary['transactions_missing']:
        reasons.append('transactions_missing:%d' % summary['transactions_missing'])
    if summary['undecodable']:
        reasons.append('undecodable_transactions:%d' % summary['undecodable'])
    if timeline.gaps:
        reasons.append('timeline_gaps:' + ','.join(sorted({gap.reason for gap in timeline.gaps})))
    others = sorted({reason for _key, reason in timeline.rejected if reason != MIGRATION_VIOLATION})
    if others:
        reasons.append('rejected_events:' + ','.join(others))
    crossing = sorted({key[0] for key, reason in timeline.rejected if reason == MIGRATION_VIOLATION})
    if reasons or not crossing:
        raise PoolExcluded(reasons or ['history_incomplete'])
    positions = [_tx_key(archive.transactions[signature]) for signature in crossing]
    if timeline.events and max(_tx_key(archive.transactions[e.signature]) for e in timeline.events) >= min(positions):
        raise PoolExcluded(['events_after_migration_boundary'])
    first = min(positions)
    migration = dict(rule=MIGRATION_RULE, boundary_signatures=crossing, boundary_slot=first[0],
                     boundary_transaction_index=first[1], max_progress_ppm=summary['max_progress_ppm'])
    return PoolTimeline(timeline.pool, timeline.events, (), ()), migration


def replay_pool(archive, params, *, quote_mint, sol_usd_series=None, window=None, exit_options=None):
    """Replay both research arms on one pool archive (complete, or ending at its migration).

    Raises PoolExcluded when the history cannot be replayed (see usable_timeline).
    """
    summary, timeline = summarize(archive)
    timeline, migration = usable_timeline(archive, summary, timeline)
    facts = creation_facts(archive)
    observer = _PoolObserver(archive, timeline, facts, params, sol_usd_series)
    record = dict(pool=archive.pool, **facts, trades=len(timeline.events),
                  transactions=len(archive.transactions), signatures=len(archive.signatures),
                  failed_signatures=sum(row.get('err') is not None for row in archive.signatures),
                  holder_owners_excluded=([facts['vault_authority']] if params.exclude_launchlab_vault
                                          and facts['vault_authority'] else []),
                  journal=[], arms={})
    if window is not None:
        record['window'] = window
    if migration is not None:
        record['migration'] = migration
    model = params.execution_model()
    if exit_options is not None and exit_options.clock_horizon:
        model = replace(model, clock_exit_latency_s=clock_exit_latency_s(params.latency_slots))
    for name in ARMS:
        arm = ResearchArm(name, observer, params, window, exit_options)
        result = replay(timeline, arm, model, quote_mint=quote_mint)
        record['journal'].extend(arm.journal)
        if result.clock_exit is not None:
            arm.exit_trigger = dict(reason='exit_horizon_clock', index=result.clock_exit['last_index'],
                                    mark=result.received)
        row = _trade(result, timeline.events, arm, params)
        if result.clock_exit is not None:
            row = clock_exit_row(row, result, timeline.events, params)
        if migration is not None:
            row = _migrated(_exit_after_migration(row, migration))
        record['arms'][name] = _apply_window(row, window)
    return record


def _totals(pools):
    totals = {}
    for arm in ARMS:
        trades = [pool['arms'][arm] for pool in pools]
        entries = [row for pool in pools for row in pool['journal'] if row['arm'] == arm]
        reasons = Counter(reason for row in entries for reason in row['blocking_reasons'])
        priced = [row['pnl_lamports'] for row in trades if row['pnl_lamports'] is not None]
        totals[arm] = dict(
            decisions=len(entries), enter_decisions=sum(row['intent'] == 'ENTER' for row in entries),
            entries=sum(row['entry_index'] is not None for row in trades),
            outcomes=dict(sorted(Counter(row['outcome'] for row in trades).items())),
            closed_cycles=sum(row['outcome'] == 'closed' for row in trades),
            pnl_lamports=sum(priced) if priced else None,
            blocking_reasons=dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))))
    return totals


def run_replay(fixtures_dir, params=None, sol_usd_series=None, exit_options=None):
    """Return the deterministic HISTORICAL_REPLAY bundle for the fixture directory.

    ``sol_usd_series`` (bot.p4.sol_usd_series.SolUsdSeries) replaces the declared
    constant: each decision uses the as-of point or WAITs with the refusal reason.
    ``exit_options`` (ExitOptions) enables the scorer plan's trailing stop and
    maximum hold; both are off by default. Every MANIFEST pool is either replayed
    or listed in ``excluded_pools`` with its reasons.
    """
    params = ReplayParams() if params is None else params
    exit_options = ExitOptions() if exit_options is None else exit_options
    if type(exit_options) is not ExitOptions:
        raise ValueError('invalid_exit_options')
    if sol_usd_series is not None and params.sol_usd is not None:
        raise ValueError('sol_usd_constant_and_series_are_exclusive')
    manifest_sha256, digests, archives, manifest = load_fixtures(fixtures_dir)
    pools, excluded = [], []
    for entry, archive in archives:
        try:
            pools.append(replay_pool(archive, params, quote_mint=entry['quote_mint'],
                                     sol_usd_series=sol_usd_series,
                                     window=collection_window(entry, manifest, params),
                                     exit_options=exit_options))
        except PoolExcluded as exc:
            excluded.append(dict(pool=archive.pool, file=entry['file'], reasons=exc.reasons))
    if len(pools) + len(excluded) != len(archives):
        raise ValueError('pool_accounting_mismatch')
    signatures = sum(pool['signatures'] for pool in pools)
    journal = [row for pool in pools for row in pool['journal']]
    bundle = dict(
        schema=SCHEMA, category=CATEGORY, params=asdict(params), params_sha256=_sha(asdict(params)),
        entry_lamports=ENTRY_LAMPORTS, reference_strategy=REFERENCE_STRATEGY,
        master_policy_sha256=MasterDecisionOrchestrator().policy_sha256,
        reference_policy_sha256=_sha(P4_POLICY),
        fixtures=dict(manifest_sha256=manifest_sha256, files=digests),
        index_semantics='entry/exit index = last real event executing before the modelled own order',
        pools=pools, totals=_totals(pools),
        flags=dict(
            category=CATEGORY, source_clock_verified=False, source_clock_model=CLOCK_MODEL,
            asof_inputs_causal=bool(journal) and all(row['inputs_causal'] for row in journal),
            identity_from_creation_transaction_only=True, archived_pool_account_used=False,
            sol_usd=params.sol_usd, sol_usd_provenance=params.sol_usd_provenance,
            sol_usd_verified=False, creator_prior_launches_assumed=0,
            failed_attempt_fees_modelled=params.failed_attempt_fee_lamports > 0,
            fixture_failed_signature_share=(
                sum(pool['failed_signatures'] for pool in pools) / signatures if signatures else None),
            admissible_in_paper_ledger=False, counted_in_master_gate=False,
            master_operational_trade=False, research_evidence_status=RESEARCH_EVIDENCE_STATUS,
            financial_order_submitted=False))
    if any('window' in pool for pool in pools):
        bundle['flags']['collection_window_rule'] = (
            'no entry after entry_cutoff_slot; a cycle counts only if its exit lands at or before '
            'window_slot_max; otherwise open_at_window_end (never a closed cycle)')
    if excluded:
        bundle['excluded_pools'] = excluded
        bundle['flags']['pool_exclusion_rule'] = EXCLUSION_RULE
    if any('migration' in pool for pool in pools):
        bundle['flags']['migration_rule'] = MIGRATION_RULE
    if exit_options.enabled:
        bundle['exit_options'] = exit_options.record()
    if sol_usd_series is not None:
        bundle['sol_usd_series'] = dict(
            label=sol_usd_series.label, ordering=sol_usd_series.ordering, sha256=sol_usd_series.sha256,
            points=len(sol_usd_series.points), max_age_ms=SOL_USD_MAX_AGE_MS,
            verification=SOL_USD_VERIFICATION)
        bundle['flags']['sol_usd_source'] = 'series:' + sol_usd_series.label
    bundle['bundle_sha256'] = _sha(bundle)
    return bundle

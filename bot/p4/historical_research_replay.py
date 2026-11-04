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

Fills, latency, own impact and fees follow :mod:`bot.market.replay`.
Failed-attempt fees are unmodelled by default (0 lamports); about a third of
the fixture signatures failed on chain. No network, wall clock or I/O beyond
reading the fixture directory.
"""
from collections import Counter
from dataclasses import asdict, dataclass
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
from bot.market.replay import ExecutionModel, Strategy, replay
from bot.master_decision import MasterDecisionOrchestrator
from bot.p4.native_asof_signal_bridge import NativeQuote
from bot.p4_experiment import POLICY as P4_POLICY, decide_prefix
from bot.p4.sol_usd_series import MAX_AGE_MS as SOL_USD_MAX_AGE_MS, VERIFICATION as SOL_USD_VERIFICATION, price_usd

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
        return ExecutionModel(latency_slots=self.latency_slots, fee_rate_ppm=None,
                              base_fee_lamports=self.base_fee_lamports,
                              priority_fee_lamports=self.priority_fee_lamports)


SLOT_MS_FLOOR = 400     # average Solana slot; a gap is checked conservatively in slots


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
    minimum_gap = -(-params.exit_horizon_ms // SLOT_MS_FLOOR) + 2 * params.latency_slots
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
                    verification=SOL_USD_VERIFICATION)
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
        return dict(shared=shared, decisions=decisions, exit_conditions=(
            None if evidence['reference_exit_conditions'] is None else
            {k: evidence['reference_exit_conditions'][k] for k in ('tp_pct', 'sl_pct')}))


class ResearchArm(Strategy):
    """One research arm: journal every decision, enter once, pre-registered exit."""

    def __init__(self, arm, observer, params, window=None):
        if arm not in ARMS:
            raise ValueError('unknown_research_arm')
        self.arm, self.observer, self.params, self.window = arm, observer, params, window
        self.journal, self.exit_plan, self.exit_trigger = [], None, None

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
        self.exit_plan = result['exit_conditions']
        return ENTRY_LAMPORTS

    def exit(self, history, position, mark):
        take = Fraction(str(self.exit_plan['tp_pct'])) / 100
        stop = Fraction(str(self.exit_plan['sl_pct'])) / 100
        elapsed_ms = (history[-1].block_time - position.entry_time) * 1000
        trigger = ('take_profit' if mark >= position.spent * (1 + take) else
                   'stop_loss' if mark <= position.spent * (1 - stop) else
                   'exit_horizon' if elapsed_ms >= self.params.exit_horizon_ms else None)
        if trigger:
            self.exit_trigger = dict(reason=trigger, index=len(history) - 1, mark=mark)
        return trigger is not None


def _trade(result, events, arm, params):
    def at(index, name):
        return None if index is None else getattr(events[index], name)

    own_transactions = 2 if result.priced else 1 if result.entry_index is not None else 0
    failed = params.failed_attempt_fee_lamports * own_transactions
    pnl = result.received - result.spent - result.tx_costs - failed if result.priced else None
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
    return row


def _apply_window(row, window):
    """A cycle counts only if its exit lands at or before window_slot_max (Q6, M1)."""
    if window is None or row['outcome'] not in ('closed', 'open_at_end'):
        return row
    if row['outcome'] == 'closed' and row['exit_slot'] <= window['window_slot_max']:
        return row
    return dict(row, outcome='open_at_window_end', mark_pnl_lamports=row['pnl_lamports'],
                pnl_lamports=None, net_return=None)


def replay_pool(archive, params, *, quote_mint, sol_usd_series=None, window=None):
    """Replay both research arms on one complete pool archive."""
    summary, timeline = summarize(archive)
    if not summary['complete']:
        raise ValueError(f'pool_history_incomplete:{archive.pool}')
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
    for name in ARMS:
        arm = ResearchArm(name, observer, params, window)
        result = replay(timeline, arm, params.execution_model(), quote_mint=quote_mint)
        record['journal'].extend(arm.journal)
        record['arms'][name] = _apply_window(_trade(result, timeline.events, arm, params), window)
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


def run_replay(fixtures_dir, params=None, sol_usd_series=None):
    """Return the deterministic HISTORICAL_REPLAY bundle for the fixture directory.

    ``sol_usd_series`` (bot.p4.sol_usd_series.SolUsdSeries) replaces the declared
    constant: each decision uses the as-of point or WAITs with the refusal reason.
    """
    params = ReplayParams() if params is None else params
    if sol_usd_series is not None and params.sol_usd is not None:
        raise ValueError('sol_usd_constant_and_series_are_exclusive')
    manifest_sha256, digests, archives, manifest = load_fixtures(fixtures_dir)
    pools = [replay_pool(archive, params, quote_mint=entry['quote_mint'], sol_usd_series=sol_usd_series,
                         window=collection_window(entry, manifest, params))
             for entry, archive in archives]
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
    if sol_usd_series is not None:
        bundle['sol_usd_series'] = dict(
            label=sol_usd_series.label, sha256=sol_usd_series.sha256,
            points=len(sol_usd_series.points), max_age_ms=SOL_USD_MAX_AGE_MS,
            verification=SOL_USD_VERIFICATION)
        bundle['flags']['sol_usd_source'] = 'series:' + sol_usd_series.label
    bundle['bundle_sha256'] = _sha(bundle)
    return bundle

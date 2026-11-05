"""Offline bridge: real MASTER (bot.master_decision) + baseline (bot.p4_experiment) -> pilot24h ledger.

Phase 1 (`decide_all`) sees ONLY frames/health/capital (no outcome argument exists) and
returns decisions + SHA-256 freeze before any result is read. Phase 2 (`score_all`)
re-verifies the SHA and then scores with explicit outcomes. No network, no signing,
no wallet. Unknown fees/exits stay None; zero qualified cycles => INSUFFICIENT DATA.
The baseline arm is p4 `early_sniping` (= current final_decision_engine entry gate
plus slot/clock checks); it is a reference proxy, not the native-ledger replay.
"""
from copy import deepcopy

from bot import p4_experiment as p4
from bot.master_decision import MasterDecisionOrchestrator
from bot.p3 import pilot24h as p
from bot.p4 import paired_research_ledger as pl

BUY_LAMPORTS = 1_000_000_000
_ACTION = {'ENTER': 'ENTER', 'NO_TRADE': 'REJECT'}


def _prefix(frames, i):
    f = frames[i]
    return [h for h in frames[:i] if h['mint'] == f['mint'] and h['available_at_ms'] < f['available_at_ms']]


def decide_all(frames, health, capital):
    """Pre-outcome decisions for both engines on the same events, times and fees."""
    core = MasterDecisionOrchestrator()
    api = p4._api()
    decisions, cases = [], []
    for i, f in enumerate(frames):
        hist = _prefix(frames, i)
        m = core.evaluate(deepcopy(f), deepcopy(hist), health=deepcopy(health), capital=deepcopy(capital))
        r = p4.decide_prefix('early_sniping', deepcopy(f), deepcopy(hist), api=api)
        ma = _ACTION.get(m['action'], 'WAIT')
        ra = 'ENTER' if r['enter'] else 'WAIT'
        obs = [f['id'], 'buy', f['mint']]
        slot = f.get('source_slot')
        decisions.append({'obs': obs, 'engine': 'MASTER', 'action': ma,
                          'cause': (m['reasons'] or [None])[0] if ma != 'ENTER' else None, 'data_max_slot': slot})
        decisions.append({'obs': obs, 'engine': 'REFERENCE', 'action': ra,
                          'cause': r['reason'] if ra != 'ENTER' else None, 'data_max_slot': slot})
        cases.append({'creator': f['creator'], 'mint': f['mint'], 'pool': f['pool'], 'source_slot': slot,
                      'asof_ms': f['available_at_ms'], 'features_available_at_ms': f['features_available_at_ms'],
                      'feature_receipt_sha256': p4._hash(f['features']),
                      'policy_sha256_master': core.policy_sha256, 'policy_sha256_reference': p4._hash(p4.POLICY),
                      'master_action': ma, 'reference_action': 'WAIT' if ra == 'WAIT' else 'ENTER',
                      'hypothetical_buy_lamports': BUY_LAMPORTS,
                      'source_clock_verified': type(f.get('slot_available_at_ms')) is int
                      and f['slot_available_at_ms'] <= f['available_at_ms'],
                      'signed_creator_verified': False})
    observations = [{'signature': f['id'], 'event': 'buy', 'mint': f['mint'], 'slot': f.get('source_slot')}
                    for f in frames]
    return {'decisions': decisions, 'digest': p.freeze(decisions), 'observations': observations,
            'frozen_pairs': [pl.freeze_pair(c) for c in cases],
            'master_policy_sha256': core.policy_sha256, 'reference_policy_sha256': p4._hash(p4.POLICY)}


def score_all(frozen, outcomes):
    """Phase 2. Refuses if decisions changed since the digest; outcomes[i] may be None (unknown)."""
    if not p.verify_frozen(frozen['decisions'], frozen['digest']):
        raise p.ProtocolError('decisions do not match pre-registered digest')
    if p.freeze(frozen['decisions']) != frozen['digest'] or len(outcomes) != len(frozen['frozen_pairs']):
        raise p.ProtocolError('outcomes must align one-to-one with frozen pairs')
    out = []
    for pair, o in zip(frozen['frozen_pairs'], outcomes):
        out.append(None if o is None else pl.score_pair(pair, o))
    return out


def final_verdict(cycles_master, cycles_ref, provenance):
    return p.verdict(cycles_master, cycles_ref, provenance)

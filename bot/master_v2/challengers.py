"""First MASTER CHALLENGER policies of Deliverable C (RUGGER 01, 2026-11-08): exact-ablation vetoes.

Not validated, not tuned on any result: thresholds are the ones written in Deliverable C §5.1
before any P0 result was read. Each challenger decides at exactly the same instant as a
registered diagnostic arm (``diagnostic-fixed-delay``), so its kept cycles are an exact subset
of that arm's cycles with identical outcomes (Deliverable C §2.5): a veto can only remove
cycles, never move an entry. ``veto_partition`` compares kept against removed cycles and
against random abstention at the same pass rate, without any replay.

Research only: MASTER_RESEARCH_PAPER intents, never operational Master trades, never counted
toward the protected 50-cycle / 20-creator thresholds.
"""
from dataclasses import asdict, dataclass
import random
from statistics import fmean

from bot.master_v2.harness import Policy

TOKEN_SHARE_TO_SUPPLY = 1e6   # progress_ppm scale


def creator_overhang(features):
    """Creator tokens as a share of the curve's sellable supply sold so far (Deliverable C, CH1 v3)."""
    return features['creator_token_share'] * features['progress_ppm'] / TOKEN_SHARE_TO_SUPPLY


@dataclass(frozen=True)
class InsiderVeto5s(Policy):
    """CH1 VETO-INITIÉS-5S: the diagnostic-fixed-delay(5 s) entry, refused when insiders are visible.

    Vetoes, all journaled, all final (NO_TRADE): (v1) the creator has sold; (v2) at least
    ``early_slot_cluster`` fee payers in slots 0-1; (v3) creator overhang above
    ``max_creator_overhang`` (0.04 ~ 0.92 SOL of creator buy at default SDK parameters).
    """
    min_age_s: int = 5
    max_lateness_s: int = 30
    early_slot_cluster: int = 3
    max_creator_overhang: float = 0.04
    require_signed_creator: bool = True
    name = 'challenger-insider-veto-5s'

    def params(self):
        return asdict(self)

    def max_entry_age_s(self):
        return self.min_age_s + self.max_lateness_s

    def base_arm(self):
        """Registered arm whose entries this challenger partitions (same instant, same population)."""
        return dict(policy='diagnostic-fixed-delay',
                    params=dict(delay_s=self.min_age_s, max_lateness_s=self.max_lateness_s,
                                require_signed_creator=self.require_signed_creator))

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if features['age_s'] > self.max_entry_age_s():
            return 'NO_TRADE', ['no_trade_near_the_target_delay']
        if features['age_s'] < self.min_age_s:
            return 'WAIT', ['before_target_delay']
        vetoes = []
        if features['creator_sold_lamports'] > 0:
            vetoes.append('veto_creator_sold')
        if features['early_slot_payers'] >= self.early_slot_cluster:
            vetoes.append('veto_early_slot_cluster')
        if creator_overhang(features) > self.max_creator_overhang:
            vetoes.append('veto_creator_overhang')
        return ('NO_TRADE', vetoes) if vetoes else ('ENTER', ['insiders_not_visible'])


@dataclass(frozen=True)
class CreatorBag30s(Policy):
    """CH2 SAC-CRÉATEUR-30S: partition of diagnostic-fixed-delay(30 s) into G1 / G2 / G3 (H- vs H+).

    G1 creator sold, G2 creator overhang above ``max_creator_overhang``, G3 kept (ENTER).
    Prediction under H-: G3 > G2 > G1. The groups are read from the journal reasons.
    """
    min_age_s: int = 30
    max_lateness_s: int = 30
    max_creator_overhang: float = 0.01
    require_signed_creator: bool = True
    name = 'challenger-creator-bag-30s'

    def params(self):
        return asdict(self)

    def max_entry_age_s(self):
        return self.min_age_s + self.max_lateness_s

    def base_arm(self):
        return dict(policy='diagnostic-fixed-delay',
                    params=dict(delay_s=self.min_age_s, max_lateness_s=self.max_lateness_s,
                                require_signed_creator=self.require_signed_creator))

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if features['age_s'] > self.max_entry_age_s():
            return 'NO_TRADE', ['no_trade_near_the_target_delay']
        if features['age_s'] < self.min_age_s:
            return 'WAIT', ['before_target_delay']
        if features['creator_sold_lamports'] > 0:
            return 'NO_TRADE', ['G1_creator_sold']
        if creator_overhang(features) > self.max_creator_overhang:
            return 'NO_TRADE', ['G2_creator_overhang']
        return 'ENTER', ['G3_kept']


CHALLENGERS = (InsiderVeto5s, CreatorBag30s)


def _closed_returns(bundle, pools):
    out = {}
    for row in bundle['pools']:
        trade = row['trade']
        if row['pool'] in pools and trade['outcome'] == 'closed':
            cost = trade['spent'] + trade['tx_costs'] + trade['failed_attempt_costs']
            out[row['pool']] = trade['pnl_lamports'] / cost
    return out


def _entries(bundle, pools):
    return {row['pool']: row for row in bundle['pools']
            if row['pool'] in pools and row['trade']['entry_index'] is not None}


def _veto_reasons(row):
    final = [entry for entry in row['journal'] if entry['intent'] == 'NO_TRADE']
    return sorted(final[-1]['reasons']) if final else []


def veto_partition(base, filtered, pools, *, n_perm=10_000, seed=7):
    """Exact ablation (Deliverable C §2.5) of a veto challenger against its base arm, on ``pools``.

    ``pools`` must be one non-holdout segment, chosen by the caller (the holdout stays sealed).
    Verifies the partition is exact (every kept entry is the base entry at the same index with
    an identical trade row), then reports kept vs removed closed cycles and the share of
    ``n_perm`` random abstentions at the same pass rate whose mean is at least the kept mean.
    """
    base_entries, kept_entries = _entries(base, pools), _entries(filtered, pools)
    for pool, row in kept_entries.items():
        if pool not in base_entries or base_entries[pool]['trade'] != row['trade']:
            raise ValueError('partition_not_exact:%s' % pool)
    removed = sorted(set(base_entries) - set(kept_entries))
    filtered_rows = {row['pool']: row for row in filtered['pools']}
    reasons = {}
    for pool in removed:
        for reason in _veto_reasons(filtered_rows[pool]) or ['no_final_veto_recorded']:
            reasons[reason] = reasons.get(reason, 0) + 1
    base_returns = _closed_returns(base, pools)
    kept = [base_returns[pool] for pool in sorted(kept_entries) if pool in base_returns]
    dropped = [base_returns[pool] for pool in removed if pool in base_returns]
    result = dict(base_entries=len(base_entries), kept_entries=len(kept_entries), removed_entries=len(removed),
                  removed_by_reason=dict(sorted(reasons.items())),
                  kept_closed=len(kept), removed_closed=len(dropped),
                  kept_mean=fmean(kept) if kept else None, removed_mean=fmean(dropped) if dropped else None,
                  kept_minus_removed=(fmean(kept) - fmean(dropped)) if kept and dropped else None,
                  random_abstention_p=None, n_perm=n_perm, seed=seed)
    everything = kept + dropped
    if kept and dropped:
        rng = random.Random(seed)
        observed = fmean(kept)
        hits = sum(fmean(rng.sample(everything, len(kept))) >= observed for _ in range(n_perm))
        result['random_abstention_p'] = (hits + 1) / (n_perm + 1)
    return result

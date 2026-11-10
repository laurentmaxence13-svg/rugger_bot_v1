"""MASTER V3 candidate policies (MASTER RESEARCH; parameters fixed a priori, never tuned on a result).

Each policy reads the frozen ``native_features`` plus ``v3lab.features.v3_extras`` and the creation
facts. ``needs_v3_features`` tells the runner to compute the extras. The source of this module and
of ``features.py`` is hashed into every pre-registration (``runner.v3lab_fingerprint``), because the
frozen code fingerprint does not cover out-of-tree code.
"""
from dataclasses import asdict, dataclass

from bot.master_v2 import policies as v2
from bot.master_v2.harness import Policy


@dataclass(frozen=True)
class LowFeeDelay5s(Policy):
    """H1 (cost): the diagnostic-fixed-delay(5 s) entry, refused when the pool's fee tier is high.

    Mechanism: the round trip on the curve costs twice the pool's fee rate; if the gross move does
    not depend on the tier, the low tier keeps the fee difference. An exact-ablation veto: it
    decides at the same instant as its base arm and can only remove entries.
    """
    min_age_s: int = 5
    max_lateness_s: int = 30
    max_fee_ppm: int = 15_000        # lowest tier measured on P0 (12 500 ppm) plus a margin
    require_signed_creator: bool = True
    name = 'v3-low-fee-delay-5s'
    needs_v3_features = True

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
        if features['fee_rate_ppm_causal'] > self.max_fee_ppm:
            return 'NO_TRADE', ['veto_fee_above_max']
        return 'ENTER', ['low_fee_tier']


@dataclass(frozen=True)
class GraduationRun(Policy):
    """H3 (selection): enter a curve that is filling fast mid-way, sell before the migration.

    Mechanism: on a constant-product launch curve the price rises mechanically with every buy; a
    pool that is past ``min_progress_ppm`` and still gaining ``min_gain_60s_ppm`` in the last
    minute is in a reflexive run towards graduation. The exit rule (pre-migration progress exit,
    trailing stop, stop loss, clock) is part of the pre-registered trial, not of this class.
    """
    min_progress_ppm: int = 300_000
    max_progress_ppm: int = 800_000
    min_gain_60s_ppm: int = 50_000
    max_top1_token_share: float = 0.20
    max_age_s: int = 600
    require_no_creator_sell: bool = True
    require_signed_creator: bool = True
    name = 'v3-graduation-run'
    needs_v3_features = True

    def params(self):
        return asdict(self)

    def max_entry_age_s(self):
        return self.max_age_s

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if self.require_no_creator_sell and features['creator_sold_lamports'] > 0:
            return 'NO_TRADE', ['creator_sold']
        if features['age_s'] > self.max_age_s or features['progress_ppm'] > self.max_progress_ppm:
            return 'NO_TRADE', ['run_window_closed']
        reasons = []
        if features['progress_ppm'] < self.min_progress_ppm:
            reasons.append('curve_not_filled_enough')
        if features['progress_gain_60s_ppm'] < self.min_gain_60s_ppm:
            reasons.append('fill_too_slow')
        if features['top1_token_share'] > self.max_top1_token_share:
            reasons.append('concentrated_holder')
        return ('WAIT', reasons) if reasons else ('ENTER', ['fast_fill_mid_curve'])


POLICIES = {cls.name: cls for cls in (v2.FixedDelay, v2.RandomEntry, LowFeeDelay5s, GraduationRun)}

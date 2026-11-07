"""First MASTER V2 challenger families and placebos (MASTER RESEARCH; not tuned on any result).

Every policy reads only ``native_features`` (lamports, token atoms, curve spot) and the
creation facts; none needs SOL/USD. Parameters are explicit and hashed into the
pre-registration of each run. Placebos exist to calibrate claims: a challenger is
only interesting if it beats abstention, random entry at matched times and the
immediate snipe after costs, out of sample.
"""
from dataclasses import asdict, dataclass
import hashlib

from bot.master_v2.harness import Policy


class NoTrade(Policy):
    """Abstain everywhere: the zero line every candidate must beat after costs."""
    name = 'placebo-no-trade'

    def decide(self, features, facts):
        return 'NO_TRADE', ['placebo_abstention']


@dataclass(frozen=True)
class RandomEntry(Policy):
    """Enter at a pseudo-random decision age, drawn from the pool id (deterministic placebo)."""
    max_age_s: int = 120
    salt: str = 'v1'
    name = 'placebo-random-entry'

    def params(self):
        return asdict(self)

    def target_age(self, pool):
        digest = hashlib.sha256(f'{self.salt}:{pool}'.encode()).digest()
        return int.from_bytes(digest[:4], 'big') % (self.max_age_s + 1)

    def decide(self, features, facts):
        if features['age_s'] > self.max_age_s:
            return 'NO_TRADE', ['placebo_window_closed']
        if features['age_s'] >= self.target_age(facts.get('pool', '')):
            return 'ENTER', ['placebo_random_age_reached']
        return 'WAIT', ['placebo_waiting']


@dataclass(frozen=True)
class ImmediateSnipe(Policy):
    """Enter at the first observable decision, optionally filtered on creation-time facts."""
    max_age_s: int = 5
    max_early_slot_payers: int = None
    max_creator_token_share: float = None
    require_signed_creator: bool = True
    name = 'immediate-snipe'

    def params(self):
        return asdict(self)

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if features['age_s'] > self.max_age_s:
            return 'NO_TRADE', ['snipe_window_closed']
        if self.max_early_slot_payers is not None and features['early_slot_payers'] > self.max_early_slot_payers:
            return 'NO_TRADE', ['early_slot_cluster']
        if (self.max_creator_token_share is not None
                and features['creator_token_share'] > self.max_creator_token_share):
            return 'NO_TRADE', ['creator_holds_too_much']
        return 'ENTER', ['first_observable_decision']


@dataclass(frozen=True)
class DelayedConfirmation(Policy):
    """Wait for independent demand before entering; give up after ``max_age_s``.

    Mechanism tested: entering after real buyers arrive trades a worse price for
    less adverse selection (fewer dead launches and creator dumps).
    """
    min_age_s: int = 20
    max_age_s: int = 180
    window_s: int = 30
    min_buyers_window: int = 5
    min_net_flow_lamports: int = 1_000_000_000
    max_top1_token_share: float = 0.15
    max_creator_token_share: float = 0.10
    max_drawdown_from_peak: float = 0.25
    require_no_creator_sell: bool = True
    require_signed_creator: bool = True
    name = 'delayed-confirmation'

    def params(self):
        return asdict(self)

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if self.require_no_creator_sell and features['creator_sold_lamports'] > 0:
            return 'NO_TRADE', ['creator_sold']
        if features['age_s'] > self.max_age_s:
            return 'NO_TRADE', ['confirmation_window_closed']
        if features['age_s'] < self.min_age_s:
            return 'WAIT', ['too_early']
        reasons = []
        if features[f'buyers_{self.window_s}s'] < self.min_buyers_window:
            reasons.append('too_few_recent_buyers')
        if features[f'net_flow_{self.window_s}s_lamports'] < self.min_net_flow_lamports:
            reasons.append('weak_net_flow')
        if features['top1_token_share'] > self.max_top1_token_share:
            reasons.append('concentrated_holder')
        if features['creator_token_share'] > self.max_creator_token_share:
            reasons.append('creator_holds_too_much')
        if features['drawdown_from_peak'] > self.max_drawdown_from_peak:
            reasons.append('already_dumping')
        return ('WAIT', reasons) if reasons else ('ENTER', ['independent_demand_confirmed'])


@dataclass(frozen=True)
class FillMomentum(Policy):
    """Enter when the curve fills fast (progress per second), exit before migration.

    Mechanism tested: fast fills attract attention and late buyers before
    graduation; the risk is buying the top from early snipers.
    """
    min_progress_ppm: int = 150_000
    max_progress_ppm: int = 600_000
    max_age_s: int = 300
    min_progress_ppm_per_s: int = 2_000
    max_top1_token_share: float = 0.20
    require_signed_creator: bool = True
    name = 'fill-momentum'

    def params(self):
        return asdict(self)

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if features['age_s'] > self.max_age_s or features['progress_ppm'] > self.max_progress_ppm:
            return 'NO_TRADE', ['momentum_window_closed']
        if features['progress_ppm'] < self.min_progress_ppm:
            return 'WAIT', ['curve_not_filled_enough']
        speed = features['progress_ppm'] / max(features['age_s'], 1)
        if speed < self.min_progress_ppm_per_s:
            return 'WAIT', ['fill_too_slow']
        if features['top1_token_share'] > self.max_top1_token_share:
            return 'WAIT', ['concentrated_holder']
        return 'ENTER', ['fast_fill']


@dataclass(frozen=True)
class FixedDelay(Policy):
    """Enter at the first decision at least ``delay_s`` after creation (entry-timing curve).

    Not a candidate: run for several delays with the same exit rule, it measures how
    the net result depends on entry timing alone (is immediate sniping rewarded?).
    """
    delay_s: int = 0
    max_lateness_s: int = 30
    require_signed_creator: bool = True
    name = 'diagnostic-fixed-delay'

    def params(self):
        return asdict(self)

    def decide(self, features, facts):
        if self.require_signed_creator and not facts.get('signed_creator_verified'):
            return 'NO_TRADE', ['signed_creator_unverified']
        if features['age_s'] > self.delay_s + self.max_lateness_s:
            return 'NO_TRADE', ['no_trade_near_the_target_delay']
        if features['age_s'] < self.delay_s:
            return 'WAIT', ['before_target_delay']
        return 'ENTER', ['target_delay_reached']

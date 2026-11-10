"""Pre-registered plan V3-P0-EXPLO-1: fixed BEFORE any V3 replay; its hash is anchored by RUGGER 02.

Everything a result could tempt us to change lives here: the data scope, the trials (policy,
parameters, exit rule), the replay parameters, the metrics, the pass/fail criteria and the
maximum number of trials. ``plan_sha256()`` hashes the canonical JSON of ``PLAN``; every trial
pre-registration embeds it, so a changed plan cannot reuse a registry entry.

Status of any result: EXPLORATORY. P0 already served 25 registered trials; nothing is promoted
from it. A hypothesis that passes here only earns a pre-registration on a fresh window (W2).
"""
import hashlib
import json

S0_W1 = 467_275_745                 # first slot of the W1 window: no V3 input may reach it
P0_REGISTERED_TRIALS = 25           # registry f1f26e36 (pinned by W1, never written by V3)
REPLAY = dict(latency_slots=4)      # as P0 phase 3 and W1 (4 slots, about 0.86 s); other values: frozen defaults
SEGMENTS = ('exploration', 'train', 'validation')   # chronological; the holdout is not in the pack
DECISION_SEGMENT = 'validation'     # one shot per hypothesis
MIN_GROUP = 20                      # fewer cycles than this in the decision segment: NOT_EVALUABLE
N_BOOT = 10_000
SEED = 20261110
ALPHA = 0.05

_REF = dict(policy='diagnostic-fixed-delay', params=dict(delay_s=5, max_lateness_s=30, require_signed_creator=True))
_CLOCK25 = dict(max_hold_s=25, clock_exit=True)
_STOPS = dict(stop_loss=0.30, trailing=0.25, clock_exit=True)

TRIALS = (
    dict(id='V3-01', role='reference', hypothesis=None, **_REF, exit=_CLOCK25,
         note='fixed 5 s delay, 25 s clock exit: the reference of the same engine (P0 T16)'),
    dict(id='V3-02', role='placebo', hypothesis=None, policy='placebo-random-entry',
         params=dict(max_age_s=120, salt='v1', require_signed_creator=True), exit=_CLOCK25,
         note='random entry age, 25 s clock exit (P0 T19)'),
    dict(id='V3-03', role='candidate', hypothesis='H2', base='V3-01', **_REF, exit=dict(_STOPS, max_hold_s=120)),
    dict(id='V3-04', role='candidate', hypothesis='H2', base='V3-01', **_REF, exit=dict(_STOPS, max_hold_s=300)),
    dict(id='V3-05', role='candidate', hypothesis='H2', base='V3-01', **_REF, exit=dict(_STOPS, max_hold_s=900)),
    dict(id='V3-06', role='probe', hypothesis='H2', base='V3-01', **_REF, exit=dict(max_hold_s=900, clock_exit=True),
         record_path=True,
         note='no stop: records the exact liquidation value after every real event (MFE, MAE, horizon curve); '
              'descriptive, never a candidate'),
    dict(id='V3-07', role='candidate', hypothesis='H1', base='V3-01', policy='v3-low-fee-delay-5s',
         params=dict(min_age_s=5, max_lateness_s=30, max_fee_ppm=15_000, require_signed_creator=True),
         exit=_CLOCK25),
    dict(id='V3-08', role='candidate', hypothesis='H3', policy='v3-graduation-run',
         params=dict(min_progress_ppm=300_000, max_progress_ppm=800_000, min_gain_60s_ppm=50_000,
                     max_top1_token_share=0.20, max_age_s=600, require_no_creator_sell=True,
                     require_signed_creator=True),
         exit=dict(exit_progress_ppm=900_000, trailing=0.20, stop_loss=0.25, max_hold_s=600, clock_exit=True)),
)

HYPOTHESES = dict(
    H1=dict(
        title='Cost: the low fee tier has a higher net expectancy at the same entry',
        mechanism='A round trip on the curve pays the pool fee rate twice (2.5 % to 7.5 % measured on P0). '
                  'If the gross move does not depend on the tier, entries in the low tier keep the difference.',
        test='exact ablation of V3-01 by V3-07 (same instant, identical trade rows): kept (fee <= 15 000 ppm) '
             'against removed closed cycles, frozen challengers.veto_partition, 10 000 random abstentions',
        passes='in validation: kept_minus_removed > 0 and random_abstention_p < 0.05, with at least 20 closed '
               'cycles kept and 20 removed; and kept_minus_removed > 0 in exploration and in train',
        fails='any other evaluable outcome', not_evaluable='fewer than 20 closed cycles kept or removed in validation'),
    H2=dict(
        title='Exit: a longer hold with protective stops beats the 25 s clock exit on the same entries',
        mechanism='The round-trip cost is paid once whatever the hold; a 25 s exit captures little gross move. '
                  'A longer hold with a stop loss (30 %) and a trailing stop (25 %) may keep the right tail and '
                  'cut dead launches. The opposite (time in market costs) is equally plausible: two-sided reading.',
        test='paired difference per pool entered by both arms, d = r(candidate) - r(V3-01), where r is the net '
             'return of a closed cycle and -1 for any entered position that is not a closed cycle; mean of d with '
             'a creator-cluster bootstrap (10 000 draws, seed 20261110); one-sided p = share of bootstrap means '
             '<= 0; Holm over the three candidates V3-03, V3-04, V3-05',
        passes='in validation: mean d > 0, Holm-adjusted p < 0.05 and CVaR 5 % of the candidate not below that of '
               'V3-01 by more than 0.10; and mean d > 0 in exploration and in train',
        fails='any other evaluable outcome', not_evaluable='fewer than 20 paired entries in validation'),
    H3=dict(
        title='Selection: buying a fast mid-curve fill and selling before migration has a positive net expectancy',
        mechanism='On a constant-product launch curve the price rises with every buy; a pool past 30 % of its '
                  'curve and still gaining 5 points a minute is in a reflexive run towards graduation. '
                  'Rare events: P0 (12.85 h, no migration among the visible pools) probably cannot evaluate it.',
        test='V3-08 alone: mean net return per entered position (non-closed counted -1), creator-cluster bootstrap',
        passes='in validation: at least 20 entered positions, pessimistic mean > 0, bootstrap 95 % lower bound > 0, '
               'and pessimistic mean above those of V3-01 and V3-02',
        fails='any other evaluable outcome', not_evaluable='fewer than 20 entered positions in validation'),
)

PLAN = dict(
    schema='rugger-master-v3-plan-v1', plan='V3-P0-EXPLO-1', status='EXPLORATORY',
    data=dict(
        allowed='P0 visible pools only (exploration, train, validation of validation.chronological_split), '
                'from a visible-only pack built by v3lab.pack and anchored by RUGGER 02',
        forbidden=['any slot >= %d (W1)' % S0_W1, 'the sealed P0 holdout (files never copied into the pack)',
                   'embargoed and creator-overlap pools'],
        s0_w1=S0_W1),
    split=dict(segments=list(SEGMENTS), decision_segment=DECISION_SEGMENT,
               rule='validation.chronological_split of the frozen tree, fractions 0.25 x 4, creators disjoint, '
                    'embargo = the largest outcome horizon of the trials (entry age + hold + latency, frozen '
                    'outcome_horizon_slots), computed over ALL pools of the source export (metadata only)',
               one_shot='the validation segment is read once per hypothesis; any second pass is a new trial'),
    replay=REPLAY,
    costs='those of the frozen engine, unchanged: curve fee from causal_fee_rate, exact integer fills, own impact '
          'on later trades, 5 000 + 100 000 lamports per own transaction, 0.1 SOL per entry; no cost is altered',
    window='entry cutoff = window_slot_max - frozen hold_gap_slots(exit rule), never later than the source cutoff; '
           'a cycle counts only if its exit lands by window_slot_max (frozen rule M1)',
    trials=[dict(t) for t in TRIALS], max_trials=len(TRIALS),
    counting=dict(p0_registered_trials=P0_REGISTERED_TRIALS,
                  rule='every executed configuration is one trial, even abandoned; cumulative N = 25 + V3 trials, '
                       'used for the deflated Sharpe ratio; the V3 registry is a separate hash chain; the W1 '
                       'registry, f1f26e36 and N = 32 are untouched'),
    metrics=['entered, closed, non-closed by outcome', 'mean net return of closed cycles',
             'pessimistic mean (non-closed = -1)', 'win rate', 'CVaR 5 % (mean of the ceil(5 % n) worst)',
             'creator-cluster bootstrap 95 % interval', 'instant round-trip cost and drift per closed cycle',
             'deflated Sharpe ratio with the cumulative N', 'V3-06: MFE, MAE and horizon curve (descriptive)'],
    hypotheses=HYPOTHESES,
    statistics=dict(n_boot=N_BOOT, seed=SEED, alpha=ALPHA, min_group=MIN_GROUP, multiple_testing='Holm within H2'),
    after='no promotion from P0; a PASS only earns a pre-registration on a fresh window (W2) before its data '
          'exist; W1 data are not used for V3 before the W1 verdict of RUGGER 02',
)


def canonical(doc=PLAN):
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)


def plan_sha256():
    return hashlib.sha256(canonical().encode()).hexdigest()


def trial(trial_id):
    for row in TRIALS:
        if row['id'] == trial_id:
            return row
    raise ValueError('unknown_trial:%s' % trial_id)


if __name__ == '__main__':
    print(json.dumps(dict(PLAN, plan_sha256=plan_sha256()), sort_keys=True, indent=1))

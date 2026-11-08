"""Causal replay harness for MASTER V2 challenger policies (offline research only).

A ``Policy`` sees ``native_features`` of the events up to the decision and answers
ENTER, WAIT or NO_TRADE (final abstention for the pool). Execution, latency, own
impact, migration and accounting reuse the audited L1 machinery
(``bot.market.replay`` with the causal fee estimate, ``usable_timeline``,
``_trade``/``_migrated`` of ``bot.p4.historical_research_replay``): a challenger can
only differ from the reference by its decisions, never by its bookkeeping.

Exits act on the exact net liquidation value of the whole position (``mark``):
stop loss, trailing stop (armed once the mark exceeded the amount spent), maximum
hold, then take profit -- the precedence of
``bot.master_positions.choose_frozen_position_action``.

Collection window (rule M1 of the L1 replay, R02 B1): when the MANIFEST sets
``entry_cutoff_slot``/``window_slot_max``, no entry is admitted after the cutoff and a
cycle counts as closed only if its exit lands by ``window_slot_max``
(``open_at_window_end`` otherwise, never in the P&L). The window must then cover
the bounded holding time of the exit rule (``max_hold_s``) plus latency.

The pre-registration hash binds the policy, its exit rule, the replay parameters,
the code (hash of the modules that decide and account), the data (MANIFEST hash)
and the windows (R02 O2).

Results are HISTORICAL_REPLAY research: never PAPER-ledger entries, never evidence
for the 50-cycle / 20-creator gate, never operational Master trades.
"""
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from bot.market.collector import summarize
from bot.market.replay import Strategy, replay
from bot.master_v2.features import native_features
from bot.master_v2.validation import preregistration
from bot.p4 import historical_research_replay as hrr

SCHEMA = 'rugger-master-v2-research-v1'
INTENTS = ('ENTER', 'WAIT', 'NO_TRADE')
_ROOT = Path(__file__).resolve().parents[2]
# W1 protocol R4: the code fingerprint covers the transitive closure of the repository modules
# imported (statically, anywhere in a module, relative imports and package __init__ files
# included) from the entry points that run, score, account and evaluate: the V2 harness and
# policies, the L1 replay and its Master scorer, the W1 evaluator, the registry and the CLI.
CODE_ROOTS = (
    'bot/master_v2/harness.py', 'bot/master_v2/policies.py', 'bot/master_v2/challengers.py',
    'bot/master_v2/validation.py', 'bot/master_v2/registry.py', 'bot/master_v2/w1_eval.py',
    'bot/p4/historical_research_replay.py', 'tools/master_v2_research.py')
FINGERPRINT_RULE = ('transitive-closure-v1: sha256 of the JSON list [path, sha256(bytes)] sorted by path, over '
                    'the repository modules statically imported from CODE_ROOTS; interpreter and third-party '
                    'packages are not covered')


def _module_file(root, name):
    """Repository path of module ``name`` (``a/b.py`` or ``a/b/__init__.py``), else None."""
    parts = name.split('.')
    for candidate in ('/'.join(parts) + '.py', '/'.join(parts + ['__init__.py'])):
        if (root / candidate).is_file():
            return candidate
    return None


def _package_of(path):
    """Package of a module file: the directory parts (``a/b/c.py`` and ``a/b/__init__.py`` -> a.b)."""
    return path.split('/')[:-1]


def _imported_names(root, path):
    import ast
    tree = ast.parse((root / path).read_bytes(), filename=path)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package_of(path)
                base = package[:len(package) - (node.level - 1)] if node.level > 1 else package
                module = '.'.join(base + ([node.module] if node.module else []))
            else:
                module = node.module
            names.append(module)
            names += [f'{module}.{alias.name}' for alias in node.names if alias.name != '*']
    # Names that are attributes (``from m import f``) resolve to no file and are dropped; the
    # packages on the way are added by code_modules (enclosing __init__ files).
    return {path for path in (_module_file(root, name) for name in names) if path is not None}


def code_modules(root=None, roots=None):
    """Sorted repository paths of the transitive import closure of ``roots`` (CODE_ROOTS)."""
    root = _ROOT if root is None else root
    seen, todo = set(), list(CODE_ROOTS if roots is None else roots)
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        if not (root / path).is_file():
            raise ValueError('code_module_missing:' + path)
        seen.add(path)
        parts = path.split('/')
        for end in range(1, len(parts)):              # enclosing package __init__ files
            init = '/'.join(parts[:end] + ['__init__.py'])
            if (root / init).is_file() and init not in seen:
                todo.append(init)
        todo += sorted(_imported_names(root, path) - seen)
    return tuple(sorted(seen))


CODE_MODULES = code_modules()


def runtime_record():
    """Interpreter, platform and third-party distributions imported by the closure (published only,
    never hashed: R02 O-R4-1)."""
    import ast
    import importlib.metadata
    import platform
    import sys
    local = {path.split('/')[0] for path in code_modules()} | {'bot', 'tools'}
    names = set()
    for path in code_modules():
        for node in ast.walk(ast.parse((_ROOT / path).read_bytes(), filename=path)):
            if isinstance(node, ast.Import):
                names |= {alias.name.split('.')[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names.add(node.module.split('.')[0])
    third_party = sorted(name for name in names if name not in sys.stdlib_module_names and name not in local)
    distributions = importlib.metadata.packages_distributions()
    packages = {}
    for name in third_party:
        for dist in distributions.get(name, [name]):
            try:
                packages[dist] = importlib.metadata.version(dist)
            except importlib.metadata.PackageNotFoundError:
                packages[dist] = None
    return dict(python=sys.version, implementation=platform.python_implementation(), platform=platform.platform(),
                third_party_imports=third_party, distributions=dict(sorted(packages.items())))


def code_fingerprint():
    """SHA-256 over the exact source of every repository module the W1 code can execute (R4)."""
    rows = [(path, hashlib.sha256((_ROOT / path).read_bytes()).hexdigest()) for path in code_modules()]
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class ExitRule:
    """Fractions of the amount spent (0.3 = 30 %); None disables a trigger.

    ``exit_progress_ppm`` sells once the observed curve progress reaches this level,
    so that a position is not carried into the migration (where it becomes
    unpriced on this curve).
    """
    take_profit: float = None
    stop_loss: float = None
    trailing: float = None
    max_hold_s: int = None
    exit_progress_ppm: int = None
    clock_exit: bool = False      # research option: sell at the max_hold deadline even on a silent curve

    def __post_init__(self):
        for name in ('take_profit', 'stop_loss', 'trailing'):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not 0 < value < 10):
                raise ValueError(f'invalid_{name}')
        if self.stop_loss is not None and self.stop_loss >= 1:
            raise ValueError('invalid_stop_loss')
        if self.trailing is not None and self.trailing >= 1:
            raise ValueError('invalid_trailing')
        if self.max_hold_s is not None and (type(self.max_hold_s) is not int or self.max_hold_s <= 0):
            raise ValueError('invalid_max_hold_s')
        if self.exit_progress_ppm is not None and (type(self.exit_progress_ppm) is not int
                                                   or not 0 < self.exit_progress_ppm < 1_000_000):
            raise ValueError('invalid_exit_progress_ppm')
        if type(self.clock_exit) is not bool:
            raise ValueError('invalid_clock_exit')
        if self.clock_exit and self.max_hold_s is None:
            raise ValueError('clock_exit_requires_max_hold_s')


def rule_dict(rule):
    """Serialised exit rule; ``clock_exit`` appears only when on, so older configurations hash as before."""
    data = asdict(rule)
    if not data['clock_exit']:
        del data['clock_exit']
    return data


class Policy:
    """Override ``decide``; ``name`` and ``params`` identify the pre-registered policy."""
    name = 'abstract'

    def params(self):
        return {}

    def max_entry_age_s(self):
        """Largest pool age (s) at which ``decide`` may still ENTER; None when unbounded."""
        return None

    def decide(self, features, facts):
        """Return (intent, reasons) with intent in INTENTS."""
        raise NotImplementedError


class PolicyArm(Strategy):
    """Journal every decision, enter once with ``entry_lamports``, exit by ``exit_rule``."""

    def __init__(self, policy, exit_rule, facts, events_per_tx, entry_lamports, window=None):
        self.policy, self.rule, self.facts = policy, exit_rule, facts
        self.events_per_tx, self.entry_lamports, self.window = events_per_tx, entry_lamports, window
        self.journal, self.exit_plan, self.exit_trigger = [], None, None
        self.abstained, self.peak_mark = False, None

    def entry(self, history):
        if self.exit_plan is not None or self.abstained:
            return None
        last = history[-1]
        if sum(e.signature == last.signature for e in history) < self.events_per_tx[last.signature]:
            return None                       # a transaction is observed whole, never mid-way
        if self.window is not None and last.slot > self.window['entry_cutoff_slot']:
            # M1: no entry after the cutoff; final, since slots only increase.
            self.journal.append(dict(index=len(history) - 1, signature=last.signature, slot=last.slot,
                                     block_time=last.block_time, intent='NO_TRADE',
                                     reasons=['after_entry_cutoff_slot']))
            self.abstained = True
            return None
        features = native_features(history, self.facts)
        intent, reasons = self.policy.decide(features, self.facts)
        if intent not in INTENTS:
            raise ValueError('invalid_policy_intent')
        self.journal.append(dict(index=len(history) - 1, signature=last.signature, slot=last.slot,
                                 block_time=last.block_time, intent=intent, reasons=list(reasons)))
        if intent == 'NO_TRADE':
            self.abstained = True
            return None
        if intent != 'ENTER':
            return None
        self.exit_plan = rule_dict(self.rule)
        return self.entry_lamports

    def exit_deadline(self, position):
        """Block time at which a clock exit sells (only with ``ExitRule.clock_exit``)."""
        if not self.rule.clock_exit:
            return None
        return position.entry_time + self.rule.max_hold_s

    def exit(self, history, position, mark):
        rule = self.rule
        ratio = mark / position.spent
        self.peak_mark = mark if self.peak_mark is None else max(self.peak_mark, mark)
        held_s = history[-1].block_time - position.entry_time
        trailing = (rule.trailing is not None and self.peak_mark > position.spent
                    and mark <= self.peak_mark * (1 - rule.trailing))
        near_migration = (rule.exit_progress_ppm is not None
                          and history[-1].state_after().progress_ppm >= rule.exit_progress_ppm)
        trigger = ('stop_loss' if rule.stop_loss is not None and ratio <= 1 - rule.stop_loss else
                   'trailing_stop' if trailing else
                   'pre_migration' if near_migration else
                   'max_hold' if (rule.max_hold_s is not None and not rule.clock_exit
                                  and held_s >= rule.max_hold_s) else   # the clock handles it
                   'take_profit' if rule.take_profit is not None and ratio >= 1 + rule.take_profit else None)
        if trigger:
            self.exit_trigger = dict(reason=trigger, index=len(history) - 1, mark=mark)
        return trigger is not None


BLOCK_TIME_RESOLUTION_S = 1   # ages and holds are read on whole-second block times
SLOT_MS_MEAN = hrr.CLOCK_SLOT_MS   # P0 measured 214.5 ms per slot (RUGGER 03, 2026-11-07)


def clock_latency_s(params):
    """Whole seconds after a clock deadline during which real events still land before our sale."""
    return hrr.clock_exit_latency_s(params.latency_slots)


def _slots(seconds, params):
    return hrr.slots_for_ms(seconds * 1000) + 2 * params.latency_slots


MIN_LATENCY_SLOTS = 1          # no run may assume an instantaneous fill (R02 O3)
MIN_EXIT_HORIZON_MS = 1_000    # no run may neutralise the L1 window guard with a ~0 horizon (R02 O5)


def validate_run_params(params):
    """Safety floors of every V2 run, whatever the entry point (CLI or direct call; R02 O7)."""
    if params.latency_slots < MIN_LATENCY_SLOTS:
        raise ValueError('replay_latency_slots_below_1')
    if params.exit_horizon_ms < MIN_EXIT_HORIZON_MS:
        raise ValueError('replay_exit_horizon_below_minimum')
    return params


def hold_gap_slots(exit_rule, params):
    """Slots a position may need after the last admitted entry; None when the hold is unbounded."""
    if exit_rule.max_hold_s is None:
        return None
    return _slots(exit_rule.max_hold_s + BLOCK_TIME_RESOLUTION_S, params)


def outcome_horizon_slots(policy, exit_rule, params):
    """Slots from a pool's creation to its last possible exit (entry age + hold); None if unbounded.

    The embargo between chronological segments must cover it, otherwise the outcome of a pool
    created just before a boundary overlaps the next segment.
    """
    age = policy.max_entry_age_s()
    if age is None or exit_rule.max_hold_s is None:
        return None
    return _slots(age + exit_rule.max_hold_s + 2 * BLOCK_TIME_RESOLUTION_S, params)


def policy_window(entry, manifest, params, exit_rule):
    """L1 collection window, further required to cover the exit rule's bounded hold."""
    window = hrr.collection_window(entry, manifest, params)
    if window is None:
        return None
    required = hold_gap_slots(exit_rule, params)
    if required is None:
        raise ValueError('collection_window_requires_bounded_max_hold_s')
    if window['window_slot_max'] - window['entry_cutoff_slot'] < required:
        raise ValueError('collection_window_gap_shorter_than_max_hold')
    return dict(window, minimum_gap_slots=max(window['minimum_gap_slots'], required))


def run_policy_pool(archive, policy, exit_rule, params, *, quote_mint, window=None,
                    entry_lamports=hrr.ENTRY_LAMPORTS):
    """One pool: journal, trade row (closed P&L or explicit open/migrated/window/unpriced outcome)."""
    validate_run_params(params)
    summary, timeline = summarize(archive)
    timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    arm = PolicyArm(policy, exit_rule, facts, Counter(e.signature for e in timeline.events),
                    entry_lamports, window)
    model = params.execution_model()
    if exit_rule.clock_exit:
        model = replace(model, clock_exit_latency_s=clock_latency_s(params))
    result = replay(timeline, arm, model, quote_mint=quote_mint)
    if result.clock_exit is not None:
        arm.exit_trigger = dict(reason='max_hold_clock', index=result.clock_exit['last_index'],
                                mark=result.received)
    row = hrr._trade(result, timeline.events, arm, params)
    if result.clock_exit is not None:
        row = hrr.clock_exit_row(row, result, timeline.events, params)   # same rule as the L1 timed sale
    if migration is not None:
        # Timed or event-driven, a sale landing at or after the boundary is unpriced (R02 B1, B2).
        row = hrr._migrated(hrr._exit_after_migration(row, migration))
    row = hrr._apply_window(row, window)
    record = dict(pool=archive.pool, creator=facts['creator'], created_slot=facts['creation_slot'],
                  signed_creator_verified=facts['signed_creator_verified'], trades=len(timeline.events),
                  journal=arm.journal, trade=row)
    if migration is not None:
        record['migration'] = migration
    if window is not None:
        record['window'] = window
    return record


def _manifest_design(fixtures_dir, params, exit_rule):
    raw = (Path(fixtures_dir) / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    windows = {entry['pool']: policy_window(entry, manifest, params, exit_rule)
               for entry in sorted(manifest['pools'], key=lambda item: item['pool'])}
    return hashlib.sha256(raw).hexdigest(), windows


def preregister(fixtures_dir, policy, exit_rule, params=None):
    """Pre-registration record of a run, computable before any replay (R02 O2)."""
    params = validate_run_params(hrr.ReplayParams() if params is None else params)
    manifest_sha256, windows = _manifest_design(fixtures_dir, params, exit_rule)
    design = dict(code_sha256=code_fingerprint(), manifest_sha256=manifest_sha256,
                  windows_sha256=hrr._sha(windows))
    sha = preregistration(policy.name, dict(policy=policy.params(), exit=rule_dict(exit_rule),
                                            replay=asdict(params)), design)
    return dict(preregistration_sha256=sha, policy=policy.name, policy_params=policy.params(),
                exit_rule=rule_dict(exit_rule), replay_params=asdict(params), **design)


def run_policy(fixtures_dir, policy, exit_rule, params=None):
    """Bundle of one policy over a fixture directory, with closed-cycle metrics."""
    params = hrr.ReplayParams() if params is None else params
    registration = preregister(fixtures_dir, policy, exit_rule, params)   # validates params first
    manifest_sha256, digests, archives, manifest = hrr.load_fixtures(fixtures_dir)
    if manifest_sha256 != registration['manifest_sha256']:
        raise ValueError('manifest_changed_during_run')
    pools, excluded = [], []
    for entry, archive in archives:
        window = policy_window(entry, manifest, params, exit_rule)
        try:
            pools.append(run_policy_pool(archive, policy, exit_rule, params, quote_mint=entry['quote_mint'],
                                         window=window))
        except hrr.PoolExcluded as exc:
            excluded.append(dict(pool=archive.pool, file=entry['file'], reasons=exc.reasons))
    if len(pools) + len(excluded) != len(archives):
        raise ValueError('pool_accounting_mismatch')
    # No aggregate over all pools (R02 U1): totals would mix in the holdout; per-segment
    # outcomes and metrics come from tools/master_v2_research.py evaluate only.
    bundle = dict(
        schema=SCHEMA, category=hrr.CATEGORY, policy_status='MASTER_RESEARCH',
        policy=policy.name, policy_params=policy.params(), exit_rule=rule_dict(exit_rule),
        params=asdict(params), preregistration_sha256=registration['preregistration_sha256'],
        code_sha256=registration['code_sha256'], windows_sha256=registration['windows_sha256'],
        fixtures=dict(manifest_sha256=manifest_sha256, files=digests),
        pools=pools, excluded_pools=excluded,
        flags=dict(admissible_in_paper_ledger=False, counted_in_master_gate=False,
                   master_operational_trade=False, financial_order_submitted=False,
                   sol_usd_used=False, open_positions_in_pnl=False))
    if any('window' in pool for pool in pools):
        bundle['flags']['collection_window_rule'] = (
            'no entry after entry_cutoff_slot; a cycle counts only if its exit lands at or before '
            'window_slot_max; otherwise open_at_window_end (never a closed cycle); the window covers '
            'the bounded max_hold_s of the exit rule plus latency')
    bundle['bundle_sha256'] = hrr._sha(bundle)
    return bundle

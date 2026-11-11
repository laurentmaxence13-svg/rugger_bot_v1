"""SELL ENGINE study: causal exit rules compared on the SAME entries, valued by v4sim unchanged.

  python -B -m statelab.exits run   <visible_pack> --expect-manifest-sha <sha256> --out <exit_rows.json>
  python -B -m statelab.exits table <exit_rows.json> --declared-k 6 [--census <census.json>] [--markdown <file>]

Entries (fixed, already measured): the reference cell ``age:5`` of ``statelab.points``, one 0.1 SOL
buy per pool, landing after the frozen order latency. Every rule below then decides the sale from
what has really happened up to each later real event (never from the future); a triggered sale
lands after the frozen order latency, behind every real trade of those slots; a rule that never
triggers sells by the frozen clock. Replays are ``v4sim.engine.replay`` in mode M-P.

RULES, declared before any row is read (``mark`` = exact liquidation value of the whole position after
a real event; ``cost`` = stake + both transaction costs):
  X0 clock 25 s                                  the reference exit (already measured: not a new trial)
  X1 take profit   mark >= cost x 1.10           else clock 60 s
  X2 stop loss     mark <= cost x 0.90           else clock 60 s
  X3 both          X1 or X2                      else clock 60 s
  X4 trailing      mark <= peak x 0.90 once the peak is above cost   else clock 300 s
  X5 first sale    the first real SELL after our landing            else clock 60 s
  X6 flow reversal the curve's real quote is below its level of 10 s ago (or of our landing, if later)
                                                 else clock 60 s
Result of a rule on an entry: r = (received - cost - rent) / (cost + rent), rent lost by today's chain
(token class of the census); -1 when the curve completed before the sale landed. The table gives, per
rule: mean, median, share of winners, mean gain and mean loss, how often the rule triggered, and the
paired difference to X0 with a creator-cluster interval. A rule IMPROVES the exit when the lower bound
of that interval is above 0 after Holm over the six rules; it is PROFITABLE only if its own mean is
above 0 with the lower bound of its interval above 0. Computing the table adds K = 6 to N.
Discovery segments only (exploration, train); population and clusters as ``statelab.study``.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import statistics

from bot.market.collector import summarize
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import Strategy
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.evaluate import _interval, cluster_bootstrap_means, holm
from v3lab.pack import Pack

from v4sim import engine
from v4sim.io import actors_from_archive

from statelab.points import REFERENCE_CELL, decision_points
from statelab.study import (DEFAULT_POPULATION, DISCOVERY_SEGMENTS, POPULATIONS, STAKE_LAMPORTS, cluster_key,
                            window_cutoff)

SCHEMA = 'statelab-exit-rows-v1'
RULES = (
    dict(id='X0', label='clock 25 s', clock_s=25),
    dict(id='X1', label='take profit +10 %, clock 60 s', take_profit=0.10, clock_s=60),
    dict(id='X2', label='stop loss -10 %, clock 60 s', stop_loss=0.10, clock_s=60),
    dict(id='X3', label='take profit +10 % or stop loss -10 %, clock 60 s', take_profit=0.10, stop_loss=0.10, clock_s=60),
    dict(id='X4', label='trailing 10 % once above cost, clock 300 s', trailing=0.10, clock_s=300),
    dict(id='X5', label='first real sale after landing, clock 60 s', first_sale=True, clock_s=60),
    dict(id='X6', label='curve flow negative over 10 s, clock 60 s', flow_window_s=10, clock_s=60),
)
REFERENCE_RULE = 'X0'
K = len(RULES) - 1
N_BOOT = 10_000
SEED = 20261112
SPL_RENT_LAMPORTS = 2_039_280


class ExitRuleStrategy(Strategy):
    """Buy the stake decided at ``decision_index``; ask to sell when the rule fires; else the clock sells."""

    def __init__(self, decision_index, amount, rule, cost):
        self.decision_index, self.amount, self.rule, self.cost = decision_index, amount, rule, cost
        self.peak, self.reason, self.trigger_age_s = None, None, None

    def entry(self, history):
        return self.amount if len(history) - 1 == self.decision_index else None

    def exit_deadline(self, position):
        return position.entry_time + self.rule['clock_s']

    def _fired(self, history, position, mark):
        rule, last = self.rule, history[-1]
        self.peak = mark if self.peak is None else max(self.peak, mark)
        if 'stop_loss' in rule and mark * 100 <= self.cost * round(100 * (1 - rule['stop_loss'])):
            return 'stop_loss'
        if 'take_profit' in rule and mark * 100 >= self.cost * round(100 * (1 + rule['take_profit'])):
            return 'take_profit'
        if 'trailing' in rule and self.peak > self.cost and mark * 100 <= self.peak * round(100 * (1 - rule['trailing'])):
            return 'trailing'
        if rule.get('first_sale') and last.side == 'sell':
            return 'first_sale'
        if 'flow_window_s' in rule:
            reference = position.entry_index                     # never earlier than our own landing
            for index in range(len(history) - 2, position.entry_index, -1):
                if history[index].block_time <= last.block_time - rule['flow_window_s']:
                    reference = index
                    break
            if last.real_quote_after < history[reference].real_quote_after:
                return 'flow_reversal'
        return None

    def exit(self, history, position, mark):
        reason = self._fired(history, position, mark)
        if reason is not None and self.reason is None:
            self.reason, self.trigger_age_s = reason, history[-1].block_time - position.entry_time
        return reason is not None


def run_rule(timeline, k, actors, model, rule):
    """One entry, one rule: outcome and proceeds; ``None`` when the buy itself is refused."""
    clock_model = replace(model, clock_exit_latency_s=hrr.clock_exit_latency_s(model.latency_slots))
    cost = STAKE_LAMPORTS + 2 * model.tx_cost
    strategy = ExitRuleStrategy(k, STAKE_LAMPORTS, rule, cost)
    result = engine.replay(timeline, strategy, clock_model, quote_mint=WSOL_MINT, mode='M-P', actors=actors)
    if result.entry_index is None:
        return None
    migrated = result.outcome == 'migrated_unpriced'
    if not migrated and result.outcome != 'closed':
        raise ValueError('exit_rule_left_a_position_open:%s' % result.outcome)       # the clock always sells
    by_clock = 'clock_exit' in result.notes
    return dict(migrated=migrated, value=None if migrated else result.received,
                reason=None if migrated else ('clock' if by_clock else strategy.reason),
                trigger_age_s=None if migrated or by_clock else strategy.trigger_age_s,
                land_index=result.entry_index, tokens=result.tokens, cost=cost)


def pool_row(archive, entry, segment, params, cutoff_slot, population=DEFAULT_POPULATION):
    """The reference entry of one pool under every rule; ``(None, reason)`` when there is none."""
    if population not in POPULATIONS:
        raise ValueError('unknown_population')
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded as exc:
        return None, 'not_replayable:' + ';'.join(exc.reasons)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if population == 'signed' and not facts['signed_creator_verified']:
        return None, 'creator_not_signed'
    kind, level = REFERENCE_CELL.split(':')
    events = timeline.events
    ks = [k for k, labels in decision_points(events, facts['creation_block_time'], archive.pool)
          if [kind, int(level)] in labels]
    if not ks:
        return None, 'no_reference_entry'
    if cutoff_slot is not None and events[ks[0]].slot > cutoff_slot:
        return None, 'after_cutoff'
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    rules = {}
    for rule in RULES:
        outcome = run_rule(timeline, ks[0], actors, model, rule)
        if outcome is None:
            return None, 'entry_refused'
        rules[rule['id']] = outcome
    first = rules[REFERENCE_RULE]
    if any((o['land_index'], o['tokens'], o['cost']) != (first['land_index'], first['tokens'], first['cost'])
           for o in rules.values()):
        raise ValueError('rules_do_not_share_the_same_entry')
    return dict(pool=archive.pool, creator=cluster_key(archive, facts),
                creator_signed=bool(facts['signed_creator_verified']), segment=segment, decision_index=ks[0],
                cost=first['cost'], rules={key: {f: v for f, v in o.items() if f not in ('land_index', 'tokens', 'cost')}
                                           for key, o in rules.items()}), None


def run(pack_dir, expect_manifest_sha256, *, latency_slots=plan.REPLAY['latency_slots'], population=DEFAULT_POPULATION):
    params = hrr.ReplayParams(latency_slots=latency_slots)
    pack = Pack(pack_dir, expect_manifest_sha256)
    rows, skipped = [], {}
    for entry, archive, segment in pack.pools():
        if segment not in DISCOVERY_SEGMENTS:
            continue
        row, reason = pool_row(archive, entry, segment, params, window_cutoff(entry, pack.manifest, params), population)
        if row is None:
            skipped[reason.split(':')[0]] = skipped.get(reason.split(':')[0], 0) + 1
            continue
        rows.append(row)
    document = dict(schema=SCHEMA, status='EXPLORATORY', pack_manifest_sha256=pack.manifest_sha256,
                    segments=list(DISCOVERY_SEGMENTS), population=population, latency_slots=latency_slots,
                    entries=REFERENCE_CELL, rules=[dict(rule) for rule in RULES], reference_rule=REFERENCE_RULE, k=K,
                    exits_sha256=fingerprint(), entered=len(rows), creators=len({r['creator'] for r in rows}),
                    pools_without_entry=dict(sorted(skipped.items())), rows=rows,
                    flags=dict(holdout_read=False, w1_data_read=False, promotion_allowed=False,
                               financial_order_submitted=False))
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


def fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _return(row, rule_id, rents):
    outcome = row['rules'][rule_id]
    rent = SPL_RENT_LAMPORTS if rents is None else rents.get(row['pool'], (None, None))[1]
    if rent is None:
        raise ValueError('token_class_unknown_for_a_pool')
    if outcome['migrated']:
        return -1.0
    return (outcome['value'] - row['cost'] - rent) / (row['cost'] + rent)


def _boot(values, groups, n_boot):
    if not values or not n_boot:
        return None, None
    means = cluster_bootstrap_means(values, groups, n_boot=n_boot, seed=SEED)
    return _interval(means, 0.05), (sum(m <= 0 for m in means) + 1) / (n_boot + 1)


def table(document, census=None, *, declared_k, n_boot=N_BOOT):
    if document.get('schema') != SCHEMA:
        raise ValueError('not_an_exit_rows_document')
    if type(declared_k) is not int or declared_k != K:
        raise ValueError('declared_k_is_not_the_number_of_exit_rules:%d' % K)
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    rows, groups = document['rows'], [r['creator'] for r in document['rows']]
    base = [_return(r, REFERENCE_RULE, rents) for r in rows]
    out, pvalues = {}, []
    for rule in RULES:
        returns = [_return(r, rule['id'], rents) for r in rows]
        diffs = [a - b for a, b in zip(returns, base)]
        interval, _p = _boot(returns, groups, n_boot)
        diff_interval, diff_p = _boot(diffs, groups, n_boot) if rule['id'] != REFERENCE_RULE else (None, None)
        wins, losses = [v for v in returns if v > 0], [v for v in returns if v <= 0]
        reasons = {}
        for r in rows:
            key = 'migrated' if r['rules'][rule['id']]['migrated'] else r['rules'][rule['id']]['reason']
            reasons[key] = reasons.get(key, 0) + 1
        out[rule['id']] = dict(
            label=rule['label'], entries=len(returns), mean_r=statistics.fmean(returns) if returns else None,
            mean_r_ci95=interval, median_r=statistics.median(returns) if returns else None,
            win_rate=len(wins) / len(returns) if returns else None,
            mean_gain=statistics.fmean(wins) if wins else None, mean_loss=statistics.fmean(losses) if losses else None,
            exits=dict(sorted(reasons.items())),
            vs_clock_25=None if rule['id'] == REFERENCE_RULE else dict(
                mean=statistics.fmean(diffs) if diffs else None, ci95=diff_interval, p_one_sided=diff_p))
        if rule['id'] != REFERENCE_RULE:
            pvalues.append(diff_p)
    adjusted = holm(pvalues)
    for rule, p in zip([r for r in RULES if r['id'] != REFERENCE_RULE], adjusted):
        block = out[rule['id']]
        low = (block['vs_clock_25']['ci95'] or [None])[0]
        own = (block['mean_r_ci95'] or [None])[0]
        block['vs_clock_25']['p_holm'] = p
        block['improves_the_exit'] = bool(low is not None and low > 0 and p is not None and p < 0.05)
        block['profitable'] = bool(block['mean_r'] is not None and block['mean_r'] > 0 and own is not None and own > 0)
    return dict(schema='statelab-exit-table-v1', status='EXPLORATORY', rows_sha256=document['rows_sha256'],
                pack_manifest_sha256=document['pack_manifest_sha256'], segments=document['segments'],
                population=document['population'], entries=document['entries'], entered=document['entered'],
                creators=document['creators'], k=K, trials_added_to_n=K,
                rent_basis='token class of the census' if rents is not None else 'ASSUMED: SPL Token rent for every pool',
                rules=out, notes=[
                    'same entries for every rule; exits decided from the past only; frozen latency on the buy and on the sale',
                    f'computing this table added {K} to the cumulative trial count N',
                    'r includes every cost and the rent lost by today\'s chain; a migrated position counts -1',
                    'a rule that improves the exit is not a profitable strategy unless its own mean is above 0'])


def _pct(value, digits=2):
    return '—' if value is None else f'{100 * value:.{digits}f} %'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + [
        f"> entrées : {document['entries']} ; {document['entered']} positions, {document['creators']} créateurs ; "
        f"population {document['population']} ; loyer : {document['rent_basis']}", '',
        '| Règle | Sortie | Rendement net moyen | IC 95 % | Médiane | Part de gagnants | Gain moyen | Perte moyenne '
        '| Sorties (motif : nombre) | Écart à l’horloge 25 s | IC 95 % de l’écart | p (Holm) | Améliore la sortie | Rentable |',
        '|' + '---|' * 14]
    for key, r in document['rules'].items():
        ci, d = r['mean_r_ci95'], r['vs_clock_25']
        exits = ', '.join(f'{name} {count}' for name, count in r['exits'].items())
        lines.append(
            f"| {key} | {r['label']} | {_pct(r['mean_r'])} | "
            f"{'—' if ci is None else f'[{100 * ci[0]:.2f} ; {100 * ci[1]:.2f}]'} | {_pct(r['median_r'])} | "
            f"{_pct(r['win_rate'], 1)} | {_pct(r['mean_gain'])} | {_pct(r['mean_loss'])} | {exits} | "
            f"{'référence' if d is None else _pct(d['mean'])} | "
            f"{'—' if d is None or d['ci95'] is None else '[%.2f ; %.2f]' % (100 * d['ci95'][0], 100 * d['ci95'][1])} | "
            f"{'—' if d is None or d.get('p_holm') is None else '%.3f' % d['p_holm']} | "
            f"{'—' if d is None else ('OUI' if r['improves_the_exit'] else 'non')} | "
            f"{'—' if d is None else ('OUI' if r['profitable'] else 'non')} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='causal exit rules on the same entries (sell engine)')
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('pack', type=Path)
    r.add_argument('--expect-manifest-sha', required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--latency-slots', type=int, default=plan.REPLAY['latency_slots'])
    r.add_argument('--population', choices=POPULATIONS, default=DEFAULT_POPULATION)
    t = sub.add_parser('table')
    t.add_argument('rows', type=Path)
    t.add_argument('--declared-k', type=int, required=True)
    t.add_argument('--census', type=Path)
    t.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    if a.command == 'run':
        if a.out.exists():
            raise SystemExit('output_exists')
        document = run(a.pack, a.expect_manifest_sha, latency_slots=a.latency_slots, population=a.population)
        a.out.write_text(json.dumps(document, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
        # Identifiers and sample sizes only: no value is shown at run time.
        print(json.dumps(dict(entered=document['entered'], creators=document['creators'],
                              pools_without_entry=document['pools_without_entry'], k=document['k'],
                              rows_sha256=document['rows_sha256'], exits_sha256=document['exits_sha256']), sort_keys=True))
        return 0
    raw = a.rows.read_bytes()
    census = json.loads(a.census.read_bytes()) if a.census else None
    document = table(json.loads(raw), census, declared_k=a.declared_k)
    document['rows_file_sha256'] = hashlib.sha256(raw).hexdigest()
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

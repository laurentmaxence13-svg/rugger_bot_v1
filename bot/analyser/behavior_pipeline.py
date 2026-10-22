"""Backtest comportemental sans exécution.

Les indicateurs sont calculés uniquement avec les informations disponibles
avant l'entrée simulée : historique antérieur du créateur et transactions
présentes dans le cache Helius jusqu'à l'heure d'entrée.  Ce module ne signe
aucune transaction et ne peut pas activer le paper trader.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from itertools import combinations
import json
import math
import sqlite3

from bot.analyser.research_pipeline import (
    _quote_at_or_after,
    load_prices,
    verified_launches,
)


def _account_keys(tx):
    keys = ((tx.get('transaction') or {}).get('message') or {}).get(
        'accountKeys', []
    ) or []
    return [item.get('pubkey') if isinstance(item, dict) else item
            for item in keys]


def _transaction_wallet(tx):
    keys = _account_keys(tx)
    return keys[0] if keys else None


def _balance_amount(item):
    amount = ((item.get('uiTokenAmount') or {}).get('uiAmount'))
    if amount is not None:
        try:
            value = float(amount)
            return value if math.isfinite(value) else 0.0
        except (TypeError, ValueError):
            return 0.0
    raw = ((item.get('uiTokenAmount') or {}).get('amount'))
    decimals = ((item.get('uiTokenAmount') or {}).get('decimals', 0))
    try:
        return float(raw) / (10 ** int(decimals))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _owner_balances(tx, mint, field):
    """Return token amounts by owner, resolving accountIndex where possible."""
    meta = tx.get('meta') or {}
    keys = _account_keys(tx)
    result = defaultdict(float)
    for item in meta.get(field, []) or []:
        if item.get('mint') != mint:
            continue
        owner = item.get('owner')
        if owner is None:
            index = item.get('accountIndex')
            if isinstance(index, int) and 0 <= index < len(keys):
                owner = keys[index]
        if owner:
            result[owner] += _balance_amount(item)
    return dict(result)


def _sol_delta(tx, owner):
    keys = _account_keys(tx)
    if owner not in keys:
        return 0.0
    index = keys.index(owner)
    meta = tx.get('meta') or {}
    pre, post = meta.get('preBalances') or [], meta.get('postBalances') or []
    if index >= len(pre) or index >= len(post):
        return 0.0
    try:
        return (float(post[index]) - float(pre[index])) / 1_000_000_000
    except (TypeError, ValueError):
        return 0.0


def _is_swap(tx):
    logs = ((tx.get('meta') or {}).get('logMessages') or [])
    text = ' '.join(str(item).lower() for item in logs)
    if any(word in text for word in ('swap', 'instruction: buy', 'instruction: sell')):
        return True
    return any(word in str(tx).lower()
               for word in ('swapbaseinput', 'swapbaseoutput'))


def _instructions(tx):
    message = (tx.get('transaction') or {}).get('message') or {}
    result = list(message.get('instructions') or [])
    for group in ((tx.get('meta') or {}).get('innerInstructions') or []):
        result.extend(group.get('instructions') or [])
    return result


def _creator_transfer_out(tx, mint, creator):
    """Detect a creator-authorised token transfer to another owner."""
    if _is_swap(tx):
        return False
    owners = {}
    for field in ('preTokenBalances', 'postTokenBalances'):
        for item in ((tx.get('meta') or {}).get(field) or []):
            if item.get('mint') != mint:
                continue
            index = item.get('accountIndex')
            keys = _account_keys(tx)
            account = keys[index] if isinstance(index, int) and index < len(keys) else None
            owner = item.get('owner')
            if account and owner:
                owners[account] = owner
    for instruction in _instructions(tx):
        parsed = instruction.get('parsed') if isinstance(instruction, dict) else None
        if not isinstance(parsed, dict) or parsed.get('type') not in {
            'transfer', 'transferChecked'
        }:
            continue
        info = parsed.get('info') or {}
        if info.get('authority') != creator:
            continue
        source_owner = owners.get(info.get('source'))
        destination_owner = owners.get(info.get('destination'))
        if source_owner == creator and destination_owner and destination_owner != creator:
            return True
    return False


def classify_creator_behavior(tx, mint, creator):
    """Classify one cached transaction from the creator's perspective."""
    pre = _owner_balances(tx, mint, 'preTokenBalances').get(creator, 0.0)
    post = _owner_balances(tx, mint, 'postTokenBalances').get(creator, 0.0)
    token_delta = post - pre
    sol_delta = _sol_delta(tx, creator)
    sale = token_delta < -1e-12 and (sol_delta > 0 or _is_swap(tx))
    buy = token_delta > 1e-12 and (sol_delta < 0 or _is_swap(tx))
    relay = _creator_transfer_out(tx, mint, creator)
    return {
        'sale': bool(sale),
        'buy': bool(buy),
        'relay': bool(relay),
        'token_delta': token_delta,
    }


def wallet_graph_snapshot(cached, mint, signal_time, observed_at):
    """Summarise holder concentration and wallet links known by observation.

    The cache is often creator-focused rather than a full ledger, so the
    holder statistics are explicitly partial.  We count only transactions in
    ``[signal_time, observed_at]`` and never use a later balance to decide an
    entry.  Same-slot co-occurrence is an indicator, not proof of a bundle.
    """
    latest_holders = {}
    linked_wallets = set()
    edges = set()
    slots = defaultdict(set)
    source_transactions = 0
    for timestamp, _signature, tx in cached:
        if timestamp < int(signal_time) or timestamp > int(observed_at):
            continue
        if mint not in json.dumps(tx, separators=(',', ':')):
            continue
        source_transactions += 1
        owners = set()
        for field in ('preTokenBalances', 'postTokenBalances'):
            owners.update(_owner_balances(tx, mint, field))
        signer = _transaction_wallet(tx)
        participant_wallets = {owner for owner in owners if owner}
        if signer:
            participant_wallets.add(signer)
            for owner in owners:
                if owner and owner != signer:
                    edges.add((signer, owner))
        linked_wallets.update(participant_wallets)
        slot = tx.get('slot')
        if slot is not None:
            slots[slot].update(participant_wallets)

        # The latest observed post-balance wins.  If only a pre-balance is
        # available, it is still useful but marked partial by the count.
        balances = _owner_balances(tx, mint, 'postTokenBalances')
        if not balances:
            balances = _owner_balances(tx, mint, 'preTokenBalances')
        for owner, amount in balances.items():
            latest_holders[owner] = (int(timestamp), max(0.0, float(amount)))

    for participants in slots.values():
        if len(participants) >= 2:
            edges.update(combinations(sorted(participants), 2))
    amounts = [amount for _timestamp, amount in latest_holders.values()
               if amount > 0 and math.isfinite(amount)]
    total = sum(amounts)
    top_share = max(amounts) / total if amounts and total > 0 else None
    return {
        'holder_count': len(amounts),
        'top_holder_share': top_share,
        'holder_data_known': bool(amounts),
        'linked_wallets': len(linked_wallets),
        'wallet_link_count': len(edges),
        'same_slot_wallets': max((len(group) for group in slots.values()), default=0),
        'source_transactions': source_transactions,
    }


def load_cached_transactions(db_path):
    """Load valid cached Helius transactions ordered by block time."""
    con = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    con.execute('PRAGMA busy_timeout=30000')
    rows = con.execute(
        '''SELECT signature,payload FROM research_tx_cache
           WHERE fetched_ok=1 AND payload IS NOT NULL'''
    ).fetchall()
    con.close()
    result = []
    for signature, raw in rows:
        try:
            tx = json.loads(raw)
            timestamp = tx.get('blockTime')
            if isinstance(timestamp, int) and timestamp > 0:
                result.append((timestamp, signature, tx))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(result, key=lambda row: (row[0], row[1]))


def _cache_index(cached):
    timestamps = [item[0] for item in cached]
    return timestamps, cached


def behavior_observation(event, prices, cached, prior_launches=0,
                         exit_delay=900, entry_delay=300, max_gap=120):
    """Create one observation using only data available by simulated entry."""
    timestamp, signature, creator, mint, _pool = event
    series = prices.get(mint, [])
    reference = _quote_at_or_after(series, timestamp + 60, max_gap)
    entry = _quote_at_or_after(series, timestamp + entry_delay, max_gap)
    exit_quote = _quote_at_or_after(series, timestamp + exit_delay, max_gap)
    if reference is None or entry is None or exit_quote is None:
        return None
    _, reference_price = reference
    entry_time, entry_price = entry
    exit_time, exit_price = exit_quote
    if min(reference_price, entry_price, exit_price) <= 0:
        return None

    timestamps, rows = _cache_index(cached)
    left = bisect_left(timestamps, timestamp)
    right = bisect_right(timestamps, entry_time)
    relevant = []
    for tx_time, tx_signature, tx in rows[left:right]:
        if tx_signature == signature:
            continue
        # Avoid parsing every creator transaction that cannot concern the mint.
        if mint not in json.dumps(tx, separators=(',', ':')):
            continue
        classification = classify_creator_behavior(tx, mint, creator)
        relevant.append((tx_time, classification))

    sale = any(item[1]['sale'] for item in relevant)
    relay = any(item[1]['relay'] for item in relevant)
    return {
        'mint': mint,
        'creator': creator,
        'reference_time': reference[0],
        'entry_time': entry_time,
        'exit_time': exit_time,
        'momentum': entry_price / reference_price - 1.0,
        'gross_return': exit_price / entry_price - 1.0,
        'prior_launches': int(prior_launches),
        'behavior_known': bool(relevant),
        'relevant_tx_count': len(relevant),
        'dev_sell_before_entry': bool(sale),
        'relay_before_entry': bool(relay),
    }


def _rule(name, observation):
    """Small pre-registered rule set; no arbitrary threshold search."""
    if name == 'all':
        return True
    if name == 'known_creator':
        return observation['prior_launches'] >= 1
    if name == 'no_dev_sell':
        return observation['behavior_known'] and not observation['dev_sell_before_entry']
    if name == 'no_relay':
        return observation['behavior_known'] and not observation['relay_before_entry']
    if name == 'clean_behavior':
        return (observation['behavior_known']
                and not observation['dev_sell_before_entry']
                and not observation['relay_before_entry'])
    if name == 'known_clean_behavior':
        return (observation['prior_launches'] >= 1 and _rule('clean_behavior', observation))
    if name == 'clean_positive_momentum':
        return _rule('clean_behavior', observation) and observation['momentum'] >= 0
    return False


RULES = ('known_creator', 'no_dev_sell', 'no_relay',
         'clean_behavior', 'known_clean_behavior', 'clean_positive_momentum')


def behavior_backtest(db_path, price_csv, exit_delay=900, costs=(200, 500, 1000),
                      train_fraction=.7, min_train=30, min_test=15):
    events = verified_launches(db_path)
    split = int(len(events) * train_fraction)
    prices = load_prices(price_csv)
    cached = load_cached_transactions(db_path)
    prior_returns = defaultdict(list)
    observations = []
    for event in events:
        prior_mean = (sum(prior_returns[event[2]]) / len(prior_returns[event[2]])
                      if prior_returns[event[2]] else None)
        observation = behavior_observation(
            event, prices, cached,
            prior_launches=sum(1 for previous in events
                              if previous[2] == event[2] and previous[0] < event[0]),
            exit_delay=exit_delay,
        )
        if observation is not None:
            observation['creator_prior_mean_return'] = prior_mean
            observations.append(observation)
            prior_returns[event[2]].append(observation['gross_return'])
    by_mint = {item['mint']: item for item in observations}
    complete_ids = set(by_mint)
    train = [by_mint[e[3]] for e in events[:split] if e[3] in complete_ids]
    test = [by_mint[e[3]] for e in events[split:] if e[3] in complete_ids]
    if len(train) < min_train or len(test) < min_test:
        return {
            'status': 'insufficient_data', 'exit_delay': exit_delay,
            'train': len(train), 'test': len(test),
            'complete': len(observations),
            'missing': len(events) - len(observations),
            'cache_transactions': len(cached),
            'behavior_known': sum(item['behavior_known'] for item in observations),
            'message': 'Observations comportementales insuffisantes.',
        }

    selection_cost = max(costs)
    candidates = []
    for rule in RULES:
        selected = [item for item in train if _rule(rule, item)]
        if len(selected) < 5:
            continue
        mean = sum(item['gross_return'] - selection_cost / 10000 for item in selected) / len(selected)
        candidates.append((mean, len(selected), rule))
    if not candidates:
        return {
            'status': 'no_signal', 'exit_delay': exit_delay,
            'train': len(train), 'test': len(test), 'complete': len(observations),
            'missing': len(events) - len(observations), 'cache_transactions': len(cached),
            'message': 'Aucune règle comportementale avec au moins 5 observations.',
        }
    train_mean, selected_train, rule = max(candidates, key=lambda item: (item[0], item[1], item[2]))
    runs = []
    for cost in costs:
        selected_test = [item for item in test if _rule(rule, item)]
        returns = [item['gross_return'] - cost / 10000 for item in selected_test]
        runs.append({
            'status': 'evaluated' if returns else 'no_signal',
            'exit_delay': exit_delay,
            'rule': rule,
            'assumed_cost_bps': cost,
            'train': len(train), 'test': len(test), 'selected': len(returns),
            'train_mean_return': train_mean,
            'mean_return': sum(returns) / len(returns) if returns else None,
            'win_rate': sum(value > 0 for value in returns) / len(returns) if returns else None,
        })
    eligible = (train_mean > 0 and all(
        run['selected'] >= 5 and run['mean_return'] is not None and run['mean_return'] > 0
        for run in runs
    ))
    return {
        'status': 'validated_behavior' if eligible else 'no_signal',
        'exit_delay': exit_delay, 'rule': rule,
        'train': len(train), 'test': len(test), 'complete': len(observations),
        'missing': len(events) - len(observations),
        'cache_transactions': len(cached),
        'behavior_known': sum(item['behavior_known'] for item in observations),
        'selected_train': selected_train, 'train_mean_return': train_mean,
        'runs': runs,
        'message': ('Règle comportementale positive et robuste à tous les coûts.'
                    if eligible else
                    'Aucune règle comportementale positive hors échantillon à tous les coûts.'),
    }


def behavior_grid(db_path, price_csv, exit_delays=(900, 3660),
                  costs=(200, 500, 1000)):
    runs = [behavior_backtest(db_path, price_csv, exit_delay=delay, costs=costs)
            for delay in exit_delays]
    eligible = [item['exit_delay'] for item in runs
                if item.get('status') == 'validated_behavior']
    return {
        'schema': 'behavior-grid-v1',
        'status': 'validated_behavior_found' if eligible else 'no_validated_behavior',
        'eligible_exit_delays': eligible,
        'runs': runs,
        'message': ('Au moins une règle comportementale reste positive à tous les coûts.'
                    if eligible else
                    'Aucune règle comportementale robuste ; aucun modèle activable.'),
    }

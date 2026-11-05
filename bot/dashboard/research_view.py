"""Read-only Rugger Wallet view of research bundles, with their exact provenance.

No network, no wallet, no order, no provider call. Pure functions: the Streamlit
page (bot/dashboard/app.py) only renders what they return.

Labels -- every displayed element carries exactly one ``label`` built from:

* ``HISTORICAL_REPLAY``: replay of archived on-chain data
  (schema ``rugger-historical-research-replay-v1``);
* ``PROSPECTIVE_PAPER``: prospective research PAPER; no producer exists yet, so
  this section is always empty;
* ``SYNTHETIC``: added to any element whose numbers depend on an invented input:
  a ``SYNTHETIC_TEST_FIXTURE`` SOL/USD series or a declared (assumed) SOL/USD rate;
* ``REAL``: executed on-chain operations. Always empty: nothing here places,
  signs or reads an order.

A bundle is displayed only if (1) its file and canonical ``bundle_sha256`` are
recomputed here and agree with the declared value (and with the committed
results registry when listed there), and (2) its flags state that it is not an
operational Master trade, not counted in the 50-cycle / 20-creator gate, not
admissible in the PAPER ledger and that no financial order was submitted.

External links (Axiom Trade, Solscan, DexScreener, Raydium) are built only from
an address that decodes to the exact Solana size; they are never fetched.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path

LAMPORTS = 1_000_000_000
MAX_BUNDLE_BYTES = 8_000_000
REPLAY_SCHEMA = 'rugger-historical-research-replay-v1'
RESULTS_SCHEMA = 'rugger-historical-research-replay-results-v1'
RESULTS_PATH = 'validation/historical_replay_l1/RESULTS.json'
LABELS = ('HISTORICAL_REPLAY', 'PROSPECTIVE_PAPER', 'SYNTHETIC', 'REAL')
ARM_NAMES = {'master': 'MASTER (recherche)', 'reference': 'RÉFÉRENCE (recherche)'}
# Flags that must be exactly False for a research bundle to be shown at all.
MUST_BE_FALSE = ('master_operational_trade', 'counted_in_master_gate',
                 'admissible_in_paper_ledger', 'financial_order_submitted')
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class BundleRefused(ValueError):
    """The bundle is not displayed; the message says why."""


def _refuse_constant(name):
    raise BundleRefused(f'json_constant_refused:{name}')


def canonical_sha256(document):
    """Same canonical JSON as the replay (sorted keys, compact, no NaN)."""
    text = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _base58_size(value):
    if type(value) is not str or not value or any(c not in _B58 for c in value):
        return None
    number = 0
    for char in value:
        number = number * 58 + _B58.index(char)
    leading = len(value) - len(value.lstrip('1'))
    return leading + (number.bit_length() + 7) // 8


def is_solana_address(value):
    """Base58 text decoding to exactly 32 bytes (public key or program address)."""
    return type(value) is str and 32 <= len(value) <= 44 and _base58_size(value) == 32


def is_solana_signature(value):
    return type(value) is str and 64 <= len(value) <= 88 and _base58_size(value) == 64


def external_links(mint, pool):
    """Outbound links built from validated addresses only (never fetched)."""
    links = dict(axiom=None, solscan_token=None, raydium=None, solscan_pool=None, dexscreener=None)
    if is_solana_address(mint):
        links.update(axiom=f'https://axiom.trade/t/{mint}',
                     solscan_token=f'https://solscan.io/token/{mint}',
                     raydium=f'https://raydium.io/launchpad/token/?mint={mint}')
    if is_solana_address(pool):
        links.update(solscan_pool=f'https://solscan.io/account/{pool}',
                     dexscreener=f'https://dexscreener.com/solana/{pool}')
    return links


def transaction_link(signature):
    return f'https://solscan.io/tx/{signature}' if is_solana_signature(signature) else None


def load_results_registry(root):
    """Committed results registry: {bundle_sha256: variant entry}; {} if absent."""
    path = Path(root) / RESULTS_PATH
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        document = json.loads(path.read_bytes(), parse_constant=_refuse_constant)
        if type(document) is not dict or document.get('schema') != RESULTS_SCHEMA:
            raise BundleRefused('results_registry_schema')
        committed = document['committed_bundle']
        registry = {}
        for variant in document['variants']:
            registry[variant['bundle_sha256']] = dict(
                variant=variant['variant'], file_sha256=variant['file_sha256'],
                committed_path=committed['path'] if committed['variant'] == variant['variant'] else None)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, BundleRefused):
            raise
        raise BundleRefused('results_registry_malformed') from None
    return registry


def verify_bundle(raw, *, registry=None, name='bundle'):
    """Parse and verify a bundle; raise BundleRefused or return (document, verification)."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_BUNDLE_BYTES:
        raise BundleRefused('bundle_size')
    file_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw, parse_constant=_refuse_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, BundleRefused):
            raise
        raise BundleRefused('bundle_json') from None
    if type(document) is not dict or document.get('schema') != REPLAY_SCHEMA:
        raise BundleRefused('bundle_schema_not_supported')
    flags = document.get('flags')
    if (document.get('category') != 'HISTORICAL_REPLAY' or type(flags) is not dict
            or flags.get('category') != 'HISTORICAL_REPLAY'):
        raise BundleRefused('bundle_category')
    for flag in MUST_BE_FALSE:
        if flags.get(flag) is not False:
            raise BundleRefused(f'bundle_flag_must_be_false:{flag}')
    declared = document.get('bundle_sha256')
    body = {key: value for key, value in document.items() if key != 'bundle_sha256'}
    recomputed = canonical_sha256(body)
    if declared != recomputed:
        raise BundleRefused('bundle_sha256_mismatch')
    entry = (registry or {}).get(recomputed)
    if entry is not None and entry['file_sha256'] != file_sha256:
        raise BundleRefused('file_sha256_differs_from_results_registry')
    verification = dict(
        name=name, file_sha256=file_sha256, bundle_sha256=recomputed,
        status='VERIFIED_AGAINST_RESULTS_REGISTRY' if entry else 'SELF_CONSISTENT_NOT_IN_REGISTRY',
        registry_variant=entry['variant'] if entry else None,
        committed_path=entry['committed_path'] if entry else None)
    return document, verification


def bundle_labels(document):
    """Return (label, reasons): HISTORICAL_REPLAY, plus SYNTHETIC if an input is invented."""
    flags, reasons = document['flags'], []
    series = document.get('sol_usd_series')
    if series is not None and series.get('label') != 'COLLECTED':
        reasons.append(f"série SOL/USD étiquetée {series.get('label')}")
    if flags.get('sol_usd') is not None:
        reasons.append(f"taux SOL/USD déclaré ({flags.get('sol_usd_provenance')}), supposé et non vérifié")
    label = 'HISTORICAL_REPLAY' + (' · SYNTHETIC' if reasons else '')
    return label, reasons


def _utc(seconds):
    if type(seconds) is not int:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _sol(lamports):
    return None if type(lamports) is not int else float(Fraction(lamports, LAMPORTS))


def _sol_usd(row, flags):
    """(value_usd, source, age_ms) of the SOL/USD rate used by this decision."""
    point = row.get('sol_usd_point')
    if point is not None:
        value = None
        if type(point.get('price')) is int and type(point.get('exponent')) is int:
            value = float(Fraction(point['price']) * Fraction(10) ** point['exponent'])
        source = (f"{point['source_kind']} · {point['source_ref']} · preuve "
                  f"{point['evidence_sha256'][:12]}… · {point['verification']}")
        return value, source, point.get('age_ms')
    refused = [r for r in row['blocking_reasons'] if r.startswith('sol_usd_')]
    if refused:
        return None, 'refusé : ' + ', '.join(refused), None
    if flags.get('sol_usd') is not None:
        return flags['sol_usd'], f"déclaré ({flags.get('sol_usd_provenance')}), supposé, non vérifié", None
    return None, 'indisponible', None


def pool_rows(document):
    label, _reasons = bundle_labels(document)
    rows = []
    for pool in document['pools']:
        intents = Counter((row['arm'], row['intent']) for row in pool['journal'])
        reasons = Counter(reason for row in pool['journal'] for reason in row['blocking_reasons'])
        closed = sum(arm.get('outcome') == 'closed' for arm in pool['arms'].values())
        links = external_links(pool.get('mint'), pool.get('pool'))
        rows.append(dict(
            label=label, pool=pool['pool'], mint=pool.get('mint'), creator=pool.get('creator'),
            signed_creator_verified=pool.get('signed_creator_verified'),
            signed_creator_reason=pool.get('signed_creator_reason'),
            trades=pool.get('trades'), decisions=len(pool['journal']),
            enter_master=intents[('master', 'ENTER')], enter_reference=intents[('reference', 'ENTER')],
            closed_cycles=closed,
            main_blocking_reasons=', '.join(f'{r} ({n})' for r, n in reasons.most_common(4)),
            **links))
    return rows


def decision_rows(document):
    label, _reasons = bundle_labels(document)
    flags, rows = document['flags'], []
    for pool in document['pools']:
        for row in pool['journal']:
            value, source, age = _sol_usd(row, flags)
            rows.append(dict(
                label=label, pool=pool['pool'], mint=pool.get('mint'), index=row['index'],
                arm=ARM_NAMES.get(row['arm'], row['arm']), slot=row['slot'],
                transaction_index=row['transaction_index'], block_time=_utc(row['block_time']),
                action=row['intent'], blocking_reasons=', '.join(row['blocking_reasons']),
                score=row.get('score'), sol_usd=value, sol_usd_source=source, sol_usd_age_ms=age,
                signature=row['signature'], transaction=transaction_link(row['signature'])))
    return rows


def cycle_rows(document):
    """Research BUY->SELL cycles; [] when none (the P&L is then empty, never zero)."""
    label, _reasons = bundle_labels(document)
    rows = []
    for pool in document['pools']:
        for arm, trade in sorted(pool['arms'].items()):
            if trade.get('outcome') in (None, 'no_entry'):
                continue
            fees = (trade.get('tx_costs') or 0) + (trade.get('failed_attempt_costs') or 0)
            rows.append(dict(
                label=label, pool=pool['pool'], mint=pool.get('mint'),
                arm=ARM_NAMES.get(arm, arm), outcome=trade['outcome'],
                entry_slot=trade.get('entry_slot'), entry_time=_utc(trade.get('entry_block_time')),
                entry_transaction=transaction_link(trade.get('entry_signature')),
                exit_slot=trade.get('exit_slot'), exit_time=_utc(trade.get('exit_block_time')),
                exit_transaction=transaction_link(trade.get('exit_signature')),
                exit_trigger=trade.get('exit_trigger'),
                buy_sol=_sol(trade.get('spent')),
                sell_sol=_sol(trade.get('received')) if trade.get('pnl_lamports') is not None else None,
                fees_sol=_sol(fees), failed_attempt_fees_modelled=document['flags'].get(
                    'failed_attempt_fees_modelled'),
                pnl_sol=_sol(trade.get('pnl_lamports')),
                mark_pnl_sol=_sol(trade.get('mark_pnl_lamports'))))
    return rows


def summary(document, verification):
    label, reasons = bundle_labels(document)
    flags = document['flags']
    cycles = cycle_rows(document)
    closed = [row for row in cycles if row['pnl_sol'] is not None]
    return dict(
        label=label, label_reasons=reasons, verification=verification,
        pools=len(document['pools']),
        decisions=sum(len(pool['journal']) for pool in document['pools']),
        entries=sum(row['action'] == 'ENTER' for row in decision_rows(document)),
        closed_cycles=len(closed),
        pnl_sol_by_arm={arm: round(sum(r['pnl_sol'] for r in closed if r['arm'] == arm), 9)
                        for arm in sorted({r['arm'] for r in closed})} or None,
        sol_usd_verified=flags.get('sol_usd_verified'),
        source_clock_verified=flags.get('source_clock_verified'),
        research_evidence_status=flags.get('research_evidence_status'),
        counted_in_master_gate=flags.get('counted_in_master_gate'),
        params_sha256=document.get('params_sha256'))


def committed_bundles(root):
    """Verify the committed bundle(s) listed in the results registry; refusals are returned."""
    root = Path(root)
    registry = load_results_registry(root)
    loaded, refused = [], []
    for entry in registry.values():
        if entry['committed_path'] is None:
            continue
        path = root / entry['committed_path']
        try:
            if not path.is_file() or path.is_symlink():
                raise BundleRefused('committed_bundle_missing')
            loaded.append(verify_bundle(path.read_bytes(), registry=registry, name=entry['committed_path']))
        except BundleRefused as exc:
            refused.append(dict(name=entry['committed_path'], reason=str(exc)))
    return loaded, refused


# Sections that must exist but stay empty until a genuine producer exists.
EMPTY_SECTIONS = dict(
    PROSPECTIVE_PAPER='Aucun bundle PROSPECTIVE_PAPER : le producteur prospectif n\'existe pas encore.',
    REAL='Aucune opération réelle : ce tableau de bord ne passe, ne signe et ne lit aucun ordre.')

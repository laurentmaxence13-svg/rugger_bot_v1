"""Fail-closed registry/decoder for Raydium LaunchLab and CPMM program activity.

Offline only: no network, no signing, PAPER research. Standalone module (does not
touch ``observer24h``). Every identifier carries an explicit evidence status:

* ``VERIFIED_FIXTURE``: observed in a signed-transaction fixture of this repo
  (tests assert it, see ``tests/test_launchlab_program_decoder.py``).
* ``DERIVED_UNVERIFIED``: Anchor sha256 name hash computed locally, but NO fixture
  proves the instruction/event name or layout. Never used to classify as known.
* ``UNKNOWN``: nothing established.

Unproven items are reported as ``kind='unproven'``/``'unknown'``; nothing is invented.
"""
from dataclasses import dataclass
import hashlib

from bot.market.launchlab_events import (
    EVENT_IX_TAG, LAUNCHLAB_PROGRAM, TRADE_EVENT_DISCRIMINATOR, EventDecodeError, b58decode,
)

CPMM_PROGRAM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'  # also used in bot/live/cpmm_swap.py
VERIFIED_FIXTURE = 'verified_fixture'
DERIVED_UNVERIFIED = 'derived_unverified'
UNKNOWN = 'unknown'

# Program ids: LaunchLab seen as programId of inner instructions in 8 repo fixtures.
# CPMM id appears in repo code only; NO CPMM transaction fixture exists.
PROGRAM_EVIDENCE = {
    LAUNCHLAB_PROGRAM: VERIFIED_FIXTURE,
    CPMM_PROGRAM: DERIVED_UNVERIFIED,
}


def anchor_ix(name):
    return hashlib.sha256(('global:' + name).encode()).digest()[:8]


def anchor_event(name):
    return hashlib.sha256(('event:' + name).encode()).digest()[:8]


# (program, discriminator bytes) -> (name, evidence)
_REGISTRY = {
    (LAUNCHLAB_PROGRAM, anchor_ix('buy_exact_in')): ('buy_exact_in', VERIFIED_FIXTURE),
    (LAUNCHLAB_PROGRAM, anchor_ix('sell_exact_in')): ('sell_exact_in', VERIFIED_FIXTURE),
}
# Names whose hash is computable but unproven by any fixture here.
_CANDIDATES = {
    LAUNCHLAB_PROGRAM: ('initialize', 'initialize_v2', 'buy_exact_out', 'sell_exact_out',
                        'migrate_to_amm', 'migrate_to_cpswap'),
    CPMM_PROGRAM: ('initialize', 'swap_base_input', 'swap_base_output'),
}
_CANDIDATE_MAP = {(p, anchor_ix(n)): n for p, names in _CANDIDATES.items() for n in names}
EVENT_TAG_EVIDENCE = VERIFIED_FIXTURE
TRADE_EVENT_EVIDENCE = VERIFIED_FIXTURE


@dataclass(frozen=True)
class Decoded:
    kind: str          # buy|sell|trade_event|unproven|unknown|failed_tx
    evidence: str
    name: str = ''
    detail: str = ''


def decode_instruction(program, data):
    """Classify raw instruction bytes. Fail-closed: only fixture-verified ids are known."""
    if program not in PROGRAM_EVIDENCE:
        return Decoded('unknown', UNKNOWN, detail='program_not_tracked')
    if not isinstance(data, (bytes, bytearray)) or len(data) < 8:
        return Decoded('unknown', UNKNOWN, detail='data_too_short')
    data = bytes(data)
    if program == LAUNCHLAB_PROGRAM and data.startswith(EVENT_IX_TAG):
        if data[8:16] == TRADE_EVENT_DISCRIMINATOR:
            return Decoded('trade_event', TRADE_EVENT_EVIDENCE, 'TradeEvent')
        return Decoded('unproven', UNKNOWN, detail='unrecognised_event_discriminator')
    disc = data[:8]
    hit = _REGISTRY.get((program, disc))
    if hit and PROGRAM_EVIDENCE[program] == VERIFIED_FIXTURE:
        return Decoded('buy' if hit[0].startswith('buy') else 'sell', hit[1], hit[0])
    cand = _CANDIDATE_MAP.get((program, disc))
    if cand:
        return Decoded('unproven', DERIVED_UNVERIFIED, cand, 'name_hash_matches_but_no_fixture')
    return Decoded('unknown', UNKNOWN, detail='unrecognised_discriminator')


def classify_transaction(tx):
    """Return [(Decoded, location, program)] for tracked programs; [] if tx failed.

    Raises EventDecodeError if the structure is unusable (never guesses).
    """
    res = tx.get('result', tx) if isinstance(tx, dict) else None
    if not isinstance(res, dict) or 'transaction' not in res or not isinstance(res.get('meta'), dict):
        raise EventDecodeError('not_a_transaction_result')
    meta = res['meta']
    if meta.get('err') is not None:
        return []
    if meta.get('innerInstructions') is None:
        raise EventDecodeError('inner_instructions_unavailable')
    msg = res['transaction']['message']
    keys = [k if isinstance(k, str) else k['pubkey'] for k in msg.get('accountKeys', [])]
    loaded = meta.get('loadedAddresses') or {}
    keys += list(loaded.get('writable', [])) + list(loaded.get('readonly', []))
    out = []
    streams = [('top', i, ix) for i, ix in enumerate(msg.get('instructions', []))]
    for g in sorted(meta['innerInstructions'], key=lambda g: g['index']):
        streams += [('inner:%d' % g['index'], j, ix) for j, ix in enumerate(g['instructions'])]
    for where, idx, ix in streams:
        pid = ix.get('programId')
        if pid is None:
            n = ix.get('programIdIndex')
            if not isinstance(n, int) or not 0 <= n < len(keys):
                raise EventDecodeError('program_index_out_of_range')
            pid = keys[n]
        if pid in PROGRAM_EVIDENCE:
            out.append((decode_instruction(pid, b58decode(ix.get('data', ''))), '%s/%d' % (where, idx), pid))
    return out


def link_evidence(decoded_list):
    """Lifecycle links. Only trades are demonstrable; creation/graduation/migration/CPMM
    pool links are reported ``unproven`` until a fixture establishes them."""
    kinds = {d.kind for d, _, _ in decoded_list}
    return {
        'trade': 'proven' if kinds & {'buy', 'sell', 'trade_event'} else 'absent',
        'creation': 'unproven', 'graduation': 'unproven',
        'migration': 'unproven', 'cpmm_pool': 'unproven',
    }

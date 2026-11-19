"""SOL/USD series in streaming: the FROZEN functions, without holding every collected transaction.

The frozen chain builds the W1 series with ``w1_run.pyth_entries`` (every transaction of the SOL/USD run in one
list, about 26 GiB for W1) then ``w1_run.sol_usd_series`` (``pyth_push.decode_entries``, the series document,
``refusals_by_utc_hour``). Of each transaction these functions only use: its chain position (``slot``,
``transactionIndex``), its ``blockTime``, its signature and error flag (``backfill.verify``), its decoded price
updates (``pyth_push.updates``) and the sha256 of its JSON (``pyth_push.evidence_sha256``).

``streaming_series()`` replaces, for the duration of a ``with`` block:
* ``backfill.read_segment`` by a reader that parses one segment with the frozen reader, computes for each row
  the two derived values with the FROZEN functions, and returns SLIM rows (the fields above only);
* ``pyth_push.updates`` and ``pyth_push.evidence_sha256`` by functions that give back, for a slim row, the value
  the frozen function gave for the full row (or re-raise the exception it raised, at the moment the frozen code
  asks for it); for any other row they are the frozen functions.
Inside the block the frozen ``pyth_entries`` and ``sol_usd_series`` run UNCHANGED: same checks, same order, same
errors, same bytes written (tested against the frozen chain, including adversarial rows). Memory: one parsed
segment at a time plus the slim rows.

``series()`` is the whole step. It first runs the frozen ``backfill.verify`` WITHOUT any replacement and requires
the verification made on the slim rows inside the block to give the same result.

EXPLORATORY ONLY: this is not the frozen chain; an official W1 verdict cannot use it (protocol R10).
"""
import contextlib
from pathlib import Path

from bot.market import backfill as bf
from bot.market import pyth_push
from bot.master_v2 import w1_run

_KEPT = ('signature', 'slot', 'transactionIndex', 'blockTime')
_UPDATES, _EVIDENCE = '\x00w1x_updates', '\x00w1x_evidence'


class StreamSeriesError(RuntimeError):
    pass


def _slim(row, frozen_updates, frozen_evidence):
    """The fields the frozen series functions read, with the values the frozen decoders give for the full row."""
    if not isinstance(row, dict):
        return row                                         # not an object: the frozen code fails on it as before
    slim = {key: row[key] for key in _KEPT if key in row}
    if 'meta' in row:
        meta = row['meta']
        slim['meta'] = {'err': meta.get('err')} if isinstance(meta, dict) and meta else meta
    try:
        found = frozen_updates(row)
    except Exception as exc:                               # raised later, IF and WHEN the frozen code asks for the updates
        slim[_UPDATES] = exc                               # (it never asks for a row without a chain position)
    else:
        slim[_UPDATES] = found
        if found:
            slim[_EVIDENCE] = frozen_evidence(row)
    return slim


@contextlib.contextmanager
def streaming_series():
    """Within the block, the frozen series functions work on slim rows (see the module docstring)."""
    frozen_read, frozen_updates, frozen_evidence = bf.read_segment, pyth_push.updates, pyth_push.evidence_sha256
    if getattr(frozen_read, 'w1x_streaming', False):
        raise StreamSeriesError('streaming_series_is_not_reentrant')

    def read_segment(path):
        return [_slim(row, frozen_updates, frozen_evidence) for row in frozen_read(path)]
    read_segment.w1x_streaming = True

    def updates(entry, **kwargs):
        if isinstance(entry, dict) and _UPDATES in entry:
            if (kwargs.get('feed_id', pyth_push.SOL_USD_FEED_ID), kwargs.get('price_account', pyth_push.SOL_USD_ACCOUNT)) != (
                    pyth_push.SOL_USD_FEED_ID, pyth_push.SOL_USD_ACCOUNT) or set(kwargs) - {'feed_id', 'price_account'}:
                raise StreamSeriesError('slim_rows_are_decoded_with_the_default_feed_only')
            value = entry[_UPDATES]
            if isinstance(value, Exception):
                raise value
            return list(value)
        return frozen_updates(entry, **kwargs)

    def evidence_sha256(entry):
        if isinstance(entry, dict) and _UPDATES in entry:
            if _EVIDENCE not in entry:
                raise StreamSeriesError('evidence_asked_for_a_row_without_update')
            return entry[_EVIDENCE]
        return frozen_evidence(entry)

    bf.read_segment, pyth_push.updates, pyth_push.evidence_sha256 = read_segment, updates, evidence_sha256
    try:
        yield
    finally:
        bf.read_segment, pyth_push.updates, pyth_push.evidence_sha256 = frozen_read, frozen_updates, frozen_evidence


def series(run_dir, s0, study_report, study_report_sha256, out):
    """The frozen series step on slim rows: writes ``out`` and ``out.decoding.json``; returns the details."""
    run_dir, out = Path(run_dir), Path(out)
    if out.exists() or Path(str(out) + '.decoding.json').exists():
        raise StreamSeriesError('output_exists')
    checked = bf.verify(run_dir)                           # the frozen verification, on the full rows
    with streaming_series():
        if bf.verify(run_dir) != checked:                  # the slim rows must verify exactly the same
            raise StreamSeriesError('verification_differs_on_slim_rows')
        entries = w1_run.pyth_entries(run_dir, s0)
        result = w1_run.sol_usd_series(entries, study_report, study_report_sha256, out)
    return dict(series_sha256=result.sha256, points=len(result.points), entries=len(entries),
                run_manifest_sha256=checked['manifest_sha256'])

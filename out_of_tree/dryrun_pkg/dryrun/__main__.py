"""``python -B -m dryrun JOURNAL.jsonl``: run the fixture cycle, print its P&L."""
import json
import sys

from .cycle import run_fixture_cycle
from .journal import verify_journal

if len(sys.argv) != 2:
    raise SystemExit('usage: python -B -m dryrun NEW_JOURNAL.jsonl')
harness, _, sold = run_fixture_cycle(sys.argv[1])
print(json.dumps(dict(
    dry_run=True, signed=False, submitted=False, funds_used=False,
    records=len(verify_journal(sys.argv[1])), journal_head_sha256=harness.journal.head,
    pnl=sold['pnl']), indent=2, sort_keys=True))

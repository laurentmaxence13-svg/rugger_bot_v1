"""Shared test fixtures.

Only one resource is managed here: ``ExecutionJournal`` objects created by
tests. Production code never creates a journal (the operator owns it), so a
test that opens one is responsible for closing it. Many tests build engines
through shared helpers and never reach a ``close()``; on Python 3.13 the
unclosed SQLite handle then raises ``ResourceWarning`` inside an unrelated
test under ``-W error``, and on Windows it keeps the journal file locked.

This fixture closes, at teardown, the journals each test opened. It does not
touch ``sqlite3.connect`` itself, so any connection leaked by production code
still surfaces as a ``ResourceWarning``.
"""
import pytest

from bot.live.journal import ExecutionJournal


@pytest.fixture(autouse=True)
def close_execution_journals_opened_by_the_test(monkeypatch):
    opened = []
    original_init = ExecutionJournal.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        opened.append(self)

    monkeypatch.setattr(ExecutionJournal, '__init__', tracking_init)
    yield opened
    for journal in opened:
        journal.close()  # sqlite3 close() is idempotent: already-closed journals are fine

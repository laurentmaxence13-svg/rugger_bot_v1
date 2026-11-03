# Legacy copies: `bot/bot/` and `tests/tests/`

Read-only inventory, 2026-11-03, from the checkout of `claude/launchlab-trade-events` at `4f2875d`. Nothing was deleted, moved or edited. Both trees are tracked by git.

## `bot/bot/`

- 66 files (60 `.py`), about 1.69 MB, all tracked. It has its own `__init__.py` files.
- Compared byte for byte with the file at the same relative path under `bot/`: 54 files are identical, 12 differ, 0 exist only here.
- The 12 that differ: `analyser/behavior_pipeline.py`, `analyser/creator_backtest_v25.py`, `analyser/creator_backtest_v26.py`, `analyser/multi_creator_research_engine.py`, `analyser/paper_trader.py`, `analyser/relay_analysis.py`, `analyser/research_pipeline.py`, `database/db.py`, `main.py`, `scanner/launch_detector.py`, `scanner/transaction_parser.py`, `solana/websocket.py`.
- `bot/bot/analyser/relay_analysis.py` does not parse: `unexpected indent` at line 783. It is the only syntax error among the 66 files.
- Junk names: zero-byte entries `analyser/auto_relay`, `analyser/creator`, `analyser/creator 1`, `analyser/cretor`, `analyser/v4`, and `analyser/__init__.py -ItemType File`. Duplicate download copies with ` (1)` / ` (4)` in the name: `creator_14_launches_analysis_v5 (4).py`, `creator_backtest_v18 (1).py`, `creator_backtest_v18 (4).py`, `price_impact_fixed (1).py`. These four are identical to their `bot/analyser/` counterparts.
- Many files in `bot/` have no counterpart here (for example `market/`, `dashboard/`, `p3/`, `analyser/paper_engine.py`, `scanner/supervision.py`), so this tree is an older snapshot, not a mirror.

## `tests/tests/`

- 6 files, all `.py`, about 16 KB, all tracked. No `__init__.py`.
- Against the same names under `tests/`: 2 identical (`test_behavior_pipeline.py`, `test_creator_backtest_v26.py`), 4 differ (`test_paper_engine.py`, which is empty here, `test_parser.py`, `test_research_pipeline.py`, `test_research_rpc.py`).

## Does anything import or run them?

- Search of every `.py`, `.md`, `.yml`, `.yaml`, `.toml`, `.cfg`, `.ini`, `.txt` file outside the two trees for `bot.bot` and `tests.tests`: no match. Inside the two trees: no match either.
- There is no `pytest.ini`, `setup.cfg`, `pyproject.toml` or `tox.ini`. The offline CI (`.github/workflows/offline-tests.yml:56`) and the documented commands run `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider -rfE`, so `tests/tests/` is excluded from collection on purpose.
- Because `bot/__init__.py` exists, `bot.bot` would be importable as a package, but nothing does it. Absolute imports such as `bot.analyser...` inside `bot/bot/` resolve to the top-level `bot/` package, not to the copy.
- Conclusion (demonstrated by search, not by execution): nothing active imports either tree. Not proven: use by an external script, a shortcut or a manual command outside this repository.

## Related backup files (outside the two trees, for context)

Tracked: `bot/analyser/final_decision_engine.py.avant_correctif`, `bot/analyser/paper_trader.py.avant_correctif`, `bot/analyser/paper_trader.py.bak_p0`, `bot/solana/websocket.py.bak`, `tests/test_paper_engine.py.bak`, `tests/test_parser.py.bak`.

## Not done

No deletion, move, rename or syntax fix. `AGENTS.md` forbids deleting these copies or treating them as active source without demonstration. Whether to archive or remove them is an owner decision.

# 2026-11-01 — First read-only causal markout audit on archived Helius captures

**Scope:** previously stored **public** GitHub Actions archives, processed offline with `bot.p3.conditional_market_markout.audit_report` (no fresh network calls, no orders, no secrets). All results are conservative model qualification only; no executed or verified-paper Master P&L is inferred.

| Archived workflow run | Archive JSON | Observations | Conditional S1→S2 models | Refusal | Original evidence SHA-256 (canonical JSON) |
|---|---|---:|---:|---|---|
| [41239391249](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41239391249) | `helius_early_signed_s1_s2.json` | 0 attempts | 0 | Prior sensor logged 8 events but selected no creation for S1 | `5251697b7bcc4428b2018d35494669018b46577b3d4fa0808635dfd26f73d8e3` |
| [41238437873](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41238437873) | `paper_signed_creations_asof_banks.json` | 1 | 0 | `invalid_root_account_or_non_SOL_pool` | `69f63077f5960e0a9d73317df1d7c55b9a303b8d92e046658624deaf9e979602` |
| [41239391249](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41239391249) | `paper_signed_creations_asof_banks.json` | 0 | 0 | No signed creation selected in bounded source | `1fe0c44af08058a8fbb1c591ecfad25d7be4fbb642b906ff3f8252ed2a2520bf` |

**Conclusion:** zero qualified conditional S1/S2 models in these three archived files, zero observed filled economic cycles and zero demonstrable Master/reference net edge. Two archives are from the same GitHub run and **must not** be counted as independent runs or creators. This audit checks structural integrity of the saved inputs, not on-chain reauthentication.

**Next run:** First validate fresh code (`tests/test_conditional_market_markout.py`, 10 pure no-network tests) and quota restoration. Then launch **one** opt-in prospective research workflow. Preserve the full captured log denominator; audit exact reasons for every unsigned/unsupported root, missing S1, failed exit, missing provider executable quote or insufficient external-cost observation. Any future positive conditional scenario remains a model markout, not a Master profit or real fill.

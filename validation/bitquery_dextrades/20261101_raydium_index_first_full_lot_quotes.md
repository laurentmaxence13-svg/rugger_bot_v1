# 2026-11-01 — Raydium public index S1/S2 full-lot PAPER quote evidence

Source: [GitHub Actions #41259451370](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41259451370), archive `rugger-index-first-41259451370` (immutable committed P3 journal + report + predeclared plan). The prospective P3 protocol was registered *before* market data collection; 20 request cap, 60-second deadline, 0.1 SOL nominal position.

## Acquisition outcome (not an executed strategy)

| Item | Observed |
|---|---:|
| Raydium index rows received | 100 |
| Candidates selected with fixed pre-provider-screen policy | 2 |
| HTTP public requests | 18 / 20 |
| Total elapsed | 16,253 ms |
| Provider HTTP 200 quotes | 6 / 6 |
| Provider modeled BUY lots fixed before follow-up | 2 |
| Provider modeled full-lot SELL quotes | 4 (2 immediate + 2 follow-up) |
| Approx. follow-up lag after initial BUY receipt | 14.9–15.0 s |
| Source quote block slot/time | **missing** |
| Creation signature matched in acquisition journal | 2 **provider/RPC-reported**, not independently reauthenticated by this quote audit |
| Applicable wallet network/ATA/priority costs | **unknown** |
| Transactions bought/settled | **0** |
| Qualified market economic cycles | **0** |
| Net Master vs reference P&L | **unknown** |

## Matched hypothetical exact-token-position quote pairs

The **selected** base mints are `9qSvf5uzaUCRvucCmTgLJcicFZXP5dJZN23ZxpYTqG5Q` and `7Cc78JVbBvzHJvbQcSw1vojQtng7zSSyJSHNbYBHgt2t`, both quoted against SOL.

| Base mint | Paper SOL input | Full modeled token BUY quantity (atomic) | Indicative full SELL proceeds (lamports) at initial and follow-up | Indicative difference from initial input (SOL) |
|---|---:|---:|---:|---:|
| `9qSvf5uzaUCRvucCmTgLJcicFZXP5dJZN23ZxpYTqG5Q` | 0.1 | 3,080,513,950,670 | 96,918,845 | **−0.003081155** |
| `7Cc78JVbBvzHJvbQcSw1vojQtng7zSSyJSHNbYBHgt2t` | 0.1 | 3,080,508,943,243 | 96,918,845 | **−0.003081155** |

Both follow-up provider responses returned the same indicative proceeds as their immediate counterpart in this capture. These are **quote deltas, not trade P&L**. Estimates incorporate the provider's output-side swap logic but cannot establish realized execution, applicable additional costs, or net profitability. The two mints may reflect correlated/identically parameterized pools; results are not a statistical independent strategy sample. Neither Master nor reference has a demonstrated executed admission decision.

**Next:** run `bot/p3/index_quote_roundtrip_audit.py` on the original archive or a new acquisition, verifying that every full sell quantity exactly equals the initial modeled BUY lot and the P3 journal hash-chain matches the externally retained `tail_hash`. Never substitute local receipt times for missing source quote times.

**Economic verdict:** `INSUFFICIENT DATA` (correct fail-closed). Position size does *not* fix negative indicative economics on these two observations.

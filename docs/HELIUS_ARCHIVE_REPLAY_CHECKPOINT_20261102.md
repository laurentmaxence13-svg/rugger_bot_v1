# Genuine signed-source evidence: offline Nov 1 replay

## Actual archived acquisition retrieved on 2026-11-02

These archives were retrieved from **existing** GitHub Actions runs without
new Helius, Solana RPC, paid provider requests or financial transactions.

| Run | Artifact ID | Duration | Events | Signed creation tx | SOL pool graphs | Frozen S1 | Genuine Master PAPER BUY/SELL |
|---|---:|---:|---:|---:|---:|---:|---:|
| [#41316007232](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41316007232) | 13087467272 | 90s | 63 | 1 | 0 | 0 | 0 |
| [#41318206470](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41318206470) | 13087923724 | 180s | 160 | 0 | 0 | 0 | 0 |

Exact archive `manifest.json` raw-byte SHA-256:
- 90s: `2778cd1fc7136da9baaae259ff921972f9225182082cbc6c00235042373f28f6`
- 180s: `75687ed50663cf493aee269a66cd848a008fdcd6ff74d453aa83cf6900564fe7`

The 90s run preserved one signer-classified creation, but its pool graph
was refused as non-native-SOL-quoted. The 180s run inspected a quota-bounded
subset of notifications and found zero qualifying signed creation candidates.
This is **not** a claim that no token launched during either capture.

The new `bot/p3/helius_signed_archive_audit.py` checks recorded raw source
SHA-256, canonical per-window summary hashes, all four linked evidence-file
hashes, event duplication, source/receipt linkage, authorized RPC quotas,
Master/benchmark no-fill states, and manifest totals. It reads ZIP files
without extracting paths and rejects oversized, duplicate, symlink and
traversal entries. It publishes no API keys, addresses or P&L claims.

A matching `helius-archive-replay-audit.yml` GitHub Actions workflow
downloads **only** these two fixed existing archived artifacts using the
repository's short-lived built-in GitHub token (`actions:read`). No Helius
secret is passed; no external RPC is called. The workflow fails closed when
the artifacts expire (GitHub retention is finite).

## Evidentiary scope

- **Archive byte integrity**: independently reproducible with SHA-256.
- **Cryptographic signature classification**: historically asserted by the
  original signed source verifier, but the ZIP auditor does **not** reverify
  the original compiled Solana transaction signature/message itself.
- **Complete event tape**: **not verified**. Sample selection and quotas
  can omit actual creations.
- **Provider independence**: **not verified** (existing Helius source only).
- **Genuine Master as-of ENTER + exact-lot BUY + costed SELL**: **not observed**.
- **Net P&L and measured Master/reference economic advantage**: **NULL**.

No stored artifact creates a valid non-forced Master entry. The original
Master's 50 qualified historical cycles and 20 independent creators remain
protected. These historical archives cannot be silently upgraded into
"successful trades" by backtesting a later outcome or substituting the
experimental DexScreener PAPER engine.

## Reproduction

Download GitHub Actions artifacts 13087467272 and 13087923724 (on an
authorized private-repository account). Run:

```bash
python -B -m bot.p3.helius_signed_archive_audit 90s.zip
python -B -m bot.p3.helius_signed_archive_audit 180s.zip
```

No key, network flag or wallet required by the auditor. Run the existing
isolated regression suite before merging any code; no merge to main is
authorized by this checkpoint.

## Next real blocker

The signed source acquisition has yet to produce a qualifying **native SOL**
LaunchLab seven-account graph with a complete contemporaneous feature tape.
Even then, a valid operational Master BUY requires the unchanged historical
evidence/health/capital/cost controls and independent full-size quote
observations. It must properly WAIT if any qualification is missing.

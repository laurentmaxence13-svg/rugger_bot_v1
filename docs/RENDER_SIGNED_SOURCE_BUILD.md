# Render signed-source deployment checkpoint (PAPER / read-only)

The current Render web service `rugger-master-readonly` is configured with
`python -m compileall -q render_status_service.py`. That command does **not**
install `requirements-render.txt`, leaving the cryptographic signed-source
runner unsupported. The current Render connector cannot change the build
command of an existing service; this PR does not claim to have deployed it.

After code review and explicit approval of the *Render feature branch* only,
the operator must update **that existing service** using the dashboard:

- Build command: `python -B -m bot.ops.render_readonly_build`
- Start command: `python render_status_service.py` (unchanged)
- Auto-deploy: OFF (unchanged)
- No merge to `main`; no new paid service or change of plan.

The isolated build helper installs only the existing declared free Python dependencies,
requires the independent Ed25519 verifier and imports the genuine signed Helius
read-only pipeline. If any step fails, the build exits nonzero. It does not
capture market data, read secrets, connect wallets or submit transactions.
Never paste API keys into source or CI; any future Helius key must be stored
only in Render server-side secret environment settings and its enablement
requires a separate, quota-bounded opt-in.

Post-deploy verification (not yet performed): GET `/healthz` and
`/api/helius`, check `no_signing_or_order_submission=true`,
`live_trading_enabled=false` and signed-source status. A successful build or
a signed-source observation is **not** a Master PAPER BUY/SELL, executable
price, P&L or demonstrated edge. Render Free sleeping/ephemeral storage means
24/7 autonomy and durable signed evidence are not guaranteed.

The separately labeled DexScreener hypothetical PAPER trades must never be
counted as genuine Master trades.

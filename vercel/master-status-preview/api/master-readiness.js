/**
 * Vercel-only public read-only proxy for Rugger Master signed-source status.
 *
 * The production Render service may still be deployed on its OLD branch and
 * return 404 at /api/master-readiness. That is a blocker, not a Master trade.
 * No wallet, Helius key, authentication token, private repo request,
 * DexScreener experimental feed or financial transaction is involved.
 */
const RENDER_URL = 'https://rugger-master-readonly.onrender.com/api/master-readiness';
const EXPECTED_SCHEMA = 'rugger-genuine-master-paper-readiness-v1';
const EXPECTED_SOURCE = 'HELIUS_SIGNED_LAUNCHLAB_ONLY';
const SOURCE_BLOCKERS = new Set([
  'SIGNED_OBSERVER_DISABLED',
  'SIGNED_SOURCE_UNCONFIGURED',
  'AWAITING_FIRST_SIGNED_CAPTURE',
  'SIGNED_CAPTURE_IN_PROGRESS',
  'SIGNED_CAPTURE_REFUSED',
  'UNRECOGNIZED_SIGNED_SOURCE_STATE',
  'SIGNED_EVIDENCE_MISSING_OR_STALE',
  'SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED',
  'SIGNED_SOURCE_COUNTERS_INCOMPLETE',
  'NO_SIGNED_LAUNCHLAB_CREATION',
  'NO_VERIFIED_SOL_QUOTED_POOL_GRAPH',
  'NO_FROZEN_CAUSAL_MASTER_DECISION',
  'NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH',
]);

const COMMON = Object.freeze({
  schema: 'rugger-vercel-master-readonly-bridge-v1',
  mode: 'GENUINE_MASTER_PAPER_READ_ONLY',
  status: 'NO_GO',
  master_buy_sell_paper_verified: false,
  master_net_pnl_sol: null,
  master_reference_edge_sol: null,
  experimental_dexscreener_excluded: true,
  financial_order_submitted: false,
  live_trading_enabled: false,
  requires_explicit_new_evidence_to_advance: true,
});

function refusal(reason) {
  return {
    ...COMMON,
    next_blocker: reason,
    verified_render_diagnostic: false,
    signed_evidence_fresh: false,
  };
}

export function assessRemoteReport(report) {
  if (!report || typeof report !== 'object' || Array.isArray(report) ||
      report.schema !== EXPECTED_SCHEMA ||
      report.source !== EXPECTED_SOURCE ||
      report.mode !== 'GENUINE_MASTER_PAPER_READ_ONLY' ||
      report.status !== 'NO_GO' ||
      !SOURCE_BLOCKERS.has(report.next_blocker) ||
      typeof report.signed_evidence_fresh !== 'boolean' ||
      report.master_buy_sell_paper_verified !== false ||
      report.master_net_pnl_sol !== null ||
      report.master_reference_edge_sol !== null ||
      report.experimental_dexscreener_excluded !== true ||
      report.financial_order_submitted !== false ||
      report.live_trading_enabled !== false ||
      report.requires_explicit_new_evidence_to_advance !== true) {
    return refusal('UNTRUSTED_MASTER_SOURCE_DIAGNOSTIC');
  }

  return {
    ...COMMON,
    source: EXPECTED_SOURCE,
    next_blocker: report.next_blocker,
    verified_render_diagnostic: true,
    signed_evidence_fresh: report.signed_evidence_fresh,
  };
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'GET_ONLY' });
  }

  let report = refusal('SIGNED_DIAGNOSTIC_UNAVAILABLE');
  try {
    const response = await fetch(RENDER_URL, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      redirect: 'error',
      cache: 'no-store',
      signal: AbortSignal.timeout(6500),
    });
    if (response.status === 404) {
      report = refusal('RENDER_MASTER_READINESS_NOT_DEPLOYED');
    } else if (response.ok) {
      // Refuse over-large, provider-controlled JSON, even if HTTP is healthy.
      const size = response.headers.get('content-length');
      if (size !== null && (!/^\d+$/.test(size) || Number(size) > 16384)) {
        report = refusal('OVERSIZED_MASTER_SOURCE_DIAGNOSTIC');
      } else {
        const raw = await response.text();
        if (raw.length <= 16384) {
          report = assessRemoteReport(JSON.parse(raw));
        } else {
          report = refusal('OVERSIZED_MASTER_SOURCE_DIAGNOSTIC');
        }
      }
    }
  } catch {
    // Never leak a private URL, source response, secrets or stack trace.
    report = refusal('SIGNED_DIAGNOSTIC_UNAVAILABLE');
  }

  return res.status(200).json({
    ...report,
    observed_at_utc: new Date().toISOString(),
    data_is_not_a_financial_trade: true,
  });
}

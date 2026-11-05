import test from 'node:test';
import assert from 'node:assert/strict';
import handler, { assessRemoteReport } from '../api/master-readiness.js';

const signedSafeReport = {
  schema: 'rugger-genuine-master-paper-readiness-v1',
  source: 'HELIUS_SIGNED_LAUNCHLAB_ONLY',
  mode: 'GENUINE_MASTER_PAPER_READ_ONLY',
  status: 'NO_GO',
  next_blocker: 'NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH',
  signed_evidence_fresh: true,
  master_buy_sell_paper_verified: false,
  master_net_pnl_sol: null,
  master_reference_edge_sol: null,
  experimental_dexscreener_excluded: true,
  financial_order_submitted: false,
  live_trading_enabled: false,
  requires_explicit_new_evidence_to_advance: true,
};

function fakeResponse() {
  const response = { headers: {}, code: null, body: null };
  response.setHeader = (key, value) => { response.headers[key] = value; };
  response.status = code => { response.code = code; return response; };
  response.json = body => { response.body = body; return response; };
  return response;
}

test('trusted signed-only diagnostic is still strictly NO-GO with unknown PnL', () => {
  const r = assessRemoteReport(signedSafeReport);
  assert.equal(r.verified_render_diagnostic, true);
  assert.equal(r.next_blocker, 'NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH');
  assert.equal(r.status, 'NO_GO');
  assert.equal(r.master_buy_sell_paper_verified, false);
  assert.equal(r.master_net_pnl_sol, null);
  assert.equal(r.financial_order_submitted, false);
});

test('dangerous or DexScreener-like reports cannot promote a trade or PnL', () => {
  const violations = [
    { source: 'DEXSCREENER_EXPERIMENT' },
    { status: 'READY' },
    { financial_order_submitted: true },
    { live_trading_enabled: true },
    { master_buy_sell_paper_verified: true },
    { master_net_pnl_sol: 4.8 },
    { master_reference_edge_sol: 1.2 },
    { next_blocker: 'UNVERIFIED_EXTERNAL_BODY' },
    { experimental_dexscreener_excluded: false },
    { signed_evidence_fresh: 'yes' },
  ];
  for (const violation of violations) {
    const r = assessRemoteReport({ ...signedSafeReport, ...violation });
    assert.equal(r.verified_render_diagnostic, false);
    assert.equal(r.status, 'NO_GO');
    assert.equal(r.master_net_pnl_sol, null);
    assert.equal(r.master_buy_sell_paper_verified, false);
    assert.equal(r.financial_order_submitted, false);
  }
});

test('invalid/missing evidence remains NO-GO', () => {
  for (const x of [null, undefined, [], {}, { status: 'GO' }]) {
    const r = assessRemoteReport(x);
    assert.equal(r.verified_render_diagnostic, false);
    assert.equal(r.live_trading_enabled, false);
  }
});

test('GET requests only; no network on rejected methods', async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('network_called'); };
  try {
    const response = fakeResponse();
    await handler({ method: 'POST' }, response);
    assert.equal(response.code, 405);
    assert.deepEqual(response.body, { error: 'GET_ONLY' });
    assert.equal(response.headers.Allow, 'GET');
  } finally {
    globalThis.fetch = prev;
  }
});

test('Render not deployed reports exact blocker without fabrication', async () => {
  const prev = globalThis.fetch;
  let called = 0;
  globalThis.fetch = async (url, init) => {
    called++;
    assert.equal(url, 'https://rugger-master-readonly.onrender.com/api/master-readiness');
    assert.equal(init.method, 'GET');
    assert.equal(init.redirect, 'error');
    return { status: 404, ok: false };
  };
  try {
    const response = fakeResponse();
    await handler({ method: 'GET' }, response);
    assert.equal(called, 1);
    assert.equal(response.code, 200);
    assert.equal(response.body.next_blocker, 'RENDER_MASTER_READINESS_NOT_DEPLOYED');
    assert.equal(response.body.status, 'NO_GO');
    assert.equal(response.body.master_net_pnl_sol, null);
    assert.equal(response.headers['Cache-Control'], 'no-store, max-age=0');
  } finally {
    globalThis.fetch = prev;
  }
});

test('trusted Render report exposes only allowlisted typed fields', async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    text: async () => JSON.stringify({ ...signedSafeReport, secret: 'NEVER_EXPOSE',
      master_wallet: 'never', new_metric: 999 }),
  });
  try {
    const response = fakeResponse();
    await handler({ method: 'GET' }, response);
    assert.equal(response.code, 200);
    assert.equal(response.body.verified_render_diagnostic, true);
    assert.equal(response.body.source, 'HELIUS_SIGNED_LAUNCHLAB_ONLY');
    assert.equal(response.body.secret, undefined);
    assert.equal(response.body.master_wallet, undefined);
    assert.equal(response.body.master_net_pnl_sol, null);
    assert.equal(typeof response.body.observed_at_utc, 'string');
  } finally {
    globalThis.fetch = prev;
  }
});

test('untrusted error text is not disclosed', async () => {
  const prev = globalThis.fetch;
  const synthetic = 'secret-key-in-error-NEVER-ECHO';
  globalThis.fetch = async () => { throw new Error(synthetic); };
  try {
    const response = fakeResponse();
    await handler({ method: 'GET' }, response);
    assert.equal(response.code, 200);
    assert.equal(response.body.next_blocker, 'SIGNED_DIAGNOSTIC_UNAVAILABLE');
    assert.equal(JSON.stringify(response.body).includes(synthetic), false);
    assert.equal(response.body.master_buy_sell_paper_verified, false);
  } finally {
    globalThis.fetch = prev;
  }
});

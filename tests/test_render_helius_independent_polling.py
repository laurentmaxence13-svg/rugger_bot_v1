"""Offline browser-polling regression: Helius is independent of DexScreener.

The Node VM test supplies mock endpoints and DOM only. No network, keys,
wallet, financial transactions, or live provider access.
"""
import shutil
import subprocess

import pytest

import render_status_service as app


def _script():
    return app.PAGE.split("<script>", 1)[1].split("</script>", 1)[0]


def test_signed_source_has_separate_polling_and_refresh_timer():
    script = _script()
    assert script.count("fetch('/api/helius'") == 1
    assert script.count("fetch('/api/status'") == 1
    assert "async function drawHelius()" in script
    market = script.split("async function draw(){", 1)[1]
    assert "fetch('/api/helius'" not in market
    assert "draw();drawHelius();" in script
    assert "setInterval(draw,15000)" in script
    assert "setInterval(drawHelius,15000)" in script


def test_signed_status_renders_even_when_market_endpoint_fails():
    if shutil.which("node") is None:
        pytest.skip("Node.js unavailable; structural polling test still runs")
    driver = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const script = fs.readFileSync(0, 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: '', replaceChildren() {}, appendChild() {}
  });
  return elements.get(id);
}
const document = {
  getElementById: element,
  createElement() { return {textContent:'', appendChild(){}}; }
};
const calls = [];
const timers = [];
async function fetch(url) {
  calls.push(url);
  if (url === '/api/status') throw new Error('market API unavailable');
  if (url === '/api/helius') return {
    ok: true,
    json: async () => ({
      observer_status: 'CAPTURE_COMPLETED_READ_ONLY',
      cycle_count: 2,
      last_summary: {crypto_signed_creation_transactions: 1,
                     frozen_S1_decisions: 0}
    })
  };
  throw new Error('unexpected endpoint: ' + url);
}
vm.runInNewContext(script, {
  document, fetch, setInterval: (fn, ms) => timers.push([fn.name, ms])
});
setImmediate(() => {
  if (!calls.includes('/api/status') || !calls.includes('/api/helius'))
    throw new Error('Both endpoints must be polled independently');
  if (!element('health').textContent.includes('Service indisponible'))
    throw new Error('Market outage was not handled');
  if (!element('helius-state').textContent.includes('CAPTURE_COMPLETED_READ_ONLY'))
    throw new Error('Signed Helius status disappeared during market outage');
  if (!element('helius-counts').textContent.includes('créations signées confirmées : 1'))
    throw new Error('Signed counts did not render');
  if (timers.length !== 2 || !timers.some(t => t[0] === 'drawHelius' && t[1] === 15000))
    throw new Error('Independent Helius refresh timer missing');
  process.stdout.write('independent_signed_source_polling_ok');
});
"""
    result = subprocess.run(
        ["node", "-e", driver], input=_script(), text=True,
        capture_output=True, timeout=8, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "independent_signed_source_polling_ok"

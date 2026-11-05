"""Offline UI regression: a Helius outage must invalidate displayed signed counters.

Node VM runs mock endpoints only; no provider calls, secrets, wallets or orders.
"""
import shutil
import subprocess

import pytest

import render_status_service as app


def _script():
    return app.PAGE.split("<script>", 1)[1].split("</script>", 1)[0]


def test_helius_failure_clears_prior_counts_without_error_detail():
    script = _script()
    assert "Aucun compteur Helius vérifiable actuellement." in script
    assert "el('helius-counts').textContent='Aucun compteur Helius vérifiable actuellement.'" in script
    if shutil.which("node") is None:
        pytest.skip("Node.js unavailable; structural fail-closed checks still run")

    driver = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const script = fs.readFileSync(0, 'utf8');
const elements = new Map();
const timers = [];
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
let mode = 'ok';
async function fetch(url) {
  if (url === '/api/status') throw Error('experimental market offline');
  if (url !== '/api/helius') throw Error('unexpected endpoint');
  if (mode === 'network') throw Error('HELIUS_API_KEY=FAKE_SECRET_DO_NOT_DISPLAY');
  if (mode === 'http') return {ok:false, status:503};
  return {
    ok:true,
    json:async () => ({
      observer_status:'CAPTURE_COMPLETED_READ_ONLY',
      cycle_count:4, successful_capture_count:3, refused_capture_count:1,
      last_summary:{crypto_signed_creation_transactions:2, frozen_S1_decisions:0}
    })
  };
}
vm.runInNewContext(script, {
  document, fetch, setInterval:(fn, ms)=>timers.push({fn, ms})
});
function check(condition, message) { if (!condition) throw Error(message); }
setImmediate(async () => {
  try {
    const refresh = timers.find(t => t.fn.name === 'drawHelius');
    check(refresh && refresh.ms === 15000, 'independent Helius refresh missing');
    check(element('helius-counts').textContent.includes('Tentatives : 4'),
          'initial signed evidence missing');
    for (const failure of ['network', 'http']) {
      mode = failure;
      await refresh.fn();
      check(element('helius-state').textContent.includes('non vérifiables'),
            'Helius failure must be explicit');
      check(element('helius-counts').textContent ===
            'Aucun compteur Helius vérifiable actuellement.',
            'previous signed counters remain stale on ' + failure);
      check(!element('helius-state').textContent.includes('FAKE_SECRET'),
            'untrusted error text exposed');
    }
    mode = 'ok';
    await refresh.fn();
    check(element('helius-counts').textContent.includes('Tentatives : 4'),
          'signed evidence did not recover after outage');
    check(element('health').textContent.includes('Service indisponible'),
          'experimental market outage must remain independent');
    process.stdout.write('signed_helius_stale_ui_fail_closed_ok');
  } catch (error) {
    process.stderr.write(String(error));
    process.exitCode = 1;
  }
});
"""
    result = subprocess.run(
        ["node", "-e", driver], input=script, text=True,
        capture_output=True, timeout=8, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "signed_helius_stale_ui_fail_closed_ok"

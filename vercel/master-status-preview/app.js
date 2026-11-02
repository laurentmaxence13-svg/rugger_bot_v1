/* UI for the GENUINE read-only Master; never use the experimental PAPER feed. */
const reasonLabels = Object.freeze({
  SIGNED_OBSERVER_DISABLED: 'Le collecteur signé est désactivé sur Render.',
  SIGNED_SOURCE_UNCONFIGURED: 'Le collecteur signé n’est pas configuré.',
  AWAITING_FIRST_SIGNED_CAPTURE: 'En attente de la première acquisition de preuves signées.',
  SIGNED_CAPTURE_IN_PROGRESS: 'Acquisition signée en cours. Aucun cycle Master qualifié.',
  SIGNED_CAPTURE_REFUSED: 'L’acquisition a été refusée ; vérifier les journaux côté serveur.',
  UNRECOGNIZED_SIGNED_SOURCE_STATE: 'État de la source signée non reconnu.',
  SIGNED_EVIDENCE_MISSING_OR_STALE: 'Les dernières preuves signées sont absentes ou périmées.',
  SIGNED_SOURCE_SAFETY_INVARIANT_UNVERIFIED: 'Les protections de la source signée ne sont pas démontrées.',
  SIGNED_SOURCE_COUNTERS_INCOMPLETE: 'Compteurs de preuves signées incomplets.',
  NO_SIGNED_LAUNCHLAB_CREATION: 'Aucune création LaunchLab signée admissible dans cet échantillon.',
  NO_VERIFIED_SOL_QUOTED_POOL_GRAPH: 'Aucun graphe de pool coté en SOL qualifié.',
  NO_FROZEN_CAUSAL_MASTER_DECISION: 'Aucune décision causale Master S1 vérifiée.',
  NO_QUALIFIED_MASTER_PAPER_BUY_SELL_PATH: 'Aucun cycle complet BUY/SELL PAPER du vrai Master vérifié.',
  RENDER_MASTER_READINESS_NOT_DEPLOYED: 'La nouvelle API Master n’est pas encore déployée sur Render.',
  SIGNED_DIAGNOSTIC_UNAVAILABLE: 'La source signée Render est momentanément inaccessible.',
  OVERSIZED_MASTER_SOURCE_DIAGNOSTIC: 'La réponse du diagnostic Render dépasse la limite autorisée.',
  UNTRUSTED_MASTER_SOURCE_DIAGNOSTIC: 'Le diagnostic Render ne correspond pas au schéma sécurisé.',
});

function text(id, value) {
  document.getElementById(id).textContent = value;
}

function renderStatus(payload) {
  // Only the signed source can be displayed. This page must NEVER infer a
  // trade, position, profit or LIVE status from a DexScreener demo feed.
  if (!payload || payload.status !== 'NO_GO' ||
      payload.financial_order_submitted !== false ||
      payload.live_trading_enabled !== false ||
      payload.master_buy_sell_paper_verified !== false ||
      payload.master_net_pnl_sol !== null ||
      payload.experimental_dexscreener_excluded !== true) {
    throw new Error('UNTRUSTED_STATUS');
  }
  text('status', 'NO-GO');
  text('executions', 'NON VÉRIFIÉE');
  text('pnl', 'INCONNU');
  text('live', 'DÉSACTIVÉES');
  const trusted = payload.verified_render_diagnostic === true;
  text('notice', trusted
    ? 'Diagnostic signé disponible. Master PAPER non autorisé à entrer.'
    : 'Diagnostic signé non encore disponible ; statut conservateur.');
  text('blocker', reasonLabels[payload.next_blocker] ||
    'Preuve nécessaire non encore qualifiée.');
  text('source', trusted
    ? (payload.signed_evidence_fresh === true
      ? 'Source signée vérifiée au dernier contrôle ; aucune exécution Master prouvée.'
      : 'Source signée vérifiée, mais ses données ne sont pas actuellement fraîches.')
    : 'Données du Master non vérifiables sur l’hébergement actif.');
  const t = Date.parse(payload.observed_at_utc);
  text('updated', Number.isFinite(t)
    ? 'Dernier contrôle : ' + new Date(t).toLocaleString('fr-FR')
    : 'Dernier contrôle : inconnu');
}

async function refresh() {
  try {
    const r = await fetch('/api/master-readiness', {
      method: 'GET', cache: 'no-store', signal: AbortSignal.timeout(9000)
    });
    if (!r.ok) throw new Error('HTTP_NOT_OK');
    renderStatus(await r.json());
  } catch {
    text('notice', 'Statut non vérifiable ; aucune opération Master prouvée.');
    text('blocker', 'Diagnostic temporairement inaccessible.');
    text('source', 'Aucun compteur ou P&L Master ne peut être validé actuellement.');
    text('updated', 'Dernier contrôle : échec de la vérification');
  }
}
refresh();
setInterval(() => {
  if (document.visibilityState === 'visible') refresh();
}, 30000);

# Historique LaunchLab et rejeu causal — 2 novembre 2026

Statut : **PAPER / lecture seule**. Aucune transaction, aucun portefeuille, aucune clé, aucun ordre.

## Démontré (preuves reproductibles)

- **Décodage exact** des événements `TradeEvent` : 7 transactions finalisées réelles (1 achat, 6 ventes) reproduites au lamport près (`tests/test_launchlab_market_events.py`).
- **Collecte complète** de 3 pools cotés en SOL (133, 38 et 2 signatures), sans trou, sans trade rejeté, avec archives brutes locales (`data/launchlab_trades`, ignoré par git).
- **Barème de frais unique par pool**, mais différent d'un pool à l'autre : 12 500, 10 000 et 18 000 ppm. Le taux par défaut de 12 500 ppm serait faux pour deux de ces pools : la calibration par pool est obligatoire.
- **Garde-fous testés** : rejeu refusé pour un pool non coté en SOL ; événements à état de courbe invalide signalés, sans plantage ; historique incomplet refusé ; listing non raccordé refusé sans fusion.

## Anecdotique (pas une preuve)

Stratégie de référence, fixée avant exécution et non optimisée : acheter 0,05 SOL après le 3e trade observé, sortir après 30 slots (`tools/launchlab_baseline_report.py`, hors ligne).

| Pool (SOL) | Résultat | P&L net |
|---|---|---|
| `C7F9…` (100 trades) | sortie après 35 slots | +0,0029 SOL (+5,8 %) |
| `5pZ6…` (11 trades) | sortie après 32 slots | −0,0050 SOL (−10,1 %) |
| `DVP4…` (2 trades) | aucune entrée | — |

Deux entrées ne permettent aucune conclusion statistique. Verdict économique : **INSUFFICIENT_DATA**.

## Non démontré et limites

- **Biais de sélection** : pools trouvés à partir des 40 dernières transactions du programme, donc récents et actifs. Pas d'échantillon représentatif, pas de pools morts.
- **Coûts** : frais de transaction = médiane des `meta.fee` observés ; frais de priorité non modélisés ; loyers de compte supposés remboursés ; pas de glissement au-delà de la courbe exacte.
- **Latence** : 2 slots, hypothèse non mesurée.
- **Migration** : une position qui franchit la migration est marquée `migrated_unpriced`, jamais valorisée en profit.
- **Impact** : les trades réels suivants sont rejoués sur la courbe modifiée par notre achat ; hypothèse que les autres acteurs ne réagissent pas.

## Découvertes techniques

- Le RPC rejette les transactions de **version 1** si `maxSupportedTransactionVersion` vaut 0 (erreur `-32015`). Le collecteur demande désormais la version 1.
- Le pool de référence des fixtures (`5BFfim…`) est coté en `TSM2…` (non SOL, 6 décimales), confirmé via son compte de configuration. Il ne sert donc pas au P&L en SOL.
- Un intermédiaire erroné de mon outil (rejeu d'un pool non SOL, `CyAzra…`) a été détecté et corrigé avant publication ; le garde-fou a été contourné par l'appelant, pas par le moteur. Un test de non-régression le couvre désormais.

## Reproduire

```sh
python -B -m pytest -q tests/test_launchlab_market_events.py tests/test_launchlab_collector.py tests/test_launchlab_replay.py tests/test_launchlab_baseline_report.py -p no:cacheprovider -W error
python -B tools/launchlab_baseline_report.py   # hors ligne, lit data/launchlab_trades
python -B tools/collect_launchlab_trades.py summarize
```

Consommation RPC de la session : **environ 520 appels Helius** en lecture seule (estimation), plus une quinzaine de requêtes sur le RPC public gratuit.

## Suite

1. Échantillon représentatif avant toute conclusion : découverte élargie, pools morts inclus. Coût à budgéter avec accord.
2. Mesurer la latence réelle (soumission vs slot) au lieu de la fixer.
3. Comparer la décision Master (branche de la PR #89) sur les mêmes pools, mêmes horodatages et mêmes coûts.

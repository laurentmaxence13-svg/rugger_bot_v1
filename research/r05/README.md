# R05 — RUGGER QUANT RESEARCH

Laboratoire indépendant de recherche multi-stratégies de RUGGER MASTER.
Ouvert le 2026-11-26. Responsable : R05. Rend compte au propriétaire.

## Périmètre et garde-fous

- **PAPER ONLY.** Aucun ordre, aucune signature, aucune clé privée, aucun transfert.
  Le code de ce dossier ne contient aucun client authentifié d'exchange.
- **Données publiques gratuites uniquement** (archive publique Binance, API publiques
  OKX, Coinbase, Kraken, Deribit, Hyperliquid, DefiLlama, GeckoTerminal, Raydium, Jupiter).
  Aucune clé API. Aucun crédit Helius consommé par R05.
- Les hôtes qui refusent l'accès depuis le conteneur (`api.binance.com`, `fapi.binance.com`
  → HTTP 451 ; `api.bybit.com` → 403) **ne sont pas contournés**.
- Aucune modification de `bot/`, `tests/`, des bases SQLite, de `.env`, ni des
  protocoles gelés G2-3 / N1 / livepaper de R01–R04. R05 lit leurs enseignements, rien de plus.
- Tout est reproductible : chaque fichier téléchargé est vérifié (CHECKSUM officiel quand
  il existe) et inscrit avec son sha256 dans `results/DATA_MANIFEST_*.json`.
  Les données brutes vont dans `research/r05/data/` (ignoré par git, voir `.gitignore` racine).
- Ordre des preuves : protocole pré-enregistré et commité **avant** le téléchargement
  des données ; résultats commités ensuite, sans modifier le protocole.
  Toute déviation est inscrite dans `docs/REGISTRE_DEVIATIONS_DEFAUTS.md`.

## Structure

| Chemin | Contenu |
|---|---|
| `docs/R05_PREREGISTRATION_v1.md` | hypothèses, données, découpages, critères d'admission/rejet — figés |
| `docs/R05_DOSSIER.md` | diagnostic, résultats, comparaison, recommandation |
| `docs/REGISTRE_DEVIATIONS_DEFAUTS.md` | défauts (cause → correction → prévention) et déviations |
| `r05lab/` | noyau : données+manifeste, coûts, backtest, statistiques, LP, microstructure |
| `experiments/` | un script par expérience, déterministe |
| `tests/` | tests unitaires (aucun réseau) |
| `results/` | sorties JSON/MD des expériences |

## Reproduire

```bash
cd research/r05
export PYTHONDONTWRITEBYTECODE=1
python -m pytest -q -p no:cacheprovider tests          # aucun réseau
python -m experiments.fetch_binance                    # télécharge + vérifie (réseau)
python -m experiments.s2_systematic                    # E-S2 (hors ligne une fois les données là)
```

Dépendances : Python ≥ 3.11, numpy, pandas, requests. Rien d'autre.

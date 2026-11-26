# R05 — Registre des déviations et des défauts

Chaque entrée : constat factuel → cause racine → correction → prévention. Une entrée n'est
close que lorsque la prévention est en place.

| # | Date (UTC) | Constat | Cause racine | Correction | Prévention | État |
|---|---|---|---|---|---|---|
| R05-D1 | 2026-11-26 13:20 | Aucune source historique de marché accessible depuis le conteneur (proxy 403 ; Pyth Hermes historique 401) | environnement par défaut limité aux hôtes Helius/Pyth/docs | environnement personnel « rugger_bot_v1 R05 market data » approuvé par le propriétaire (hôtes publics gratuits, sans clé) | test d'accès en tête de chaque collecte ; aucun résultat simulé à la place d'une donnée absente | clos |
| R05-D2 | 2026-11-26 13:25 | `api.binance.com`, `fapi.binance.com` → 451 ; `api.bybit.com` → 403 | restriction géographique du conteneur | aucune ; seule l'archive statique publique `data.binance.vision` est utilisée | ne jamais contourner un refus géographique ; signaler | ouvert (limite déclarée) |

# MASTER V2 — Banc de recherche des politiques challengers (MASTER RESEARCH)

Préparé le 2026-11-07 par RUGGER 01 sur la branche locale `claude/r01-master-v2-research`,
issue de `e21c32c` (correctifs L1 P0 audités PASS par RUGGER 02).

Ce banc n'est **ni** une politique opérationnelle, **ni** une source pour le registre PAPER, **ni** une preuve pour la porte de 50 cycles et 20 créateurs. La politique figée et ses résultats historiques ne changent pas.

## 1. Pourquoi ce banc

- Le scoreur actuel s'exprime en dollars. Sans série SOL/USD causale, toutes ses décisions attendent (`sol_usd_rate_unavailable`).
- Sur les données P0, avec un cours déclaré, il ne produit qu'un seul bras distinct : le bras MASTER est identique à `early_sniping`.
- Pour comparer de vraies politiques indépendantes, il faut des décisions qui :
  - ne lisent que le passé (`events[:k+1]`) ;
  - s'expriment directement en lamports et en atomes de token, donc **sans SOL/USD** ;
  - s'exécutent avec exactement la même comptabilité que le rejeu L1 audité.

## 2. Composants

| Module | Rôle |
|---|---|
| `bot/master_v2/features.py` | Caractéristiques causales natives SOL à l'événement de décision : âge, activité, acheteurs uniques, flux net par fenêtre, progression de la courbe, prix par rapport au lancement et au pic, achats et ventes du créateur, parts des plus gros détenteurs, payeurs des premiers slots. |
| `bot/master_v2/harness.py` | `Policy` (ENTER / WAIT / NO_TRADE, ce dernier étant définitif pour le pool) et `PolicyArm`. Le banc réutilise `bot.market.replay` (latence, impact propre, frais causaux) et `usable_timeline`, `_trade`, `_migrated` du rejeu L1. Les sorties portent sur la valeur de liquidation exacte de la position, dans l'ordre de priorité opérationnel : stop-loss, stop suiveur, sortie avant migration, durée maximale, prise de profit. Aucune décision n'est prise au milieu d'une transaction. |
| `bot/master_v2/policies.py` | Placebos `placebo-no-trade` et `placebo-random-entry` ; diagnostic `diagnostic-fixed-delay` (courbe rendement / moment d'entrée) ; familles `immediate-snipe`, `delayed-confirmation` et `fill-momentum`. Les paramètres par défaut sont des points de départ non réglés. |
| `bot/master_v2/lifecycle.py` | Cycle de vie de chaque pool, sans aucune politique : pic, moment du pic, multiples à 5 s, 15 s, 30 s, 60 s, 120 s, 300 s et 900 s, première vente du créateur. |
| `bot/master_v2/validation.py` | Métriques des cycles clos, intervalle par rééchantillonnage (avec grappes de créateurs), PSR, DSR sur tous les essais, découpage chronologique avec embargo et créateurs disjoints, empreinte de pré-enregistrement. |
| `tools/master_v2_research.py` | Commandes `run`, `lifecycle` et `evaluate`. Le segment `holdout` reste scellé, sauf `--holdout` avec les empreintes pré-enregistrées à desceller. |

Règles de comptabilité, héritées du rejeu L1 : seul un cycle `closed` a un P&L. Les positions ouvertes, migrées ou invalorisables sont comptées par issue, toujours hors P&L.

## 3. Protocole d'exploration P0 (proposé à RUGGER 03, après audit de RUGGER 02)

Les 514 pools P0 ont déjà servi au diagnostic. Ils ne peuvent donc être qu'un jeu d'**exploration**. La validation finale exige une fenêtre nouvelle, collectée après le gel des règles et seulement avec l'accord du propriétaire.

1. `lifecycle` sur les 514 pools : comment et à quelle vitesse les lancements montent puis s'effondrent.
2. Courbe du moment d'entrée : `diagnostic-fixed-delay` pour des délais de 0, 5, 15, 30, 60 et 120 s, avec une seule règle de sortie fixée à l'avance. L'entrée immédiate est-elle récompensée après coûts ?
3. Placebos : `placebo-no-trade` et `placebo-random-entry`.
4. Familles : `immediate-snipe`, `delayed-confirmation` et `fill-momentum`, chacune avec ses paramètres par défaut.
5. `evaluate` sur l'ensemble des exécutions. Tous les essais entrent dans le DSR, et le segment `holdout` reste scellé.

Toute règle choisie sur ces résultats doit ensuite être figée (empreinte de pré-enregistrement), puis jugée sur une fenêtre future qui n'aura jamais été lue.

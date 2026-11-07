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

### Garde-fous ajoutés après l'audit de RUGGER 02 (B1 et O1 à O6, rapport `3ae70926…`)

- **Fenêtre de collecte M1 (B1).** Quand le MANIFEST fixe `entry_cutoff_slot` et `window_slot_max`, aucune entrée n'est admise après la coupure. Le refus est journalisé et définitif : `NO_TRADE`, motif `after_entry_cutoff_slot`. Un cycle ne compte comme clos que si sa sortie tombe au plus tard à `window_slot_max`, sinon `open_at_window_end`, hors P&L. C'est `_apply_window` du rejeu L1.
  - L'écart de la fenêtre doit couvrir la détention bornée de la règle de sortie : `ceil(max_hold_s × 1000 / 350) + 2 × latence` slots.
  - Sans `max_hold_s`, une fenêtre est refusée.
  - **Sur P0** (écart de 160 slots), cela impose `max_hold_s ≤ 54`.
- **Pré-enregistrement lié (O2).** L'empreinte couvre la politique, la sortie, les paramètres de rejeu, le **code** (empreinte des modules qui décident et comptent), les **données** (MANIFEST) et les **fenêtres**.
- **Registre d'essais (O3, O6).** `bot/master_v2/registry.py` tient un fichier JSON Lines chaîné par SHA-256, en ajout seul.
  - Chaque `run` y inscrit son pré-enregistrement **avant** le rejeu.
  - `evaluate` refuse un bundle non inscrit, refuse d'omettre un essai inscrit sur les mêmes données (le DSR compte donc tous les essais) et ne descelle le holdout que pour des empreintes inscrites.
  - La tête de chaîne (`registry_head`) doit être ancrée hors de l'outil : message à RUGGER 02, ou T-REG quand GitHub reviendra.
- **Embargo (O1).** `evaluate` exige un embargo d'au moins la plus longue détention bornée des exécutions comparées, plus la latence.
- **Placebo à population égale (O4).** `placebo-random-entry` exige, comme les challengers, un créateur signé.
- **Cycle de vie (O5).** Par défaut, le relevé ne décrit que le segment d'exploration. `--segment all` doit être demandé explicitement.

### Limites d'usage relevées au ré-audit de RUGGER 02 (rapport `73b63567…`)

- **U1, aucun agrégat sur tous les pools.** Le bundle ne porte plus d'agrégats sur l'ensemble des pools (`metrics`, `outcomes`), et `run` n'affiche que des identifiants. Les issues et les mesures ne sont produites que par segment, dans `evaluate`, et le holdout reste scellé. Les lignes de chaque pool restent dans le bundle, nécessaires à `evaluate`. Le scellement reste donc procédural : ne pas agréger ces lignes à la main.
- **U2, ancrage du registre obligatoire.** Une troncature de la **fin** du registre est indétectable localement, et `registered_at` est déclaré par l'appelant. Avant toute évaluation, la tête de chaîne (`registry_head`) est envoyée à RUGGER 02, ou inscrite dans T-REG quand GitHub reviendra. Une évaluation sans tête ancrée n'a pas de valeur de preuve.
- **U3, positions ouvertes publiées.** Comme dans L1, la durée maximale n'agit qu'au prochain événement : une position dans un pool devenu inactif reste ouverte, hors P&L. `evaluate` publie donc par segment :
  - les issues ;
  - le nombre de positions entrées mais non closes ;
  - la somme de leurs valeurs de marché ;
  - le nombre de positions non valorisables ;
  - une moyenne pessimiste, où chaque position non close compte comme une perte totale (`mean_return_open_as_total_loss`).

## 3. Protocole d'exploration P0 (proposé à RUGGER 03, après audit de RUGGER 02)

Les 514 pools P0 ont déjà servi au diagnostic. Ils ne peuvent donc être qu'un jeu d'**exploration**. La validation finale exige une fenêtre nouvelle, collectée après le gel des règles et seulement avec l'accord du propriétaire.

1. `lifecycle` sur les 514 pools : comment et à quelle vitesse les lancements montent puis s'effondrent.
2. Courbe du moment d'entrée : `diagnostic-fixed-delay` pour des délais de 0, 5, 15, 30, 60 et 120 s, avec une seule règle de sortie fixée à l'avance, de détention au plus 54 s sur P0. L'entrée immédiate est-elle récompensée après coûts ?
3. Placebos : `placebo-no-trade` et `placebo-random-entry`.
4. Familles : `immediate-snipe`, `delayed-confirmation` et `fill-momentum`, chacune avec ses paramètres par défaut.
5. `evaluate` sur l'ensemble des exécutions. Tous les essais entrent dans le DSR, et le segment `holdout` reste scellé.

Toute règle choisie sur ces résultats doit ensuite être figée (empreinte de pré-enregistrement), puis jugée sur une fenêtre future qui n'aura jamais été lue.

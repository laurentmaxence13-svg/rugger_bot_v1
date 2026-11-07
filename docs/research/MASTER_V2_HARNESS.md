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
  - L'écart de la fenêtre doit couvrir la détention bornée de la règle de sortie, plus 1 s d'arrondi des `block_time`. Elle vaut `slots_for_ms((max_hold_s + 1) × 1000) + 2 × latence` slots. Le plancher dépend de la durée couverte : 190 ms en dessous de 60 s, 200 ms au-delà (décision C1 de RUGGER 02, constat C3, commit `75a55d8`). Les fixtures mesurent 210 à 222 ms par slot, et P0 214,5 ms ; l'hypothèse de 400 ms était fausse.
  - Sans `max_hold_s`, une fenêtre est refusée.
  - **Sur P0** (écart de 160 slots, soit environ 34 s à 214,5 ms par slot mesurés), cela impose `max_hold_s ≤ 28` à la latence par défaut de 2 slots, et `max_hold_s ≤ 27` à 4 slots. Le protocole P0 fixe une latence de 4 slots, `max_hold_s = 25` et `exit_horizon_ms = 25000` (commits `341d3f4` et `75a55d8`). Il exige 145 slots côté V2, soit ceil(26 000 / 190) + 8, et 140 côté garde L1, soit ceil(25 000 / 190) + 8. Les valeurs par défaut de L1 (30 s, latence 2) exigent 162 slots : elles sont refusées sur P0. L'ancienne limite de 54 s reposait sur la borne erronée de 350 ms.
- **Pré-enregistrement lié (O2).** L'empreinte couvre la politique, la sortie, les paramètres de rejeu, le **code** (empreinte des modules qui décident et comptent), les **données** (MANIFEST) et les **fenêtres**.
- **Registre d'essais (O3, O6).** `bot/master_v2/registry.py` tient un fichier JSON Lines chaîné par SHA-256, en ajout seul.
  - Chaque `run` y inscrit son pré-enregistrement **avant** le rejeu.
  - `evaluate` refuse un bundle non inscrit, refuse d'omettre un essai inscrit sur les mêmes données (le DSR compte donc tous les essais) et ne descelle le holdout que pour des empreintes inscrites.
  - La tête de chaîne (`registry_head`) doit être ancrée hors de l'outil : message à RUGGER 02, ou T-REG quand GitHub reviendra.
- **Embargo (O1, revue D).** `evaluate` exige un embargo couvrant tout l'horizon de résultat de chaque exécution comparée : l'âge maximal d'entrée déclaré par la politique (`max_entry_age_s`), plus la détention bornée, plus 2 s d'arrondi, plus la latence. Avec `fill-momentum` par défaut, une détention de 25 s et une latence de 4 slots (protocole P0), cela fait ceil(327 000 / 200) + 8 = 1 643 slots, et 1 655 slots à 10 slots de latence, au lieu des 750 par défaut. (L'ancien exemple de 1 739 slots correspondait à 45 s de détention à 2 slots, refusé sur P0.)
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
- **Positions migrées et divergentes (ré-audit `32269b03…`, T3, T4).** Seules les positions encore sur la courbe (`open_at_end`, `open_at_window_end`) portent une valeur de marché. Une position `migrated_unpriced` garde dans sa ligne la dernière valeur d'avant la migration : elle est ignorée, la position compte parmi les non valorisables, et `migrated` en donne le nombre. Une `counterfactual_divergence` est ouverte et non valorisable. Des tests vérifient que chaque segment, holdout compris, ne compte que ses propres pools.

## 3. Protocole d'exploration P0 (proposé à RUGGER 03, après audit de RUGGER 02)

Les 514 pools P0 ont déjà servi au diagnostic. Ils ne peuvent donc être qu'un jeu d'**exploration**. La validation finale exige une fenêtre nouvelle, collectée après le gel des règles et seulement avec l'accord du propriétaire.

0. **Paramètres communs**, fixés avant tout résultat :
   - latence de 4 slots (`--replay latency_slots=4`), soit environ 0,86 s à 214,5 ms par slot. Avant la mesure de P0 par RUGGER 03, les 2 slots par défaut visaient environ 800 ms à 400 ms par slot ; ils ne représentent plus que 0,43 s (R02, O1) ;
   - détention maximale de 25 s, avec `exit_horizon_ms=25000`.

   Sur P0, l'écart de 160 slots dure environ 34 s. Ces valeurs y tiennent même si le plancher de slot devait descendre à 175 ms : 26 000 / 175, arrondi au-dessus, donne 149 slots, plus 8 de latence, soit 157 ≤ 160.

   Avant tout rejeu, RUGGER 03 vérifie sur P0, par fenêtres glissantes, que les slots ne sont jamais plus courts que le plancher de 200 ms (condition C1 de RUGGER 02).
1. `lifecycle` sur le segment d'exploration de P0 : comment et à quelle vitesse les lancements montent puis s'effondrent.
2. Courbe du moment d'entrée : `diagnostic-fixed-delay` pour des délais de 0, 5, 15, 30, 60 et 120 s, avec les deux mêmes règles de sortie pour tous, fixées à l'avance : E_SHORT (détention de 25 s seule) et E_SL (stop-loss de 10 %, prise de profit de 20 %, détention de 25 s). L'entrée immédiate est-elle récompensée après coûts ?
3. Placebos : `placebo-no-trade` et `placebo-random-entry`.
4. Familles : `immediate-snipe`, `delayed-confirmation` et `fill-momentum`, chacune avec ses paramètres par défaut.
5. `evaluate` sur l'ensemble des exécutions. Tous les essais entrent dans le DSR, et le segment `holdout` reste scellé.

Toute règle choisie sur ces résultats doit ensuite être figée (empreinte de pré-enregistrement), puis jugée sur une fenêtre future qui n'aura jamais été lue.

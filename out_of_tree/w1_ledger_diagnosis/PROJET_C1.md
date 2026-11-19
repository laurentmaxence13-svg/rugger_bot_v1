# Projet de correction C1 du ledger — NON APPLIQUÉ (R02 abb5fb04)

État : projet seulement. Rien n'est écrit ni exécuté avant l'audit de RUGGER 02 et sa décision.

## 1. Le défaut, vérifié dans le code figé (arbre aff97638)

**Ce que fait le rejeu**

- `bot/market/replay.py` compte 1 × `tx_cost` à l'achat (l. 224). Il en ajoute 1 × à la vente sur événement (l. 239),
  à la vente à l'horloge (l. 256) ou au marquage de fin de données (l. 290).
- Les issues `closed` et `open_at_end` ont donc 2 × `tx_cost`. Les issues non valorisées en ont 1 × :
  `counterfactual_divergence`, `migrated_unpriced` direct (franchissement de la migration ou `remaining_base == 0`),
  et le refus du marquage.
- `priced` vaut vrai uniquement pour `closed` et `open_at_end` (l. 96).

**Ce que fait hrr**

`hrr._trade` (l. 600-630) fixe `failed_attempt_costs` à 2 × si le résultat est valorisé, sinon à 1 ×. hrr réétiquette
ensuite certaines lignes valorisées **sans toucher** à `tx_costs` ni à `failed_attempt_costs` :

- `_apply_window` : `closed` hors fenêtre, ou `open_at_end`, devient `open_at_window_end` ;
- `_migrated` : `open_at_end` devient `migrated_unpriced` ;
- `_exit_after_migration` : `closed` dont la vente atterrit après la frontière devient `migrated_unpriced`, avec la
  note `exit_after_migration`.

**Ce qu'attend le ledger v7.4**

- `verify_cycle` (l. 337) attend `own = 2` seulement si `outcome` est `closed` ou `open_at_end`.
- Pour toute autre issue, il attend 1 × pour `tx_costs` (l. 344-347).

Une ligne valorisée puis réétiquetée est donc signalée à tort. Le rejeu est correct ; c'est l'attendu du vérificateur
qui est faux.

**Discriminant indépendant du bundle**

Seules les issues valorisées renseignent `exit_index` : `replay.py` le pose pour `closed` et `open_at_end`, et jamais
sur les chemins non valorisés. L'étape 2 (`w1diag.c1_table`) le montre, sans montant.

## 2. Correction proposée

**C1-b (recommandée) : l'attendu est re-dérivé, pas lu dans le bundle.** Pour une issue `open_at_window_end` ou
`migrated_unpriced` qui a une règle de sortie, le ledger appelle sa propre boucle `derive_hold` (copie indépendante,
déjà testée).

- Si l'issue re-dérivée est `closed` ou `open_at_end`, l'attendu est :
  - `tx_costs = 2 × (base + priority)` ;
  - `failed_attempt_costs = 2 × failed_fee` ;
  - `exit_index` re-dérivé égal à celui du bundle (contrôle ajouté).
- Sinon, l'attendu est 1 ×, et l'issue re-dérivée doit être égale à celle du bundle.
- Le `scope` reste `entry_only` pour ces issues. Le P&L n'est ni vérifié ni compté : il n'y en a pas.

**C1-a (minimale, moins indépendante) :** `own = 2 si exit_index n'est pas None, sinon 1`. Cette variante est rejetée
si R02 exige l'indépendance.

## 3. Deux façons de la livrer, et leur impact

| | D1 : `ledger.py` v7.7 modifié | D2 (recommandée) : module enveloppe `w1aux/ledger_c1.py` |
|---|---|---|
| `ledger.py` | sha 115f3cb5 changé | **inchangé** (115f3cb5) |
| Identités dayj et explore | **changent** : `W1AUX_ANCHORED` épingle ledger.py, donc il faut modifier `dayj.py` et les identités d'explore. La chaîne en cours refuse (`code_identities_changed_between_steps`), ce qui impose une transition d'identité déclarée (ta voie ii) ou une chaîne neuve | **inchangées** |
| `ledger_parallel` / `ledger_resume` | leur `LEDGER_SHA256` refuse, donc il faut de nouvelles versions | inchangés |
| Cache P1-bis | **invalidé**, car la clé contient le sha de ledger.py : 2 344 appels à recalculer, environ 11 h 30 | **réutilisé à 100 %** : la clé ne change pas et `derive_l1_plans` n'est pas touché |
| Durée sur W1 | environ 11 h 30, plus le risque de redémarrage (couvert par la reprise) | PROBE + relecture du cache + ASSEMBLY : quelques minutes d'après la mesure synthétique (environ 3 min extrapolées), plus la canonisation des timelines (R-c, non mesurée). **Moins d'une heure attendu, non mesuré** |
| Trace | les identités elles-mêmes | `LEDGER_PARALLELE.json` reçoit `c1 = {module, sha256}`. Lanceur `ledger_par step --resumable --c1` (w1x 0.1.5, `explore.py` inchangé) |

**Principe de D2.** `_entry_for` appelle `verify_cycle` par son nom global. Le module remplace `ledger.verify_cycle`,
dans un bloc `with`, par `verify_cycle_c1`, qui :

1. appelle le `verify_cycle` v7.4 d'origine ;
2. pour les seules issues `open_at_window_end` et `migrated_unpriced`, remplace les deux contrôles de multiplicité
   (`tx_costs`, `failed_attempt_costs`) par l'attendu de C1-b, et ajoute les contrôles `exit_index` et
   `relabel_consistent` ;
3. ne change rien d'autre : pour toute autre issue, le résultat est exactement celui de v7.4 (testé).

**Préalable (ta réserve R-a).** `ledger/` (FAIL) doit être sorti de la racine, avec son sha256, avant toute relance.
`explore` exige que `ledger/` soit absent. R03 en a déjà une copie gelée (`ledger_fail_20261119`).

## 4. Preuves prévues, avant toute exécution

- Ledger v7.4 avec C1 identique au ledger v7.4 seul sur le pack gelé et sur les packs synthétiques sans réétiquetage
  (même octets).
- Cas synthétiques réétiquetés, obtenus en remplaçant `summarize`, la fenêtre et la migration :
  - fenêtre : `closed` hors fenêtre, et `open_at_end` ;
  - migration : `open_at_end` migré, et `exit_after_migration` ;
  - `migrated_unpriced` direct ;
  - `counterfactual_divergence`.
  - Résultat attendu : FAIL en v7.4 et PASS avec C1. Une ligne réétiquetée dont `tx_costs` a été falsifié reste FAIL.
- Défauts volontaires.
- Suites complètes en `-W error`.
- MANIFEST.

## 5. Ce que C1 ne change pas

- Le rejeu, les bundles, le protocole et les seuils.
- Les autres contrôles du ledger.
- Les 2 344 plans L1.

D'après l'étape 1, aucun autre essai n'a d'écart : C1 ne change donc aucun autre verdict, ce qui sera vérifié par
l'identité sur le pack gelé.

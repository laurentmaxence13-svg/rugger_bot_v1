# w2arms 0.1 — bras W2 C-E et son placebo apparié (plan P-4 accepté par R02, 3f463674 ; Dossier B v1.6 §§ 4 à 7)

C-E est une OPTION NON RECOMMANDÉE (R01, R02). Le module existe pour qu'un emplacement vide puisse être rempli sans
improvisation.

## Ce que fait le module

**`rows`**
- **Fenêtre.** Il traite UNE fenêtre W2 : `--s0`, plage d'évaluation = `w1_run.plan(s0)['evaluation']`, gelée.
- **Lignes.** Une ligne par position placebo gelée : décision `placebo:0`, TP 7 / SL 5 / 30 s, latence 4, plus le
  rejeu à 10 slots.
- **Contenu de chaque ligne.**
  - le drapeau C-E : palier du taux causal ≤ 2 500 ppm (`cdgate.gate.tier`) ;
  - l'outcome brut ;
  - les frais de courbe exacts, en lamports.
- **Ce qui n'y figure pas.** Aucun rendement n'est calculé ni affiché ; seuls les effectifs sont imprimés.

**`verdict`**
- **Entrées.** Les lignes ANCRÉES des k fenêtres CONSÉCUTIVES (s0 + i × 1 612 800), lues une seule fois.
- **Mode et conventions.**
  - Mode gelé de C-E : compte FERMÉ (`closedacct` 0.2, échecs = 0).
  - Dénominateur : la mise.
  - Migrée : (− coût − loyer) / mise.
- **Conditions du § 5.**
  1. La borne basse unilatérale à 98,33 % du net est > 0.
  2. La borne basse de (C-E − placebo apparié SANS palier, mêmes pools) est > 0 (§ 6.5).
  3. Le net est > 0 sur chaque moitié, coupées à EVAL_MIN_1 + k × 1 612 800 / 2.
  4. Identité des coûts : brut − frais − tx − loyer (ou frais de nettoyage) = net, avec un résidu nul en lamports.
  5. La condition du § 3 est une entrée ancrée de R02.
- **Bootstrap.** Groupé par créateur, 10 000 tirages, graine = int(sha du gel[:8], 16).
- **Décision, dans cet ordre.**
  - DESCRIPTIVE si la règle 6.4 s'est déclenchée (entrée ancrée, comptes de population).
  - INCONCLUSIVE si n < 414.
  - GO si les conditions 1 à 5 sont toutes remplies.
  - NO-GO sinon.
- **Publié à part.** Mode loyer perdu, échecs = 1, latence 10 slots, gagnantes, min et max.
- **Gardes.**
  - Fenêtres consécutives, sinon refus ;
  - aucun pool dans deux fenêtres ;
  - même règle et même palier ;
  - sha de chaque fichier de lignes ;
  - format de l'entrée 6.4 ;
  - sortie jamais écrasée ;
  - aucun pool dans le verdict.

## Preuves

- **Tests : 11 réussis.**
  - Plage = `w1_run.plan`, et les fenêtres consécutives se touchent.
  - Lignes sans rendement.
  - Mêmes positions et même net que le placebo à palier bas de cdgate sur le pack gelé.
  - Une fenêtre hors des pools ne lit rien.
  - Décisions GO, DESCRIPTIVE, INCONCLUSIVE et NO-GO (conditions 1, 2, 3 et 5).
  - Gardes.
  - Convention migrée.
  - Quantile unilatéral exact.
  - Rejeu réel à 4 et à 10 slots.
- **Défauts volontaires : 15 sur 15 détectés** (`MUTATIONS_w2arms_v0_1.json`).

## Limites, déclarées

- **Condition 4.** Elle est une identité par construction : les frais de courbe s'annulent. Le test vérifie de plus que
  le net de la décomposition est égal au net de closedacct.
- **A0, A1 et C-B.** Ils ne sont pas dans ce module : ils réemploient dayj (C1 + P1) et statelab.hypotheses, gelés,
  selon le plan P-4.

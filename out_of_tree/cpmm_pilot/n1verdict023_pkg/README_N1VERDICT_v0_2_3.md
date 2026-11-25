# n1verdict 0.2.3 — cpmmrecon avant les positions, G-0 calculé (PROJET)

RUGGER 01, 25/11/2026.
- Demande de R02 (12:42:09Z). Le point (3) du texte cda64700 et l'option (a) ont été fixés par R02 à 13:03Z.
- **PROJET : rien n'est intégré ni ancré** avant la signature de cda64700 et la vérification de R02 à la source.
- Paquet séparé. n1verdict 0.2.2 (`n1verdict_pkg`), cpmmx, cpmmcost, lpcost et cpmmrecon sont INTACTS.
- Hors ligne, 0 crédit. Aucune donnée de fenêtre n'est lue : les tests sont synthétiques.

## Point (3) de cda64700 (mot pour mot, transmis par R02)

« (3) le contrôle G-0 de N1 est le même que celui de G2-3, appliqué à ses trois pools ; une position N1 dont l'état
d'entrée ou de sortie est séparé de son atterrissage par une transaction non décodée est non valorisable et comptée en
perte totale. »

## Changements par rapport à la 0.2.2

| Étape | 0.2.3 |
|---|---|
| Lignes (`lines.prepared`) | Ligne d'union (pré-T0 + fenêtre) puis `cpmmrecon.rebuild` (tout ou rien par transaction), comme g23run 0.1.2. Le côté créateur vient de `cpmmcost.creator_side` ; une ligne sans côté connu n'est pas tentée (`kept:not_tried_creator_side`). Le coffre WSOL vient de U2 |
| G-0 | **Calculé** : il n'y a plus d'option `--g0`. `pool_gate` (inchangé) porte sur la ligne de FENÊTRE de chaque pool, reconstituée de la même façon, comme G2-3. `g0_passed` = aucune erreur d'intégrité (exception) sur les 3 pools. **Option (a)** : un pool non admis est exclu et publié avec ses motifs (`g0_excluded`, `per_pool[p].status = excluded_by_g0`). Les planchers jugent ensuite : avec 2 pools, ou 0, le résultat est INCONCLUSIF, jamais STOP ni une erreur |
| Règle UNDECODED (`verdict.undecoded_reason`) | Une transaction encore non décodée après cpmmrecon, ordonnée par (slot, transactionIndex), rend la position non valorisable, donc perte totale, dans deux cas. **Entrée** (`undecoded_transaction_at_entry`) : elle est strictement après le dernier swap exécuté à T0 (l'état de décision) et strictement avant le premier swap après l'atterrissage d'entrée. **Sortie** (`undecoded_transaction_at_exit`) : elle est strictement après le dernier swap exécuté à l'atterrissage de sortie − 1 s, et avant le premier swap après cet atterrissage ; s'il n'y en a pas, jusqu'à la fin des pages. La règle s'applique à la série principale et aux 3 sensibilités |
| Marques quotidiennes | Elles ne sont pas concernées par la règle. Le nombre de marques touchées (`undecoded_marks`, début des jours 1 à D − 1) est publié dans RECONSTRUCTION.json, à titre descriptif |
| Sorties | RESULT.json comme en 0.2.2 ; RECONSTRUCTION.json (`--reconstruction`) : par pool, la reconstitution de l'union et de la fenêtre (reconstituées / conservées avec motifs), G-0, `undecoded_after`, `undecoded_marks`, et `g0_passed` |

- **Portée de la règle UNDECODED.** Un pool admis n'a aucune transaction de FENÊTRE non décodée, car G-0 la
  refuserait (remarque de R02). La règle peut pourtant s'appliquer à une transaction **pré-T0** non décodée, placée
  entre le dernier swap avant T0 et le premier swap après l'atterrissage d'entrée : G-0 ne lit que la fenêtre. Ce cas
  est testé (`test_a_pre_t0_undecoded_transaction_before_the_entry_landing_makes_the_position_unpriced`).
- **Schémas conservés** : `n1verdict-v0.2.1` et `n1verdict-lines-v0.2.2`. Sans transaction tronquée et avec 3 pools
  admis, RESULT.json est identique octet pour octet à celui de la 0.2.2 lancée avec `--g0 passed`. La version se lit
  dans le MANIFEST et dans RECONSTRUCTION.json (`n1verdict-reconstruction-v0.2.3`).

## Commande (R03, après signature et vérification R02)

`python -B -m n1verdict.lines --u2 U2.json --pre-root DIR --window-root DIR --t0-slot 473309024 --sheet-sha <N1 v0.7>
--result RESULT.json --reconstruction RECONSTRUCTION.json`

Chemin Python : celui de la 0.2.2, avec cpmmcost 0.3.1 (`cpmmcost031_pkg`) à la place de cpmmcost 0.3, cpmmpilot
0.2.8, puis `cpmmrecon_pkg` et `n1verdict023_pkg`.

## Validation

- 25 tests : les 13 tests de la 0.2.2 (2 adaptés : G-0 calculé et `--reconstruction`), plus 12 nouveaux
  (`tests/test_recon.py`) :
  - bornes d'entrée et de sortie de la règle, ordre (slot, index), entrée examinée d'abord ;
  - perte totale avec la mise de la 0.2.1, série principale et sensibilités ; aucun effet hors des intervalles ;
  - exclusion G-0 : 2 pools donnent INCONCLUSIF, 0 pool donne INCONCLUSIF, pool exclu non nommé refusé, STOP sur
    erreur d'intégrité ;
  - cpmmrecon appelé sur l'union et sur la fenêtre, avec le coffre WSOL, les frais et le côté créateur ;
  - transaction pré-T0 non décodée (position non valorisable), transaction de fenêtre non décodée (pool exclu) ;
  - marques touchées ;
  - `prepared` garde les contrôles de `pool_line` (signature des deux côtés, pool manquant) ;
  - **identité** : RESULT.json octet pour octet avec la 0.2.2 ancrée (sha `de0732b3` / `e6db8985` vérifiés),
    lancée sur son propre verdict.
- Mutants : 89/89 détectés (`MUTATIONS_n1verdict_v0_2_3.json`) : verdict 47/47 (33 de la 0.2.2, dont 1 adapté, et 14
  nouveaux), lines 42/42 (15 de la 0.2.2, dont 4 adaptés à G-0 calculé, et 27 nouveaux). Une première campagne laissait
  survivre `both_sides_allowed_023` (41/42) ; le test de `prepared` le détecte.

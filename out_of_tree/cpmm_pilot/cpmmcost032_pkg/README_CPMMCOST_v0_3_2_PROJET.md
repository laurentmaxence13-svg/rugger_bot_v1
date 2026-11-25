# cpmmcost 0.3.2 — PROJET E-G0 (NON ANCRÉ, à ne pas utiliser)

RUGGER 01, 25/11/2026.
- Préparé sur autorisation de R04 (12:00Z : « PRÉPARER le code, sans l'ancrer »).
- Il attend le texte E-G0 du propriétaire. Rien ici n'est soumis à l'audit tant que ce texte n'existe pas (R02).
- Base : cpmmcost 0.3.1 (E-CF). **Sans le paramètre `tolerance`, `pool_gate` est identique à 0.3.1** : les 25 tests de
  la 0.3.1 passent tels quels.

## Ce que fait le projet (G-0 seulement)

`pool_gate(line, config, tolerance=dict(positions=skipped_positions(line, txs), transactions=N))` lève les motifs
`undecoded_transactions` et `reserves_chain_broken` SEULEMENT si les trois conditions suivantes sont réunies :
1. toutes les transactions non décodées sont `log_truncated` ;
2. leur part, `len(skipped) / N`, est ≤ 2 % ;
3. chaque rupture de réserves (hors événements LP) est adjacente à l'une d'elles : une non décodée se trouve
   strictement entre les deux swaps, par (slot, index).

Aucun autre motif n'est jamais levé : frais de transfert, swaps non reproduits, etc. La preuve publiée est renvoyée
dans `undecoded_tolerated`.

## Ce que le texte du propriétaire doit fixer avant toute version à auditer

- **N, le dénominateur.** Il change le résultat : pour G8kgi7, 1,22 % de toutes les tx, mais 3,32 % des tx portant un
  swap (`EG0_DENOMINATORS.json`, commit 46a4e9a). Le projet prend N en ENTRÉE et ne le choisit pas.
- **« Position touchée » (vente nulle K01).** Deux lectures sont possibles :
  - une non décodée quelque part entre la décision et la sortie ;
  - une non décodée entre l'état qui valorise un atterrissage et cet atterrissage.

  Pour N1, qui tient 12 jours, la première lecture rendrait presque toutes les positions « touchées ». Ce câblage
  n'est PAS écrit : il touche g23run et n1verdict, et attend la définition.

## Vérification (pages pré-T0 / pré-départ, hors ligne, N = toutes les tx des pages, à titre d'illustration)

`verify_eg0_real_pages.py` → `VERIFY_EG0_REAL_PAGES.json` :
- AEZjoU, G8kgi7 et GdxFyc sont admis ; Gms3Ma est refusé (token_transfer_fee) ;
- livesim : FAn5gz est refusé à 2,26 %, et 7SJ5UK, 5zk4vh, 6CQSpR et 4D17GN seraient admis.

## Validation

- 28 tests : les 25 de la 0.3.1, plus 3 tests E-G0 synthétiques. Ils couvrent :
  - l'absence d'effet par défaut et la cohérence des entrées ;
  - la part ≤ 2 % (2 % compris), la rupture non adjacente refusée et une autre cause refusée ;
  - le fait qu'aucun autre motif n'est levé.
- 61 mutants sur 61 détectés (`MUTATIONS_cpmmcost_v0_3_2_PROJET.json`).

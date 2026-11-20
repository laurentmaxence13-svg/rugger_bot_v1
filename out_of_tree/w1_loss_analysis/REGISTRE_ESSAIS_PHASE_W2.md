# Registre des essais — phase « rentabilité » / W2 (RUGGER 01, tenu au fil de l'eau ; règle R02 877da7b6)

Règles de comptage :
- N augmente de 1 pour chaque règle candidate W2, et pour chacune de ses variantes, évaluée sur W1 ou sur P0.
- Les ventilations descriptives (E) sont comptées à part et publiées.
- Point de départ : N = 159 (R02). La lecture unique des HW1, à venir après le verdict officiel W1, porte N à 164.

| Date (UTC) | Objet | Données | E | N après | Empreinte du résultat | Remarque |
|---|---|---|---|---|---|---|
| 2026-11-20 | w1loss 0.3, liste fermée T1 à T7 | W1, ledger ancré | +7 | 159 | JSON da1e5758, .md f5d1388e (R02 2333dcff) | exécuté par R03, vérifié et ancré par R02 |
| 2026-11-20 | Porte de C-A (T1, palier 12 500 ppm), ancrée par R02 (f2f86f74) | W1, ledger ancré | — | **160** | da1e5758 (R02 2333dcff) | ÉCHEC : n = 46, net −5,45 % [−10,89 ; −0,55] ; C-A retiré |
| 2026-11-20 | Liste des pools migrés (w1migr 0.1.1) | W1, bundle L1 | — | 160 (hors N, population) | eef9fb48 | 12 membres ; C-C irréalisable |
| 2026-11-20 | Candidat C-D (entrée tardive à palier bas), écrit après regard sur les E = 7 ventilations W1 (R02 3cd2ffa2) | — | — | **161** | — | N + 1 à l'écriture ; aucune évaluation sur W1 |

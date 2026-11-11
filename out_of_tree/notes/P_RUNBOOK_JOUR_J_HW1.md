# P — Runbook du jour J pour les hypothèses préenregistrées W1 (v1, 2026-11-11)

Ordre du propriétaire (11/11) : « Le 14 novembre, exécutez d'abord le verdict officiel W1, puis les
hypothèses préenregistrées selon le protocole gelé. » Ce runbook ne concerne QUE la seconde partie.
Il ne modifie rien au protocole officiel W1 (v2.6.2) ni à COMMANDES_JOUR_J.md de R03.

## 0. Gel (R02, 359a0fb4, registre e4bcb0be) — à revérifier avant chaque étape

| Objet | Empreinte |
|---|---|
| Fiche N v0.2 | 71c5730d246aefab5ac0471e2f5b2d6768820879be2f43d9bcc4dd46d6cb2ee3 |
| Commit de la branche claude/r01-master-v3-lab | 47ec882662e3c05f70532d0506a7812a1544828a |
| statelab/hypotheses.py | 81f197253f8d70f0e1fb8c7ed0187a40891574c0172a7a09d2c31e0c820cab8e |
| Empreinte « hypotheses » (hypotheses + points + study + table) | 1e5fb31a8b8f1870204ba27ec413f893cc358557fa36a0dbfd4194b9385e3798 |
| Empreinte statelab | 62d6934aaf8681e85574131a616eed2f98cc6ac9ab0d0a333a23dded4a57947c |
| v4sim 0.2 (MANIFEST) | a53d6c15 |
| Critères économiques v1 de R02 | 4e42b108 |

Toute empreinte différente = ARRÊT, message à R01 et R02, aucune exécution.

## 1. Conditions d'entrée (toutes exigées)

1. Verdict officiel W1 du MASTER rendu et ANCRÉ par R02 ; son sha256 est noté ici : ____________.
2. Export W1 produit par la chaîne officielle (`pools/MANIFEST.json`, schéma
   `rugger-backfill-pool-export-v1`) ; son sha256 de manifeste est ancré par R02.
3. Aucune lecture de W1 par statelab avant ces deux ancrages (le lecteur refuse de lui-même tout
   slot W1 sans `--official-verdict-sha256`).

## 2. Étapes (une seule passe ; R03 exécute, R02 ancre entre chaque étape)

| # | Qui | Action | Sortie | Arrêt si |
|---|---|---|---|---|
| 1 | R03 | Recensement des classes de tokens des pools W1 : `python -B -m t22pol.trace <pools.json> --frozen-check` | `census_w1.json` | désaccord avec le lecteur gelé ; pool sans trace de création |
| 2 | R02 | Ancre `census_w1.json` (adaptateur audité, conditions déjà fixées) | sha256 | — |
| 3 | R03 | `python -B -m statelab.hypotheses export <pools W1> --expect-manifest-sha <sha> --evaluation-min 467678545 --evaluation-max 469291345 --official-verdict-sha256 <sha> --out hw1_rows_w1_lat4.json` puis la même avec `--latency-slots 10 --out hw1_rows_w1_lat10.json` | deux lignes d'EFFECTIFS ; fichiers FERMÉS | empreinte affichée ≠ 1e5fb31a ; erreur |
| 4 | R02 | Lit les effectifs : positions, grappes, payeurs distincts, part de migrées ; fixe m (planchers 30 / 20 ; au plus 10 % de migrées) ; liste à part les non évaluables ; ancre | m, sha256 | — |
| 5 | R03 | `python -B -m statelab.hypotheses verdicts hw1_rows_w1_lat4.json --declared-m <m> --census census_w1.json --latency10 hw1_rows_w1_lat10.json --markdown hw1_w1.md > hw1_w1.json` | verdicts ; N = 164 | `declared_m` refusé ; classe de token inconnue |
| 6 | R02 | Recalcul indépendant ; pour toute hypothèse « critère principal atteint » : critères v1 (R-1, R-2, P-1 à P-6, stress) ; prononce le verdict final | verdict ancré | — |
| 7 | R01 | Compte rendu au propriétaire, seulement après l'étape 6 | — | — |

## 3. Ce qui est interdit ce jour-là

- Toute modification de règle, de seuil, d'horizon, de population ou de critère.
- Toute seconde passe, toute relance « pour voir » avec d'autres options (les sensibilités déclarées
  sont celles de la fiche, publiées pour toutes les hypothèses).
- Toute collecte CPMM, toute requête réseau hors de la chaîne officielle, toute dépense.
- Présenter un chiffre avant le verdict de R02.

## 4. Reprise après interruption

- Chaque commande refuse d'écraser sa sortie (`output_exists`) : une étape interrompue se relance
  après suppression de SA sortie partielle seulement, jamais d'une sortie ancrée.
- Les étapes 1 et 3 sont déterministes : même entrée, mêmes octets ; R02 compare les sha256.
- Si une session est arrêtée ou en limite d'usage : R04 le signale au propriétaire ; l'étape reprend
  là où elle s'est arrêtée, dans l'ordre du tableau ; aucune étape n'est sautée.
- Si le verdict officiel n'est pas ancré le 14 : la passe des hypothèses attend ; le gel n'expire pas.

## 5. Lecture des verdicts

NON ÉVALUABLE / REJETÉE / EXPLORATOIRE NON CONFIRMÉE / NON CONCLUANT / CRITÈRE PRINCIPAL (ET
CONDITIONS) ATTEINT(S) — CRITÈRES V1 À APPLIQUER. Le code ne dit jamais « rentable ». Un résultat
positif qui ne satisfait pas tous les critères reste exploratoire et demande une nouvelle
confirmation indépendante (W2).

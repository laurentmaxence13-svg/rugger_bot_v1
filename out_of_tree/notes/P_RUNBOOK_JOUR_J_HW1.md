# P — Runbook du jour J pour les hypothèses préenregistrées W1 (v2, 2026-11-11 — intègre la revue de R02 4e03d6a6 et les réponses de R03)

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
| 1a | R03 | Entrée du recensement, hors ligne et sans prix : `python3 -I build_trace_input.py <export W1>/pools pools_trace_w1.json` (extracteur ancré par R02 : b861d35c ; le sha256 du fichier produit est affiché d'abord) | `pools_trace_w1.json` | empreinte de l'extracteur ≠ celle ancrée |
| 1b | R03 | Recensement des classes de tokens : `python -B -m t22pol.trace pools_trace_w1.json --frozen-check` (sans `-I` ; trace.py = version auditée 274fbc30) | `census_w1.json` | code de retour 1 (au moins un désaccord avec le lecteur gelé) |
| 2 | R02 | Ancre `pools_trace_w1.json` et `census_w1.json`. Pools laissés de côté par l'extracteur : règle de l'ancrage d5cde717, pas d'arrêt à cette étape | sha256 | — |
| 3 | R03 | `python -B -m statelab.hypotheses export <pools W1> --expect-manifest-sha <sha> --evaluation-min 467678545 --evaluation-max 469291345 --official-verdict-sha256 <sha> --out hw1_rows_w1_lat4.json` puis la même avec `--latency-slots 10 --out hw1_rows_w1_lat10.json` | deux lignes d'EFFECTIFS ; fichiers FERMÉS | empreinte affichée ≠ 1e5fb31a ; manifeste W1 ≠ celui ancré ; plage d'évaluation ≠ [467678545 ; 469291345) ; erreur |
| 4 | R02 | ANCRE D'ABORD les deux fichiers de lignes, PUIS lit les effectifs : positions, grappes, payeurs distincts, part de migrées ; fixe m (planchers 30 / 20 ; au plus 10 % de migrées) ; liste à part les non évaluables ; ancre m | sha256 des lignes, m | — |
| 5 | R03 | `python -B -m statelab.hypotheses verdicts hw1_rows_w1_lat4.json --declared-m <m> --census census_w1.json --latency10 hw1_rows_w1_lat10.json --markdown hw1_w1.md > hw1_w1.json` | verdicts ; N = 164 | `declared_m` refusé. Si une position est refusée faute de classe de token : hypothèses NON ÉVALUABLES (recensement incomplet), sans complément |
| 6 | R02 | Recalcul indépendant, avec les règles qu'il a ancrées AVANT W1 (4e03d6a6, § 6 ci-dessous) ; pour toute hypothèse « critère principal atteint » : critères v1 (R-1, R-2, P-1 à P-6, stress) ; prononce le verdict final | verdict ancré | — |
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

## 6. Règles de l'étape 6, déclarées par R02 avant W1 (ancrage 4e03d6a6, registre eb96595f)

R02 a relevé deux écarts entre la fiche gelée et le code gelé. Le code n'est pas modifié ; R02 les traite
lui-même, avec la même fonction de rendement, le même bootstrap et le même m :

1. Le code INCLUT les positions de classe « refused » (le recensement leur donne un loyer), alors que la
   fiche dit « exclu et compté » (sur P0 : 2 positions, sans effet). R02 calcule la variante V-fiche (hors
   « refused ») : un résultat positif exige le code ET V-fiche.
2. Le code ne calcule pas toutes les sensibilités annoncées par la fiche. R02 calcule V-SPL (exigée pour
   le mot « exécutable »), V-signés et V-loyer récupéré (publiées, sans effet sur le verdict).

Aucune de ces variantes ne peut rendre positif un résultat que le code gelé ne donne pas positif.

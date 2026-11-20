# Paquet cloud v2.6.4 — option A2 (verdict officiel W1) — PRÉPARÉ, NON AUDITÉ, NON LANCÉ

Ce paquet a été préparé sur la décision du propriétaire du 20/11, point 4 : « Préparez l'option A2 avec un plafond
maximal de 66 $ TTC, sans lancement ni engagement financier ».

Il ne peut être lancé qu'après trois conditions :
1. le PASS de RUGGER 02 sur ce paquet ;
2. l'accord EXPLICITE du propriétaire sur l'amendement C1 et sur la dépense ;
3. la sauvegarde W1 terminée (lots 6 et 7).

## Différences avec la v2.6.3 (423dfd4)

| Point | v2.6.3 | v2.6.4 |
|---|---|---|
| w1aux | v7.4 (31222874) | **v7.8** : v7.4 + P1 + reprise + C1 + lanceur (empreinte de l'arbre 426ed6cb) |
| Étape ledger | `w1aux.dayj` (ledger v7.4) : FAIL certain sur les 93 lignes C1 | `w1aux.dayj_c1p1 --ledger-workers $WORKERS`, c'est-à-dire C1 + P1 sur 8 processus ; trace publiée (`dayj_c1p1_trace.json`) |
| Autres étapes | `w1aux.dayj` | inchangées |
| DEADLINE | ≤ 48 h, proposée à + 40 h | **≤ 50 h**, refusée au-delà, proposée à + 50 h |
| Budget | 60 $ | **66 $ TTC** au plus ; durée prévue de 36 à 43 h, soit 48 à 57 $ TTC (note voie B v0.4.1, PASS R02) |

## Tests hors ligne

- `test_cloud_v26.sh`, adapté à la v2.6.4 : ALL OK.
  - L'étape ledger, et elle seule, passe par le lanceur, qui reçoit `--ledger-workers 8`.
  - La trace est écrite hors de `dayj/`, puis publiée.
  - Une DEADLINE à + 51 h est refusée, et le démarrage aussi au-delà de 50 h après la création.
- Le tarif reste à relire par RUGGER 03.

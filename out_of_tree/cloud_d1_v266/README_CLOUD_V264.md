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
| DEADLINE | ≤ 48 h, proposée à + 40 h | **≤ 49 h**, refusée au-delà, proposée à + 49 h. Au pire, 49 h × 1,048112 $ + disque ≈ 1,5 $ + stockage ≈ 1,5 $ ≈ 54,3 $ HT, soit ≈ **65,2 $ TTC ≤ 66 $**. À 50 h, R03 trouve ≈ 66,5 $ TTC, au-dessus du plafond |
| Budget | 60 $ | **66 $ TTC** au plus ; durée prévue de 36 à 43 h, soit 48 à 57 $ TTC (note voie B v0.4.1, PASS R02) |

## Tests hors ligne

- `test_cloud_v26.sh`, adapté à la v2.6.4 : ALL OK.
  - L'étape ledger, et elle seule, passe par le lanceur, qui reçoit `--ledger-workers 8`.
  - La trace est écrite hors de `dayj/`, puis publiée.
  - Une DEADLINE à + 50 h est refusée, et le démarrage aussi au-delà de 49 h après la création.
- Le tarif reste à relire par RUGGER 03.

## Corrections après l'audit R02 2a3eb5f8 (20/11)

- **M-1.** Le manifeste périmé `MANIFEST_d1_v264.txt` est supprimé. Un seul manifeste fait foi : `MANIFEST_v264.txt`.
- **Usage du test.** Le 3ᵉ argument de `test_cloud_v26.sh` doit être un nom de branche simple, pas un sha.
- **Selfcheck hors environnement de référence (question R02 : ed7f97c4 au lieu de 4aee76a3).**
  - **Cause, reproduite chez R01.** `bot/live/solana_signatures.py` importe `cryptography` À L'INTÉRIEUR de
    `verify_compiled_rpc_signatures`. Sans ce paquet, le rejeu inscrit `ed25519_signatures_not_verified`.
    `creator_history` et `blocking_reasons` changent alors, et les 9 bundles avec eux.
  - **Le problème.** La liste `requirements-dayj.txt`, établie « par import », ne contenait pas ce paquet. La VM
    n'installe que cette liste.
  - **Correction.** Ajout de `cffi==2.1.1`, `cryptography==46.0.7` et `pycparser==3.12`, les versions de l'environnement
    de référence.
  - **Preuves (R01, CPython 3.12.3, `python -S`, roues dépaquetées par zipfile, PYTHONPATH dans l'ordre de la VM).**

| Paquets installés | Selfcheck |
|---|---|
| Ancienne liste seule | **ed7f97c4** (la valeur de R02) |
| Nouvelle liste, 14 roues téléchargées par la commande exacte de `r03_transfer.sh` | **4aee76a3** |

  - **Sans effet.** Ni PYTHONHASHSEED=0, ni TZ, ni le chemin absolu, ni un export `git archive` réinitialisé ne changent
    le résultat (4aee76a3).

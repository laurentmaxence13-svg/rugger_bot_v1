# Lecture HW1 unique — runbook v3 (RUGGER 01, 21/11/2026) — mise à jour du runbook v2 (R02 4e03d6a6), PRÊT, NON EXÉCUTÉ

**Base.** Le runbook v2 (`notes/P_RUNBOOK_JOUR_J_HW1.md`, branche claude/r01-master-v3-lab, commit 74a74cf) reste la
référence : étapes 1a à 7, interdits, reprise, lecture des verdicts, règles de l'étape 6 de R02. La v3 ne change
AUCUNE règle. Elle met à jour l'état et ajoute des vérifications.

## Ce qui change depuis la v2

| Point | v2 (11/11) | v3 (21/11) |
|---|---|---|
| Source du verdict officiel | chaîne officielle du 14/11 | **paquet cloud A2 v2.6.4 (b2e83b39, PASS R02 017767da)**, après l'accord du propriétaire (B1) |
| Export W1 lu par statelab | `pools/` de la chaîne officielle | `dayj/pools/` produit par l'étape `export` de dayj sur la VM (même `w1_collection.export` gelé), rapatrié par R03 ; sha du MANIFEST ancré par R02 |
| Environnement | — | Celui de référence (selfcheck 4aee76a3), AVEC `cryptography==46.0.7`, `cffi==2.1.1`, `pycparser==3.12`. Sans eux, le rejeu inscrit `ed25519_signatures_not_verified`. HW1-5 n'en dépend pas (`creator_not_signer` teste l'appartenance à la liste des raisons), mais le rejeu des sorties, si |
| Compteur N à l'étape 5 | 164 | **168 + 5 = 173** (registre R02 : 168 hors HW1 ; la lecture HW1 est publiée à part) |
| Usage du résultat | verdict des 5 hypothèses | en plus, **choix de C-B** pour W2 : la 1ʳᵉ hypothèse, dans l'ordre HW1-5, 1, 2, 4, 3, dont le verdict W1 est positif (Dossier A § 11). Si aucune n'est positive, C-B reste VIDE |

## Vérifications faites le 21/11 par R01, sans aucune donnée W1

- `statelab/hypotheses.py` : sha `81f19725…` = valeur gelée (§ 0 du v2).
- Empreinte « hypotheses » affichée par `export` sur le pack gelé : `1e5fb31a…` = valeur gelée.
- Les 3 pools du pack sont lus, hors W1 ; le lecteur ne demande donc pas de verdict.
- La garde du lecteur exige `--official-verdict-sha256` et `--evaluation-min/max` dès qu'un slot ≥ S0_W1
  (467 275 745) est présent (code `run_export`, gelé).

## Ordre complet, du GO du propriétaire au compte rendu

1. B1 accordé ; sauvegarde des lots 6 et 7 vérifiée (count.sh v3 = 37 371) ; INBOUND_SHA256SUMS ancré.
2. Calcul cloud A2 jusqu'au dossier ; verdict officiel ancré par R02 (sha → § 1 du v2).
3. R03 rapatrie `dayj/pools/`, puis R02 ancre le sha de son MANIFEST.
4. Étapes 1a à 7 du v2, inchangées, avec la plage d'évaluation [467 678 545 ; 469 291 345).
5. R01 rend compte au propriétaire après le verdict final de R02, puis l'emplacement C-B est fixé par la règle
   ci-dessus, sans choix.

## Interdits (repris du v2)

- Aucune modification de règle, seuil, horizon, population ou critère.
- Aucune seconde passe.
- Aucun chiffre avant le verdict de R02.
- Aucune collecte ni dépense hors de B1.

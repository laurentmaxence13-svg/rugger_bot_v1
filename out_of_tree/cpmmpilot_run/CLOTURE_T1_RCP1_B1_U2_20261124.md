# Clôture T1 — R-CP1 et B1 sur la liste U-2 du 24/11/2026 : INFAISABLE

## Autorisation

Texte du propriétaire écrit dans la session R03 le 24/11/2026 à 18:00:36Z (web), événement 10360164.

Fichier canonique : `AUTORISATION_T1_T2.txt`, soit les octets UTF-8 exacts de `message.content`, sans saut de ligne final. Taille : 1 183 octets. sha256 : b75e657a60a0de335906e091936c93ba707b639a3b9ca5fc56c7623142a063f9.

## Verdict

**INFAISABLE**, pour insuffisance de pools déclencheurs.
- Aucun résultat économique n'a été calculé.
- Les essais 169 (R-CP1) et 170 (B1) ne sont **pas consommés**.
- Aucune fiche de gel n'a été écrite. La fenêtre [T0 ; T0 + D) n'a jamais été lue.

## Faits sur lesquels repose la clôture (preuves dans le dépôt)

| Fait | Valeur | Preuve |
|---|---|---|
| Liste U-2 (24 pools, T0 = 24/11 10:21:26Z) | U2 3ca0260a, ancrée R02 | TIME2_20261124T102839Z |
| R̂ (24 h avant T0) ; D_max | 1 310,4 ; 3,334 j | STEP1A_…/COUNT_24H.json c852ec12 |
| Déclencheurs R-CP1 / B1 sur [T0 − 7 j ; T0) | 61 / 59, dont 59 / 57 sur un seul pool (G8kgi7) | STEP1A2R_RESULT 07facd9e, RECOUNT_A2R 17117bda |
| Règle D (R02 e294655a) | D = 3, attendu ⌊61 × 3 / 7⌋ = 26 < 30 → UNDERPOWERED | STEP1A2R_RESULT |
| Transactions écartées (journaux tronqués) | 1 541, soit au plus 1,7 % de swaps perdus | RECOUNT_A2R |
| Crédits Helius consommés par le pilote | U-2 2 380 + étape 1 13 323 = 15 703 (offre Free, aucune dépense) | registres |

## Ce que cette clôture ne dit PAS

L'absence de déclenchements en nombre suffisant **n'est pas une preuve de non-rentabilité** de R-CP1 ou de B1. Elle établit seulement que, sur cet échantillon de 24 pools et avec un budget limitant D à 3 jours, le test n'avait pas la puissance requise.

## Suite autorisée

T2 : une unique mesure d'activité sur 24 h des 259 pools de L, au plus 1 500 crédits, sans lecture de transaction individuelle. Sa méthode doit être validée par R02 avant exécution.

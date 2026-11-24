# lpcost 0.2 — une position LP continue, valorisée jour par jour (R04-6)

RUGGER 01, 24/11/2026.
- Décision R04-6 (21:27Z), sous les conditions C1 et C2 de R02 (avis ancré).
- `lpcost/model.py` (0.1, PASS TECHNIQUE R02) est **inchangé**. Il est réutilisé : transactions, `share_after_others`,
  atterrissage, pires états.
- Le seul ajout est `lpcost/continuous.py`.
- Hors ligne, sur pools synthétiques seulement. Ce n'est pas un trade du Master.

## La position (`continuous_position`)

- **Mise notionnelle** = `stake_ppm` × la réserve WSOL de l'ÉTAT DE DÉCISION à l'ouverture. Elle est figée à
  5 000 ppm (0,5 %) et plafonnée à 0,5 % ; elle n'engage aucun capital.
- La moitié de la mise (mise // 2) achète le jeton de base sur le pire état d'atterrissage, avec la garde cpmmcost
  de 20 000 ppm.
- Dépôt proportionnel, arrondi par excès.
- Un seul retrait, à `end_time`, arrondi par défaut sur le pire état de sortie.
- Vente de tout le jeton de base au pire des 4 candidats.
- La période doit être un nombre entier de jours.

## La quantité du mot (C1) : l'écart à la détention, net de TOUS les coûts

- G(t) = V_LP(t) − V_DÉTENTION(t), au prix observé du pool, avec V_LP = 2 s(t) Q(t) et
  V_DÉTENTION = base déposée × Q/B + SOL déposé.
- **écart** = G(fin) − G(début) − coûts.
- **coûts** = entrée (moitié − jetons × P_début : frais, impact, latence, pire état) + sortie (avoirs LP marqués +
  restes − SOL reçu : arrondi du retrait, frais et impact de la vente) + 6 transactions à 105 000 lamports + loyers
  perdus.

**Marques.**
- Début : l'état d'atterrissage du dépôt.
- Fin : le pire état de sortie.
- Aux bornes de jour t_k : le premier état OBSERVÉ après t_k, c'est-à-dire les réserves journalisées avant le premier
  swap de block_time > t_k, avec notre part après les événements LP strictement antérieurs à ce swap. Ce marquage
  est exact et ne franchit jamais un événement LP.
- S'il n'y a plus de swap avant l'atterrissage de sortie, la marque est l'état de sortie.

**Valeurs journalières (C2).** Jour k = G(t_{k+1}) − G(t_k) − coûts / n. Leur somme est exactement l'écart, en
fractions.

**Identité exacte (descriptive).** Net absolu = SOL reçu − mise − transactions − loyers = écart + G(début) +
jetons × (P_fin − P_début). Le résidu est nul, et vérifié dans le code.

**Refus de garde.** Pas de position. Les transactions facturées sont réparties sur les n jours.

## Validation

- 22 tests sur `lpcost/tests` : les 13 de 0.1 et 9 nouveaux. Ils couvrent :
  - la mise à 0,5 % de la réserve de décision ;
  - l'identité, la somme journalière et C2 ;
  - un pool très actif (écart > 0) et une tendance (perte d'inventaire) ;
  - un recalcul indépendant des marques et de la sortie ;
  - un événement LP d'autrui entre une borne et le swap suivant ;
  - la garde (refus à 3 %, acceptée à 50 000 ppm et à 1 %) ;
  - les échecs et les loyers ;
  - les entrées.
- 24 mutants sur 24 détectés sur `continuous.py` (`MUTATIONS_lpcost_continuous_v0_2.json`, runner
  `mutations_lpcost_continuous_runner.py`). Deux mutants ÉQUIVALENTS ont été retirés, avec leur justification dans le
  JSON.

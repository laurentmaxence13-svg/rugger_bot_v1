# Seuil d'équilibre — G2-3 et N1 (R01, 26/11/2026, v0.1)

**Limite L1 (texte eba73e3f) :** le résultat livesim « ne peut servir ni à choisir ni à modifier une stratégie ». Cette note
éclaire la structure des coûts. Aucun levier tiré de ces données (taille, frais, sortie) ne peut fonder une nouvelle
expérience sans données neuves. Rien ici n'est un pré-enregistrement ni un verdict gelé. Jamais une transaction du
Master. Données déjà publiques seulement, hors ligne, 0 crédit : livesim d4933e7 (24 h, 3 pools, 21 signaux G2-3,
19 témoins) et pages pré-T0 6e27bf5 (P3, P3bis). Ni les pools ni la fenêtre du pilote. Méthode M1–M5 déclarée à R02
avant lecture et corrigée par R02 (a)–(e).

## 1. Coût aller-retour par position, mouvement de prix nul

Le coût comprend les frais du pool aux deux jambes, l'impact et le fixe gelé : 4 × 105 000 lamports (achat, vente,
fermeture WSOL, nettoyage), échecs gelés compris. Contrôle : sur les 21 positions publiées, le jeton acheté et le net
sont retrouvés à l'unité.

L'état d'achat est celui du modèle gelé, à chaque signal. Deux conventions de vente :
- **A** : la vente se fait sur l'état qui contient encore notre achat. L'impact s'annule alors.
- **B (cpmmcost)** : la vente se fait sur le pire de cet état et des réserves sans notre achat.

Valeurs en médiane.

| mise | frais 0,25 % : A / B | 0,50 % : A / B | 1 % : A / B |
|---|---|---|---|
| 0,1 SOL | 0,92 / 0,97 % | 1,42 / 1,47 % | 2,41 / 2,46 % |
| 0,5 SOL | 0,58 / 0,84 % | 1,08 / 1,34 % | 2,07 / 2,33 % |
| 1 SOL | 0,54 / 1,06 % | 1,04 / 1,55 % | 2,03 / 2,54 % |
| 5 SOL | 0,50 / 3,05 % | 0,99 / 3,53 % | 1,98 / 4,48 % |

- À 0,1 SOL, le fixe (0,42 %) et les frais du pool (0,50 %) font tout le coût.
- Au-delà de 0,5 SOL, l'impact domine en convention B : les pools ont 180 à 380 SOL de réserve.
- P3 : sur 29 692 swaps réels de 0,05 à 0,2 SOL, le modèle donne la sortie et les frais exacts à l'unité. L'impact
  à 0,1 SOL est de 0,004 à 0,031 %.
- P3bis (pages pré-T0) :
  - frais réels payés (médiane) : AEZjoU 5 000, G8kgi7 39 000 à 55 000, GdxFyc 105 000 lamports ;
  - ventes qui ferment déjà le WSOL dans la même transaction : 15 % (AEZjoU), 68 % (G8kgi7), 0 % (GdxFyc) ;
  - levier chiffré : un aller-retour en 2 transactions ramènerait le fixe de 0,42 % à 0,21 % à 0,1 SOL. Il n'est
    présentable que pour une nouvelle expérience.

## 2. Mouvement brut nécessaire et fréquence observée (horizon gelé : TP/SL ± 2 %, horloge 1 800 s)

**Mouvement d'équilibre (médiane), convention A, frais 0,25 %** : 0,92 % à 0,1 SOL, 0,59 % à 0,5 SOL, 0,54 % à 1 SOL,
0,51 % à 5 SOL. En convention B : 0,98 / 0,85 / 1,07 / 3,17 %.

**Part des entrées dont le mouvement réalisé dépasse ce seuil**, à 0,1 SOL et 0,25 % :

| entrées | n | part au-dessus du seuil | mouvement moyen / médian / p90 |
|---|---|---|---|
| signaux G2-3 | 21 | 9,5 % (2) | +0,52 % / −0,10 % / +0,55 % |
| témoin | 19 | 5,3 % (1) | +0,41 % / 0,00 % / +0,90 % |
| taux de base, chaque swap | 3 152 | 0,4 % | +0,01 % / −0,01 % / +0,01 % |
| taux de base espacé de ≥ 1 800 s | 98 | 2,0 % | +0,14 % / −0,01 % / +0,38 % |

**Pools du pilote, pré-T0** (g23b sur l'exécution à blanc, R02 ; n = 250, entrées dépendantes) :
- brut B : +0,068 % [−0,135 ; +0,281] ;
- coût : 0,934 % par position ;
- la borne haute du brut est sous les seuls frais du pool (0,50 %).

## 3. Verdicts francs (étiquettes descriptives, hors vocabulaire gelé des verdicts)

**G2-3 — hors de portée au p90, avantage improbable à ces coûts.**
- Le seuil est d'au moins 0,51 % pour toute mise, et de 0,92 % à 0,1 SOL. Il dépasse le p90 du taux de base :
  0,01 % sur toutes les entrées, 0,38 % sur les entrées espacées. Part observée au-dessus : 0,4 à 2,0 %.
- Les signaux dépassent le seuil plus souvent (9,5 %), mais :
  - n = 21 est insuffisant ;
  - la médiane des signaux est négative ;
  - leur moyenne (+0,52 %) tient à 2 sorties TP sur un seul pool (5zk4vh : +8,0 % et +4,5 %) ; les 18 signaux de
    6CQSpR sortent tous à l'horloge, avec un net négatif ; la moyenne reste sous le coût à 0,1 SOL.
- Sur les pools du pilote, la borne haute du brut avant coûts (0,28 %) est sous les frais du pool seuls. Aucun levier
  sur le fixe ne comble cet écart.
- Avec des frais de pool de 0,5 ou 1 %, l'écart grandit.

**N1 — improbable, n insuffisant (n = 3 pools × 1 jour ; pools qui ne sont pas ceux de N1).**
- Mise de 5 000 ppm de la réserve, frais 0,25 %, sur 12 jours, sans écart à la détention :
  - coût : 0,28 à 0,32 % ;
  - rotation journalière nécessaire (volume / réserve) : 0,22 à 0,25 ; à 0,1 SOL de mise : 0,70.
- Rotation observée sur 24 h : 0,33, 0,29 et 0,12. Deux pools sur trois sont au-dessus, avec une marge mince : environ
  +0,08 à +0,10 % sur 12 jours.
- Écart à la détention : quasi nul sur 24 h (prix final / initial 0,994 à 1,003). Sur 12 jours, il n'est PAS MESURÉ.
  Un écart de prix d'environ ± 9 % sur 12 jours suffit à effacer la marge.
- Aucun seuil de rotation ici n'est valable pour les pools du pilote N1.

Calcul : be_calc.py, sortie be_r01.json 61f7a661 ; P3 3e03f8a ; P3bis p3bis_r01.json 24eaa1f2 ; divergence il24.py.

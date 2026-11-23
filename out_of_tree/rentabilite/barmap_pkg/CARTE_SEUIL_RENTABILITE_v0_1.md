# T-R01-2 — Carte du seuil de rentabilité (v0.1) : avantage brut minimal pour un net nul

RUGGER 01, 23/11/2026.
- **Aucune donnée lue.** Seulement les modèles audités : courbe exacte `cpmmx.curve`, comme cpmmcost 0.3 ;
  constantes de papercost et de la chaîne gelée.
- Les chiffres sont reproductibles à l'octet (`barmap.carte.document()`, `CARTE_SEUIL_v0_1.json`).
- **Définition.** Brut = mouvement du prix médian entre la décision (avant notre achat) et la vente, en % de la
  mise de 0,1 SOL.
  - Notre impact est payé sur les deux jambes : c'est l'état défavorable X-1 que retient cpmmcost.
  - Le mouvement extérieur se fait à k constant ; les frais des autres traders sont ignorés (déclaré).
- **Contrôle de cohérence (testé).** La carte retrouve `cpmmcost.bar` : 1,12 % à 100 SOL, 2,92 % à 10 SOL. Elle
  retrouve aussi la barrière LaunchLab moyenne de W1 : ≈ 3,66 % compte fermé, ≈ 5,6 % loyer perdu (R02).

**Point de référence** : CPMM 0,25 %, réserve de 100 SOL, priorité de 100 000 lamports par tx, 0 échec, compte fermé, fermeture WSOL séparée → **1,12 %**.

## Une variable à la fois, autour du point de référence

| Levier | Valeurs → brut minimal |
|---|---|
| Palier de frais du pool (ppm ; seul 2 500 est U-1, les autres sont DÉCLARÉS) | 2500 → 1,12 % ; 10000 → 2,63 % ; 20000 → 4,67 % ; 40000 → 8,80 % |
| Réserve en SOL (position = 0,1 SOL) | 10 → 2,91 % ; 20 → 1,92 % ; 50 → 1,32 % ; 100 → 1,12 % ; 500 → 0,96 % ; 1000 → 0,94 % |
| Frais de priorité par tx (lamports, + 5 000 de base) | 0 → 0,72 % ; 10000 → 0,76 % ; 100000 → 1,12 % ; 500000 → 2,73 % ; 1000000 → 4,74 % |
| Taux d'échec par tx (chaque échec facturé, géométrique) | 0 → 1,12 % ; 10 % → 1,17 % ; 30 % → 1,30 % ; 50 % → 1,54 % ; 60 % → 1,75 % |
| Mode de loyer | closed → 1,12 % ; rent_lost → 3,06 % |
| Fermeture WSOL séparée | True → 1,12 % ; False → 1,02 % |
| Latence | NON MESURÉ : ce n'est pas un frais. Son coût est la dérive adverse pendant 4 slots, qui exige des prix (PAPER_LIVE S-3 ; pire cas H-1 de cpmmcost) |

## LaunchLab (même méthode, impact de courbe NON inclus)

| Palier | Compte fermé | Loyer perdu |
|---|---|---|
| 2500 ppm | 0,81 % | 2,75 % |
| 12500 ppm | 2,81 % | 4,75 % |
| 16700 ppm (moyenne W1) | 3,65 % | 5,59 % |
| 17500 ppm | 3,82 % | 5,75 % |
| 37500 ppm | 7,81 % | 9,75 % |

## Les leviers, classés par l'écart de barrière sur leur grille

| Rang | Levier | Écart (points de brut) |
|---|---|---|
| 1 | fee_tier_ppm | 7,68 |
| 2 | priority_lamports | 4,02 |
| 3 | venue_launchlab_w1_mean_vs_cpmm_025 | 2,53 |
| 4 | reserve_sol | 1,97 |
| 5 | rent_mode | 1,94 |
| 6 | failure_rate | 0,63 |
| 7 | wsol_separate_close | 0,11 |

**Les 3 leviers qui abaissent le plus la barrière** (sur la grille déclarée) :
1. **Palier de frais : rester sur les pools à 0,25 %.** Un pool à 1 % coûte déjà 2,63 %, à 4 % 8,80 %. Changer de lieu (courbe LaunchLab au taux moyen W1, 3,66 %) va dans le même sens : écart de 2,53 points.
2. **Frais de priorité.** À 0,1 SOL de mise, chaque tranche de 100 000 lamports par tx coûte ≈ 0,4 point sur 4 tx. Passer de 100 000 à 10 000 retire 0,36 point, mais au risque d'une latence plus longue, NON MESURÉE ici.
3. **Réserve du pool et mode de loyer (ex aequo, ≈ 1,9 à 2,0 points)** :
   - éviter les réserves de moins de 50 SOL (impact payé deux fois : 2,91 % à 10 SOL) ;
   - fermer le compte de jetons (+1,94 point si le loyer est perdu).
- Le taux d'échec vient ensuite (+0,63 point de 0 à 60 %), puis la fermeture WSOL dans la même transaction (−0,105 point).

**Bornes utiles pour choisir les hypothèses** (CPMM 0,25 %) :
- configuration favorable plausible (réserve de 500 SOL, priorité de 10 000, WSOL dans la même tx, compte fermé, 0 échec) : **0,59 %** ;
- configuration défavorable plausible (20 SOL, priorité de 100 000, 30 % d'échecs, loyer perdu) : **4,01 %**.
- Une hypothèse candidate doit donc viser un brut d'au moins ≈ 0,6 % (configuration favorable) à 1,1 % (référence) par position sur CPMM établi, et ≈ 3,7 % sur la courbe LaunchLab au taux moyen W1. Le palier LaunchLab à 2 500 ppm (0,81 %) n'inclut pas l'impact de la courbe : il n'est pas comparable.

**Limites déclarées.**
- Paliers CPMM autres que 0,25 % : à confirmer sur des AmmConfig lus.
- Frais des autres traders ignorés dans le mouvement extérieur.
- Impact de la courbe LaunchLab non inclus : il exige l'état de la courbe.
- Latence NON MESURÉE.

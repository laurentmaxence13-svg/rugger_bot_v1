# T-R01-7 — Causes des pertes et hypothèses économiques (v0.2)

RUGGER 01, 24/11/2026. Directive du propriétaire « priorité absolue aux résultats » (24/11, 12:40Z), relayée par
R04. **v0.2** : v0.1 (276bc716, ancrée au registre 104c9a24, CONFORME R02) avec les 2 précisions de R02.
**Sources uniquement** :
- tableau consolidé v0.2 [TC] (ebf63663) ;
- Dossier A § 1 [DA] (recalcul R02) ;
- w1decomp 0.2 [WD] (df0d9cbb) ;
- barmap 0.1 [BM] (CARTE e5cc3091, JSON 31f7a36a) ;
- cpmmcost 0.3 [CC].

Aucune nouvelle lecture de W1, aucun résultat du pilote, aucune cellule D3. % de la mise de 0,1 SOL ; « NM » = NON
MESURÉ.

## 1. Pourquoi on a perdu

| Stratégie (n) | Brut | Frais courbe | Tx | Loyer | Net | Source |
|---|---|---|---|---|---|---|
| MASTER W1 (128) | **−0,72** [−3,11 ; +1,65] | 3,34 | 0,21 | non modélisé [SL] ; ≈ 2,04 [LP] | **−4,27** [SL] (identité de décomposition brut − coûts, [DA] [WD]) ; moyenne publiée −4,26 [−6,69 ; −1,95] ; ≈ −6,3 [LP] | [DA] § 1 ; [WD] ; [TC] |
| Placebo W1 | −0,19 | 4,20 | 0,21 | [SL] | −4,60 | [DA] § 1 |
| C-D, palier ≤ 0,25 % (46) | −1,94 | 0,49 | 0,21 | perdu | −4,59 [LP] | [TC] |
| Placebo palier bas (35) | +0,89 (comparateur, observé après regard) | 0,50 | 0,21 | perdu | −1,82 [LP] | [TC] |
| C-A, L1, L3, crible L1, T1, T3′ | NM (aucune décomposition) | NM | NM | — | −5,45 à −10,62 | [TC] |

**Constat.**
- **Le brut est nul ou négatif.** L'IC du MASTER contient 0. Aucune stratégie n'a de brut mesuré > 0.
- **Les coûts font l'essentiel de la perte.** Pour le MASTER, coûts = 3,55 points sur 4,27, soit **83 %** de la perte
  [SL]. En loyer perdu : ≈ 5,6 sur 6,3, soit **≈ 89 %**.
- **La sélection** pèse −0,53 point de brut face au placebo (−0,72 contre −0,19). C'est un écart non apparié, dans le
  bruit.
- **La sortie** : NM séparément. Le seul indice est descriptif et postérieur à la décision ([WD] D2 : pic médian à 5
  slots, premier passage sous l'entrée à 17 slots, avec 4 slots de latence).

**Conclusion.** **Cause dominante : le coût d'exécution sur la courbe LaunchLab** (≈ 3,3 % de frais aller-retour,
plus le loyer). Il faudrait un signal brut > 3,5 % pour l'absorber, et aucun signal mesuré n'en approche.

## 2. La barre à franchir (brut nécessaire pour un net nul) [BM]

| Lieu / variable | Barre |
|---|---|
| LaunchLab, palier moyen W1 (16 700 ppm) | **3,65 %** compte fermé ; **5,59 %** loyer perdu |
| LaunchLab, autres paliers | 0,81 % (0,25 %) ; 2,81 % (1,25 %) ; 3,82 % (1,75 %) ; 7,81 % (3,75 %), compte fermé |
| **CPMM 0,25 %, réserve 100 SOL** (base) | **1,12 %** |
| CPMM 0,25 %, par réserve | 2,91 % (10 SOL) ; 1,92 % (20) ; 1,32 % (50) ; 0,96 % (500) ; 0,94 % (1 000) |
| CPMM, autres paliers (100 SOL) | 2,63 % (1 %) ; 4,67 % (2 %) ; 8,80 % (4 %) |
| CPMM 0,25 %, priorité 0 / 10 000 / 500 000 lamports | 0,72 % / 0,76 % / 2,73 % |
| CPMM 0,25 %, loyer perdu ; 60 % d'échecs | 3,06 % ; 1,75 % |

**Leviers, du plus fort au plus faible** (étendue de la barre sur la grille) :
- palier de frais (7,68 pts) ;
- priorité (4,02) ;
- lieu LaunchLab → CPMM 0,25 % (2,53) ;
- réserve (1,97) ;
- loyer (1,94) ;
- échecs (0,63) ;
- WSOL (0,11).

Le levier déjà actionné : **changer de lieu**, de 3,65 % à 1,12 % (−2,5 pts). Le suivant : **la priorité**, qui
abaisse 1,12 % à 0,76 % à 10 000 lamports. Son effet sur l'atterrissage est NM.

## 3. Portefeuille d'hypothèses (toutes en CPMM établi, palier 0,25 %, sorties ±2 % / 30 min)

| Hyp. | Qui nous paie, et pourquoi ce ne serait pas déjà arbitré | Brut à observer | n (pilote) | Jours | Crédits |
|---|---|---|---|---|---|
| **R-CP1** | Le vendeur pressé non informé (choc de liquidité) ; l'arbitrage inter-lieux ramène le prix, mais pas forcément en 4 slots sur un pool peu suivi | ≥ 1,12 % + δ 0,5 ≈ **1,6 %** | 155 | 155 / déclencheurs par jour : NM ici (compté par R03, étape 1 (2)) ; D_max = 3,33 j | ≤ 50 000 (pilote en cours) |
| **B1** | L'acheteur tardif : diffusion lente de l'information de détail | ≈ 1,6 % | 155 | même collecte que R-CP1 | 0 de plus |
| **G2-1** | Comme R-CP1, quand la chute vient de swaps directs (non informés) | ≈ 1,6 % | 155 (≈ ½ des déclencheurs R-CP1) | ≥ 2 × celle de R-CP1 | ≤ 50 000 (fenêtre disjointe) |
| **G2-2** | Le vendeur qui solde jusqu'à l'épuisement ; on achète la stabilisation | ≈ 1,6 % | 155 | NM | ≤ 50 000 |
| **G2-3** | Les vendeurs face à une demande large et nouvelle | ≈ 1,6 % | 155 | NM | ≤ 50 000 |
| **G3-1** | Le trader qui a déplacé un pool (impact payé), rattrapé par l'arbitrage entre pools frères | > b = 1,12 % par construction | 155 | NM ; paires probablement rares | ≤ 2 × 50 000 |
| **G3-2** | Signal d'un apport de capital informé ; barre abaissée à ≈ 1,02 % (200 SOL : `barmap.cpmm_gross_required`, hors de la grille ancrée, comme dans GEN-3 v0.2) | ≈ 1,5 % | 155 (si ≥ 30 dépôts avant T0) | NM ; dépôts probablement rares | 0 au-delà de la fenêtre |

**Dispersion.** n = 155 suppose σ = 2,5 %, une déclaration plausible avec des sorties bornées à ±2 %.
- La dispersion W1 sur la courbe est **≈ 13,7 %**, déduite de l'IC groupé du MASTER (largeur 4,74, n = 128). Elle
  n'est **pas transposable** : sorties non bornées, autre lieu.
- Avec elle, il faudrait ≈ 4 600 positions pour δ = 0,5 %.

## 4. Classement : plausibilité économique × vitesse du verdict

1. **R-CP1 et B1.** Le pilote est en cours (G-1 sous ≤ 3,33 j de données), à 0 crédit de plus. Elles se départagent
   sur les mêmes données : si les deux sont NÉGATIVES, la famille « prix sur 10 min » est close d'un coup.
2. **G2-3.** Elle est indépendante du déclencheur de prix et survit à 1.
3. **G3-2.** Coût bas, mais une population probablement trop faible.
4. **G2-1 et G2-2.** Retirées d'office si R-CP1 et B1 sont NÉGATIVES.
5. **G3-1.** Mécanisme fort, mais paires rares et données doublées.

**Familles A–H sans intérêt à cause de la barre** (chiffres [BM] et [TC]) :
- **B2**, momentum LaunchLab : barre 3,65 % contre un brut MASTER de −0,72 %.
- **E1**, largeur de demande sur la courbe : T1 net −5,59 %, barre 3,65 %.
- **D3 / C-E**, palier bas LaunchLab : espérance ≈ +0,07 % contre une barre de 0,81 %.
- **H3** : même barre ; n = 414 sur 48 à 64 jours.
- **H2**, C-C : vide, ≈ 140 jours pour 414.
- **Tout pool CPMM ≥ 1 %** : barre ≥ 2,63 %.
- **A2** (choc de taille) : ce n'est pas la barre, mais l'arbitrage qui agit avant nos 4 slots (catalogue v0.2).

## 5. Hypothèses nouvelles attaquant la cause dominante (le coût d'exécution)

- **N1 — « Être payé du frais au lieu de le payer » : fourniture de liquidité sur CPMM 0,25 %.**
  - Les preneurs paient 0,25 % par swap. Le LP en reçoit 84 % (parts protocole 12 % et fonds 4 % de l'AmmConfig U-1,
    D4FP). Cette config porte aussi un frais créateur de 500 ppm (0,05 %) ; son application aux pools est NM.
  - L'acteur qui paie est le preneur de liquidité. Ce n'est pas arbitré, car c'est la rémunération normale du risque
    de sélection adverse (perte d'inventaire).
  - Réfutable : frais perçus moins perte d'inventaire < 0.
  - Il n'existe aucun modèle de coût LP audité : **NM**. Il faudrait un nouveau code (à annoncer avant de l'écrire).
    Ce n'est pas un trade du Master au sens actuel : **décision du propriétaire** avant tout travail.
- **N2 : aucune.** Baisser la priorité est un levier de coût, pas une hypothèse d'avantage. Son effet sur
  l'atterrissage se mesure en PAPER_LIVE (S-3), pas par un essai.

Toute hypothèse de cette note est une CANDIDATE à 0 essai. G2-x et G3-x supposent le texte D ou une tranche d'essais.
Rien ici ne constitue un résultat économique. Le seul verdict proche est G-1 de R-CP1 et B1.

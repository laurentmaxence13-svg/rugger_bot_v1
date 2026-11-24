# R04-2 — Dossier N1 « fournisseur de liquidité » sur CPMM 0,25 % : étude hors ligne (v0.1)

RUGGER 01, 24/11/2026. Décision R04-2 (24/11, 20:38Z, par délégation du propriétaire) : étude HORS LIGNE.
- Aucune donnée lue, aucun code écrit, aucun essai consommé.
- Rien ici n'est un résultat économique. « NM » = NON MESURÉ.
- N1 n'est pas un trade du Master : il ne compte jamais pour 50/20.

## 1. Qui paie, et pourquoi ce ne serait pas déjà arbitré

- **Qui paie.** Chaque preneur paie le frais de palier, 0,25 % du montant d'entrée.
  - Les parts protocole (12 %) et fonds (4 %) de l'AmmConfig U-1 (D4FP) sont prélevées à part.
  - Le reste reste dans les réserves et revient aux fournisseurs de liquidité : **f_LP = 0,25 % × 84 % = 0,21 % du
    volume**.
  - Un frais créateur de 0,05 % existe aussi dans D4FP. Son application aux pools est NM ; il ne revient pas aux
    fournisseurs.
- **Ce que paie le fournisseur.** Quand le prix bouge ailleurs, les arbitragistes alignent le pool en lui achetant au
  prix ancien. Le fournisseur leur cède cet écart : c'est la **LVR**, perte face au rééquilibrage (Milionis, Moallemi,
  Roughgarden et Zhang, 2022 ; référence externe, non vérifiée dans cette session).
  - Pour un pool x·y = k, la LVR vaut **σ² / 8 de la valeur du pool par unité de temps**, σ étant la volatilité du
    prix.
  - Avec des frais, les arbitrages sont moins fréquents : σ² / 8 est alors une borne haute de la perte.
- **Pourquoi ce ne serait pas déjà arbitré.** La rémunération des fournisseurs est l'équilibre d'un marché à
  l'entrée libre. Elle n'est positive que là où l'apport de liquidité est insuffisant par rapport au volume.
  L'hypothèse est donc de trouver ces pools, c'est-à-dire ceux où le **flux non informé** (le détail) est élevé par
  rapport à la volatilité.

## 2. La condition économique, en une ligne

Le net par jour, en part de la valeur déposée, vaut :

**f_LP × (volume / TVL) − σ_j² / 8 − coûts fixes amortis.**

Le seuil de rotation journalière (volume / TVL) au-dessus duquel les frais couvrent la LVR, sans coûts fixes :

| σ journalière du prix | LVR par jour | Rotation journalière nécessaire |
|---|---|---|
| 2 % | 0,005 % | **2,4 %** |
| 5 % | 0,031 % | **15 %** |
| 10 % | 0,125 % | **60 %** |
| 20 % | 0,50 % | **238 %** |

Volume, TVL et σ des pools : NM. Ce sont des mesures de marché, sans rendement de stratégie. Elles sont calculables
sur les pages déjà collectées, sur décision.

**Coûts fixes d'un aller-retour** pour une position de 0,1 SOL :
- échange de la moitié en jeton de base, puis retour : 2 × 0,25 % × 0,05 SOL ;
- dépôt, retrait et 2 échanges : 4 transactions.

| Cas | Coût fixe de l'aller-retour |
|---|---|
| Valeur gelée, 105 000 lamports par transaction | **0,445 % de la mise** |
| Sensibilité, frais médians de 8 000 lamports | **0,057 %** |

L'aller-retour doit donc durer plusieurs jours pour amortir le coût gelé, sauf avec une rotation très élevée.

## 3. Données nécessaires

- Par swap :
  - montants d'entrée et de sortie ;
  - frais (trade, créateur) ;
  - réserves avant le swap ;
  - événements LP (dépôts, retraits).
- Tout est dans `cpmmx.timeline`, construit à partir des pages GTFA « full » : **aucun prix externe** n'est
  nécessaire. On compare à la détention des mêmes jetons, valorisée au prix du pool.
- Pages disponibles :
  - les pages A2r des 24 pools U-2 (fenêtre et pré-T0 : à confirmer par R03) ;
  - les pages de la fenêtre G2-3 des 4 pools une fois collectées. Leur emploi pour N1 exige une fiche N1 ancrée AVANT
    leur lecture.
- Crédits : **0 au-delà des collectes déjà autorisées** si ces pages suffisent ; sinon 0,103 × transactions.

## 4. Projet de modèle de coût `lpcost` (spécification seule, sans code)

1. **Entrée au début du jour j.**
   - Échange de 0,05 SOL en jeton de base, valorisé exactement par `cpmmcost` (frais, impact, garde, latence de
     4 slots).
   - Dépôt proportionnel aux réserves : on obtient une part s du pool (arrondi des jetons LP par défaut).
2. **Détention.** La valeur de la part suit les réserves, frais de LP compris. Les parts protocole et fonds sont
   déjà déduites (`timeline.after_swap` avec les parts lues de l'AmmConfig).
3. **Sortie à la fin du jour j** : retrait de s × réserves, puis échange de tout le jeton de base en SOL
   (`cpmmcost`, au pire cas H-1).
4. **Net** = SOL reçus − 0,1 SOL − 4 transactions − loyer perdu éventuel du compte LP.
   - Ventilé en frais perçus, perte d'inventaire (LVR réalisée) et coûts fixes.
   - Il y a une identité exacte à résidu nul, comme cpmmcost.
5. **Témoin** : la détention des mêmes jetons sur le jour, ou la détention de 0,1 SOL. Descriptif.

Code, tests et mutants sont à écrire seulement sur décision, puis audités par R02. Estimation : ≈ 6 à 8 h, hors
audit.

## 5. Statistique

- **Unité** : le pool-jour, une position de 0,1 SOL ouverte au début du jour et fermée à la fin.
- **Inférence** : celle de g23five (bootstrap par blocs pool-jour stratifié par pool). Mêmes planchers : ≥ 30
  pool-jours, ≥ 3 pools, Kish ≥ 2,5, aucun pool > 50 %. Même garde « sans le pool le plus fourni ».
- **Univers** : pools nommés avant T0, par un critère d'ACTIVITÉ fixé d'avance. Proposition : rotation estimée ≥ 15 %
  par jour sur les 7 jours avant T0, le seuil d'équilibre à σ_j = 5 %. Aucun rendement.
- **n et durée** :
  - 4 pools × 12 j = 48 pool-jours ;
  - σ par pool-jour NM, donc la puissance est NM ;
  - la cible de 155 pool-jours demanderait ≈ 13 pools sur 12 j, ou 4 pools sur ≈ 39 j.
- **Essais** : 1 (une tranche nouvelle, ou un réemploi décidé par le propriétaire).

## 6. Risques déclarés

- Flux informé au-delà de la LVR (initiés, jetons manipulés).
- Retrait d'un gros fournisseur.
- Jetons Token-2022 à frais de transfert, exclus par `pool_gate`.
- MEV sur le dépôt et le retrait (garde à l'échange).
- La LVR théorique ne remplace pas la mesure : le verdict ne porte que sur le net mesuré par `lpcost`.

## 7. Décision de principe à demander au propriétaire

« J'autorise une recherche PAPER côté fournisseur de liquidité sur CPMM 0,25 % :
- un modèle de coût `lpcost` audité par R02 ;
- d'abord sur des pages déjà collectées, avec une fiche ancrée avant leur lecture ;
- 1 essai ;
- 0 crédit au-delà des collectes autorisées.

Ce n'est pas un trade du Master et cela ne compte pas pour 50/20. »

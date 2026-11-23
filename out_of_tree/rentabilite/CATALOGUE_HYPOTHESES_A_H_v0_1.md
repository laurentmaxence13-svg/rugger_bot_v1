# R-1 — Catalogue des stratégies candidates, familles A à H, et classement (v0.1)

RUGGER 01, 23/11/2026. Directive stratégique finale du propriétaire (« ORDRE PERMANENT DE RECHERCHE DE RENTABILITÉ »),
relayée par R04. Soumis à l'audit de R02.

**Ce que ce document fait, et ne fait pas.**
- C'est un catalogue d'hypothèses écrites AVANT toute donnée qui les évaluerait.
- Aucune hypothèse n'est tirée de W1 par sélection de paramètres. Les seuils proposés viennent de règles déjà
  préenregistrées (R-CP1) ou de leur miroir exact.
- Aucune n'est évaluée ici. Aucun essai n'est consommé par ce document.
- Le vocabulaire est fermé : aucune hypothèse n'est qualifiée autrement que par un verdict NÉGATIF / INCONCLUSIF, ou
  par un GO_PILOTE / CONFIRMÉ futur.

## 0. Cadre commun

**Budget d'essais.**
- N = 168 utilisés sur un plafond de 170, hors HW1. R-CP1 porte N à 169.
- **Sous le plafond actuel, il ne reste donc qu'UNE hypothèse de plus.**
- Au-delà, il faut un nouveau plan de recherche dont R02 fixe le plafond N AVANT les données (note de réorientation
  v0.2, f366e1cc). C'est une décision du propriétaire, à présenter avec ce catalogue.

**Ce que W1 permet et interdit.**
- W1 a été lu : il ne sert jamais à choisir un seuil.
- Ses résultats (tableau consolidé v0.2, ebf63663) sont des contraintes. Sur la courbe LaunchLab à frais standards,
  aucune règle n'a de brut positif mesuré, et les 7 stratégies évaluées sont NÉGATIVES.
- Toute hypothèse LaunchLab exige des données NEUVES (W2).

**Barrières de coûts**, en % de la mise de 0,1 SOL, calculées par les modèles audités :

| Lieu | Barrière : brut nécessaire pour un net nul | Source |
|---|---|---|
| CPMM établi, 0,25 %, compte fermé | **0,82 %** : 2 × 0,25 % + 3 × 105 000 lamports. **≈ 1,12 %** avec l'impact à 100 SOL de réserve et la fermeture WSOL séparée ; ≈ 1,92 % à 20 SOL | cpmmcost 0.3 (`fixed_cost_share`, `bar`) ; C-a |
| CPMM : chaque échec | +0,105 % par transaction échouée ; un achat refusé par la garde coûte 0,105 % sans entrée | cpmmcost 0.3 |
| CPMM : latence | H-1 au pire cas des deux côtés ; sensibilité à 10 slots | cpmmcost 0.3 |
| LaunchLab, palier moyen W1 | **≈ 3,55 %** si le compte est fermé (frais de courbe 3,34 % + tx 0,21 %) ; **≈ 5,6 %** avec le loyer perdu (+2,05 %) | Dossier A § 1 ; closedacct 0.2 (+1,93 point si le compte est fermé) |
| LaunchLab, palier 2 500 ppm | ≈ 0,71 % (+0,105 % de nettoyage si le compte est fermé) | Dossier A § 1 ; fiche C-E |

**n requis** (formule de cpmmprereg : n = ⌈((z₁₋α + z₀,₈) σ / δ)²⌉, avec δ = +0,5 % net) :

| Cas | n |
|---|---|
| σ = 2,5 % (hypothèse déclarée pour une fourchette de ±2 %), pilote à α = 0,05 | 155 |
| Même σ, deux hypothèses sur le même pilote (α = 0,05/2) | 197 |
| Même σ, confirmation à α = 0,05/3 | 221 |
| σ = 5 % (sorties plus larges), pilote | 619 |
| LaunchLab, Dossier B v1.9 (σ 13,7 %, δ 2 %, K = 3) | 414 |

**Données CPMM.**
- La collecte du pilote R-CP1 couvre 24 pools pendant D jours, pour ≤ 50 000 crédits, dans l'offre Free à 0 $.
- **Une hypothèse CPMM préenregistrée AVANT T0 peut s'évaluer sur la MÊME collecte, sans coût de données de plus.**
  Elle consomme seulement son essai, et l'α doit être partagé.
- Variables enregistrées à chaque swap (`cpmmx.timeline.Swap`) :
  - slot, temps de bloc, rang dans la transaction ;
  - sens ; réserves avant et après ;
  - montants et frais (`SwapEvent`) ;
  - `depth` : appel direct, ou via un autre programme (routeur).
- Le pool enregistre aussi les variations de liquidité (`lp_changes`).
- **Le signataire du swap n'est PAS dans la timeline** : il faut un petit code nouveau, à auditer, qui le lit dans la
  transaction brute déjà collectée.

**Données LaunchLab** : les 34 `FEATURES` causales de `statelab.signals`, par exemple :
- `unique_buyers`, `buyers_10s`, `net_flow_60s_lamports` ;
- `price_change_30s`, `drawdown_from_peak` ;
- `top5_token_share`, `fee_rate_ppm_causal`.

## 1. Les hypothèses

Format de chaque fiche : mécanisme | variables à la décision (source) | barrière | données | témoin | n | essais |
réfutation rapide.

### A — Retour à la moyenne

**A1. R-CP1 : rebond après une chute (CPMM établi). DÉJÀ PRÉENREGISTRÉE (fiche v0.2, 66ab4ab4).**
- **Mécanisme.** Une vente non informée et pressée déplace le prix d'un pool à 0,25 %. Les arbitrages entre lieux le
  ramènent ensuite vers le prix du marché. Celui qui achète après la chute capte une partie de ce retour.
- **Variables.**
  - Le spot après chaque swap (réserves journalisées, parts de l'AmmConfig appliquées).
  - Le nombre de swaps sur 600 s.
  - Le délai depuis la dernière position. Source : `cpmmx.timeline`.
- **Barrière.** ≈ 0,82 % à 1,12 % ; garde de l'achat à 2 %.
- **Données.** Pilote : ≤ 100 + ≤ 50 000 crédits, 0 $.
- **Témoin.** Apparié par pool, à date aléatoire.
- **n.** 155 au pilote, n_c ≥ 221 en confirmation.
- **Essais.** 1 (N = 169).
- **Réfutation rapide.** OUI : G-1 donne NO-GO dès que la borne haute est < 0.

**A2. Retour après un choc de taille (CPMM établi).**
- **Mécanisme.** C'est le même que A1, mais déclenché par UN swap de vente supérieur à 1 % de la réserve en quote, et
  non par une chute sur 10 minutes.
- **Variables.** La taille du swap rapportée à `quote_before` (timeline).
- **Barrière.** Comme A1. **Mais l'arbitrage rapide agit dans le même slot ou le suivant.** Avec 4 slots de latence et
  H-1 au pire cas, la part du retour qui reste à capter est probablement faible.
- **Données.** La même collecte que A1 : 0 coût de plus.
- **Témoin.** Apparié par pool.
- **n.** 197 si elle partage le pilote avec A1.
- **Essais.** 1.
- **Réfutation rapide.** OUI (G-1).

### B — Momentum

**B1. Miroir de R-CP1 : achat après une HAUSSE de 3 % ou plus en 10 minutes (CPMM établi).**
- **Mécanisme.** L'attention et la diffusion lente de l'information sur des jetons à flux de détail entretiennent
  le mouvement. C'est l'hypothèse exactement opposée à A1, avec les mêmes paramètres. Ce n'est ni un réglage ni une
  sélection : c'est le seul choix de seuil sans degré de liberté.
- **Variables.** Celles de A1.
- **Barrière.** Celle de A1.
- **Données.** La même collecte : 0 coût de plus.
- **Témoin.** Le même.
- **n.** 197 si elle partage le pilote avec A1.
- **Essais.** 1.
- **Réfutation rapide.** OUI.
- **Intérêt particulier.** A1 et B1 se départagent sur les mêmes données. Si les deux sont NÉGATIVES, la famille
  « mouvement de prix sur 10 minutes » est close d'un coup sur CPMM.

**B2. Momentum sur la courbe LaunchLab.**
- **Statut.** Déjà couvert par le MASTER (`confirmed_momentum` dans l'union du scoreur), NÉGATIF sur W1.
- **Proposition.** Aucune nouvelle variante (risque de surajustement élevé).

### C — Cassure (breakout)

**C1. Nouveau plus haut sur 24 h avec un volume d'au moins 2 fois la médiane sur 24 h (CPMM établi).**
- **Mécanisme.** Un franchissement de résistance avec un volume anormal signale une demande nouvelle.
- **Variables.** Il faut 24 h d'historique par pool avant chaque décision.
- **Barrière.** ≈ 1,12 %.
- **Données.** **24 h de collecte en plus par pool**, à chiffrer par R03. C'est hors du pilote actuel.
- **Témoin.** Apparié.
- **n.** 155 ou plus, avec σ inconnu : il serait plus grand avec des sorties larges (619 si σ = 5 %).
- **Essais.** 1.
- **Réfutation.** Plus lente : il y a peu d'événements par pool.

### D — Liquidité

**D1. Profondeur minimale.**
- **Ce que c'est.** Une CONDITION DE COÛT, pas une source d'avantage. Une réserve ≥ 100 SOL ramène l'impact sous
  environ 0,3 %.
- **Statut.** Déjà incluse dans U-3. Ce n'est pas une hypothèse : 0 essai.

**D2. Retrait de liquidité (LP qui retire).**
- **Usage.** EXCLUSION : ne pas entrer dans les N minutes qui suivent un retrait (`lp_changes`).
- **Mécanisme.** Un retrait annonce une réserve plus mince et parfois une sortie d'initiés.
- **Proposition.** Filtre de protection, à ajouter seulement par un préenregistrement neuf. Il coûterait 1 essai s'il
  est testé seul. Non prioritaire.

**D3. Palier LaunchLab bas avec compte fermé (C-E).**
- **Statut.** Figé pour W2. Espérance ≈ 0 (+0,07 %, observé après regard). Résultat attendu : NO-GO ou INCONCLUSIF.
- **n.** 414, sur 48 à 64 jours. Non recommandé.

### E — Participants

**E1. Largeur de la demande (T1, LaunchLab).**
- **Statut.** NÉGATIF sur W1 (−5,59 %). L'écart avec le placebo est descriptif et non apparié.
- **Usage possible.** Seulement combinée à un lieu à frais bas (voir H2), et sur des données neuves.

**E2. Demande dispersée face à une offre concentrée (CPMM établi).**
- **Mécanisme.** Plusieurs acheteurs distincts contre un seul vendeur important : le vendeur liquide, la demande de
  fond reste.
- **Variables.** Le signataire de chaque swap (transaction brute). C'est un nouveau code, à auditer (§ 0).
- **Barrière.** ≈ 1,12 %.
- **Données.** La même collecte que A1.
- **Témoin.** Apparié.
- **n.** 197 ou plus.
- **Essais.** 1.
- **Réfutation.** OUI.

**E3. Part des routeurs (`depth` > 1).**
- **Mécanisme.** Les swaps appelés par un autre programme (agrégateurs, robots) sont plus informés que les swaps
  directs. Une chute faite surtout par des appels directs serait plus « non informée » : c'est une variante plus
  fine de A1.
- **Variables.** `depth` (timeline).
- **Coût.** 1 essai.
- **Risque de surajustement.** Moyen : il faudrait fixer un seuil.

### F — Volatilité

**F1. Filtre de régime : R-CP1 seulement quand la volatilité réalisée sur 1 h est sous sa médiane.**
- **Mécanisme.** En régime calme, une chute de 3 % est plus souvent un choc de liquidité qu'une nouvelle
  information.
- **Problème.** La médiane devrait être fixée sur des données pré-T0, hors pilote. C'est 1 paramètre de plus,
  1 essai, avec un risque de surajustement moyen.

### G — Sélection et exclusion des pools

**G1. Exclusions de protection.**
- **Contenu.** Token-2022 avec frais de transfert, réserves rompues, programmes non décodables.
- **Statut.** Déjà dans U-4 (`pool_gate`). 0 essai. Ce n'est pas une source d'avantage.

**G2. Exclure les pools dominés par un seul compte** (part du premier signataire supérieure à 50 % des swaps sur
24 h).
- **Mécanisme.** On évite les pools manipulés ou tenus par un seul robot.
- **Coût.** 1 essai, et le nouveau code du signataire (§ 0).

**G3. Changer de lieu : CPMM établi à 0,25 % plutôt que la courbe LaunchLab.**
- **Statut.** Ce n'est pas une règle, c'est le cadre de A1, B1 et E2. Il fait passer la barrière de ≈ 3,55 % à
  ≈ 0,82 % – 1,12 %.

### H — Combinaisons

**H1. A1 avec la condition E2** (chute faite par un seul vendeur, au moins 5 acheteurs distincts dans les 10 min).
- **Mécanisme.** On combine l'argument de A1 (choc non informé) et celui de E2.
- **Coût.** 1 essai, nouveau code du signataire.
- **Risque de surajustement.** Plus élevé : 2 conditions.

**H2. Largeur de demande (E1) sur pool CPMM après migration.**
- **Statut.** C-C est vide : environ 3 migrations par jour. Puissance impossible (environ 140 jours pour 414). Non
  proposée.

**H3. Palier bas LaunchLab avec compte fermé et largeur de demande.**
- **Exigence.** Données W2, n = 414, palier bas rare.
- **Statut.** Non proposée.

## 2. Classement proposé, selon les 8 critères du propriétaire

Notation de 1 (défavorable) à 3 (favorable) :

| Hypothèse | Plausibilité | Information nouvelle | Surajustement (3 = faible) | Coût | Durée | Données | Réfutabilité | Confirmation | Total |
|---|---|---|---|---|---|---|---|---|---|
| **A1 R-CP1** | 2 | 3 | 3 (aucun paramètre choisi sur des données) | 3 (0 $) | 2 (D jours) | 3 (collecte prévue) | 3 (G-1) | 2 (221 entrées, fenêtre neuve) | **21** |
| **B1 miroir momentum** | 2 | 3 (clôt la famille avec A1) | 3 (miroir exact) | 3 (0 donnée de plus) | 3 (même pilote) | 3 | 3 | 2 | **22** |
| E2 dispersion des participants | 2 | 3 | 2 (1 seuil) | 2 (code nouveau) | 3 | 2 | 3 | 2 | 19 |
| E3 part des routeurs | 2 | 2 | 2 | 3 | 3 | 3 | 3 | 2 | 20 |
| A2 choc de taille | 1 (arbitrage plus rapide que nous) | 2 | 2 | 3 | 3 | 3 | 3 | 2 | 19 |
| F1 régime de volatilité | 1 | 1 | 1 | 3 | 3 | 2 | 3 | 2 | 16 |
| C1 cassure | 2 | 2 | 2 | 1 (collecte de plus) | 1 | 1 | 2 | 1 | 12 |
| H1 A1 et E2 | 2 | 2 | 1 | 2 | 3 | 2 | 3 | 1 | 16 |
| D3 / C-E palier bas, LaunchLab | 1 (≈ 0 observé) | 1 | 2 | 1 (W2, 48 à 64 jours) | 1 | 1 | 2 | 1 | 10 |
| E1, H2, H3 (LaunchLab ou migrations) | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 9 |

**Proposition (au propriétaire, après audit de R02).**
1. **A1 (R-CP1)**, déjà prête. Il faut la source U-2 et le GO de l'étape 0.
2. **Dernier essai sous le plafond actuel : B1**, préenregistrée AVANT T0 sur la MÊME collecte, sans aucun coût de
   données. Points à trancher par R02 :
   - comment partager α : soit α = 0,05/2 pour les deux, soit A1 garde son α gelé et B1 prend un α séparé ;
   - si la fiche A1 v0.2 doit être amendée avant son gel.
3. Si le propriétaire ouvre un nouveau plan avec un plafond N fixé par R02 : **E3, puis E2** (code du signataire à
   écrire et auditer), sur la même collecte ou sur la confirmation.
4. **Non recommandées** : C1 (données et durée), F1 et H1 (surajustement), et toute piste LaunchLab sur la courbe
   (D3, E1, H2, H3), dont l'espérance est ≈ 0 ou négative.

**Ce que ce catalogue ne garantit pas.** Aucune de ces hypothèses n'a de brut mesuré. Le seul argument chiffré est
la barrière : environ 3 à 5 fois plus basse sur CPMM établi que sur la courbe LaunchLab.

# Rentabilité chiffrée — tableau consolidé de toutes les stratégies évaluées, et chemin vers un premier verdict indépendant (v0.2)

RUGGER 01, 23/11/2026. Directive du propriétaire « PRIORITÉ ABSOLUE : RENTABILITÉ CHIFFRÉE », relayée par R04.
Soumis à R02 pour vérification.
- **v0.2** = v0.1 (c3bb1689) avec les corrections K-1 à K-5 de l'audit R02 (`AUDIT_TABLEAU_RENTABILITE_v0_1_R02.md`, sha
  e93a83b8…) et la grille R02 b83af1be.
- Chaque chiffre est RECOPIÉ d'une source déjà ancrée ou vérifiée par R02. Aucun n'est recalculé ici, et aucune donnée
  scellée n'est lue.
- Une case sans source vérifiable porte « — (non mesuré) ».
- C-B, C-C, C-E et R-CP1 n'ont aucune position : leur ligne ne porte aucun chiffre de rendement.
- Tous les rendements sont en % de la mise de 0,1 SOL, par position clôturée, en rejeu historique PAPER sur W1. Aucun
  n'est un trade du Master opérationnel, et aucun ne compte pour 50/20.

## Sources

| Code | Document | sha256 | Ancrage ou vérification |
|---|---|---|---|
| [DA] | `w1_loss_analysis/DOSSIER_A_PERTES_ET_CANDIDATS_W2_v1.md` (v1.8) | b5be9396… | Lecture W1 ea152a32 ; ventilation da1e5758 / f5d1388e ; R02 f2f86f74 et 2333dcff ; recalcul R02 du § 1 : brut −0,721, courbe 3,339, tx 0,210, net −4,266 ; placebo −0,191 / 4,202 / 0,210 / −4,600 |
| [NT] | `w1_loss_analysis/NOTE_PISTES_TARDIVES_CPMM_v0_1.md` | 7841eb6d… | latelab 7351512d (moitié 1) ; moitié 2 lue par R02 (T1 : f3c6c9e3) ; cdgate 2b173f10 |
| [CE] | `w1_loss_analysis/FICHE_C_E_v0_2.md` | 6d00179d… | R02 85d2e959 |
| [RO] | `w2_ready/NOTE_REORIENTATION_SI_CB_ECHOUE_v0_2.md` | f366e1cc… | Corrections R02 intégrées |
| [VB] | `w1_exploratory_measures/NOTE_VOIE_B_PROJECTION_v0_4.md` (v0.4.1) | 6c86c464… | **Caduque** pour le coût de C-B : la voie B est close (8cfead0e). Le cadre en vigueur est la fiche R02 v1.1 (e2a93ea8), voir la tâche 2 |
| [W1P] | `W1_PROTOCOL_v2.6.2.json` (gelé) | 0b88317a… | Gel R02 |
| [PR] | `cpmm_pilot/cpmmprereg_pkg/PREENREGISTREMENT_CPMM_RCP1_v0_2.md` | 66ab4ab4… | PASS R02 (059a3b5) |
| [NP] | `cpmm_pilot/NOTE_CPMM_ETAT_ET_PILOTE_v0_2.md` | b4c6562c… | R02 |

**Grille de R02.** Toutes les cases ont été recoupées avec `GRILLE_SOURCES_RENTABILITE_R02_v1_0.md` (sha b83af1be…).
Quatre cases en viennent :
- l'IC du MASTER W1 (3aa36aa3, 068d54dd) ;
- son coût complet (0167b2d1) ;
- l'ancrage du crible L1 (20aba3f5) ;
- le verdict de T3′.

**Méthode d'IC commune** (latelab, latesel, cdgate, w1loss) : intervalle à 95 % bilatéral de la moyenne, par
bootstrap de grappes de créateurs (le pool si le créateur est absent), 2 000 tirages, graine 20261120.

**Vocabulaire du verdict** : règle R-0.1 de R02 et ordre gelé du § 2.2 (2792655a). Le § 3.2 n'est pas utilisé : c'est
la règle de PAPER_LIVE.
- INCONCLUSIF passe AVANT NÉGATIF : n < 30, ou une ligne non interprétable, donne INCONCLUSIF, IC publié.
- Sinon, NÉGATIF si la borne haute de l'IC est < 0.
- Aucun verdict positif n'est possible ici (R-0.6 non remplie, aucune donnée indépendante).
- Les IC viennent de 2 000 tirages, graine 20261120.

**Régimes de coûts**, signalés dans chaque case de net :
- **[SL]** : moteur gelé SANS loyer (le loyer est supposé rendu, non modélisé) ;
- **[LP]** : loyer PERDU, inclus.
Partout : 0,1 SOL ; atterrissage après 4 slots ; 2 transactions de 105 000 lamports ; **0 échec en primaire** (non
mesuré) ; aucun MEV.

**Observations post hoc** (palier 2 500 avec n = 12 ; écart apparié T6 ; brut des entrées tardives à ≥ 450 slots) :
elles ne vont jamais en verdict et ne sont jamais présentées comme des gains.

## Tâche 1 — Tableau consolidé

| Stratégie | n réel (grappes) | Brut moyen | Net moyen, moteur gelé [régime] | Net en coûts complets | Frais courbe / tx | Latence / échecs | IC (95 %, bootstrap par grappes) | Comparaison au placebo | Statut | Verdict | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **MASTER W1** (≡ référence) | 128 | −0,72 % | **−4,26 %** [SL] | ≈ −6,3 % [LP] : ajout additif du loyer, SANS IC (0167b2d1) | 3,34 % / 0,21 % | 4 slots / 0 | [−6,69 ; −1,95] | Placebo W1 −4,60 % [SL], non apparié | EXPLORATOIRE (lecture préliminaire ; le verdict officiel W1 n'est pas produit) | **NÉGATIF** | ea152a32 ; 3aa36aa3 ; 068d54dd ; [DA] § 1 |
| **C-A** (porte T1 à 12 500 ppm) | 46 | — (non mesuré) | **−5,45 %** [SL] | — (non mesuré) | — (non mesuré) | 4 slots / 0 | [−10,89 ; −0,55] | — (non mesuré) | EXPLORATOIRE (porte) ; RETIRÉ | **NÉGATIF** | f5d1388e ; f2f86f74 ; [DA] § 3 |
| **latelab L1** (`age:120`, découverte, moitié 1) | 178 (174) | — (non mesuré : latelab ne décompose pas les frais) | **−5,14 %** [LP] | — (non mesuré) ; loyer récupéré −3,21 % | — (non mesuré) | 4 slots / 0 ; horloge 60 s | [−7,42 ; −2,90] | Placebo n = 270 : −5,67 % [LP], descriptif, non apparié | EXPLORATOIRE (découverte) | **NÉGATIF** | 7351512d ; [NT] § 1 |
| **latelab L3** (`age:300`, moitié 1) | 82 (77) | — (non mesuré) | **−7,81 %** [LP] | — (non mesuré) ; loyer récupéré −5,94 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−10,77 ; −4,76] | Même placebo (−5,67 %) | EXPLORATOIRE | **NÉGATIF** | 7351512d ; [NT] § 1 |
| **latelab L1, crible** (moitié 2) | 106 (83) | — (non mesuré) | **−10,29 %** [LP] | — (non mesuré) ; loyer récupéré −8,47 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−13,81 ; −6,35] | Placebo n = 200 : −10,41 % [LP], descriptif | EXPLORATOIRE (crible pré-enregistré) | **NÉGATIF** | 20aba3f5 ; [NT] § 2 bis |
| **T1 latesel** (crible, moitié 2) | 34 (34) | — (non mesuré) | **−5,59 %** [LP] | — (non mesuré) ; loyer récupéré −3,67 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−11,17 ; −0,09] | Placebo de la moitié 2 : −10,41 %, descriptif, NON apparié | EXPLORATOIRE (seuils fixés sur la moitié 1) | **NÉGATIF** | f3c6c9e3 ; [NT] § 2 bis |
| **T3′ latesel** (crible, moitié 2) | 23 (23) | — (non mesuré) | **−10,62 %** [LP] | — (non mesuré) ; loyer récupéré −8,80 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−18,03 ; −4,18] | Placebo de la moitié 2 : −10,41 % | EXPLORATOIRE | **INCONCLUSIF** (n < 30) | [NT] § 2 bis |
| **C-C** (CPMM après migration) | **aucune position** | — | — | — | — | — | — | — | Emplacement VIDE : 12 pools migrés, porte inatteignable | Pas de verdict | [DA] § 3 ; d4a01934 |
| **C-D** (tardif, palier ≤ 2 500 ppm) | 46 (41) | −1,94 % | **−4,59 %** [LP] | — (non mesuré) ; à 10 slots −4,70 % [LP] ; loyer récupéré −2,64 % | 0,49 % / 0,21 % | 4 slots (sensibilité 10) / 0 | [−7,40 ; −2,42] | Placebo au palier ≤ 2 500 : −1,82 % [LP], descriptif, non apparié | EXPLORATOIRE (porte W1) ; RETIRÉ | **NÉGATIF** | 2b173f10 ; [NT] § 2 ter |
| **Placebo du palier bas** (comparateur de C-D) | 35 (34) | +0,89 % | **−1,82 %** [LP] | — (non mesuré) ; loyer récupéré +0,17 %, sans IC | 0,50 % / 0,21 % | 4 slots / 0 | [−3,29 ; −0,33] | C'est lui, le comparateur | Comparateur ; observé APRÈS regard | **NÉGATIF** (comparateur, pas une règle) | 2b173f10 ; [NT] § 2 ter |
| **C-E** (précoce, palier ≤ 2 500 ppm, compte fermé) | **aucune position** (jamais évalué ; figé pour W2 seulement) | — | — | — | — | — | — | Seul effet cité : +0,17 % sur le placebo (loyer récupéré), sans IC | Recevable, NON recommandé | Pas de verdict. NO-GO ou INCONCLUSIF déclaré d'avance | [CE] ; 85d2e959 |
| **C-B** (une hypothèse HW1 gelée) | **aucune position** | — | — | — | — | — | — | — | **SCELLÉ (HW1)** : HW1 non lue, B1 non signé | Pas de verdict | [DA] § 3 ; w1chain 0.2 |
| **CPMM R-CP1** (pools établis) | **aucune position** | — | — | — | — | — | — | — | INDÉPENDANT (prévu : fenêtre neuve après T0) ; préenregistré | Pas de verdict | [PR] |

**Lecture du tableau (constat, sans extrapolation).**
- **9 lignes ont un IC**, et toutes ont un net moyen négatif :
  - **8 sont NÉGATIVES** : MASTER, C-A, L1, L3, crible L1, T1, C-D et le placebo du palier bas (comparateur) ;
  - **1 est INCONCLUSIVE** : T3′, avec n < 30.
- **Aucune démonstration de rentabilité nette n'existe aujourd'hui.** Les deux seules pistes qui peuvent encore en
  produire une, C-B et R-CP1, n'ont aucune position.

## Tâche 2 — Chemin le plus court vers un PREMIER verdict économique indépendant

### C-B

| Rubrique | Contenu |
|---|---|
| **Étapes** | 1. Verdict officiel W1 (B1) par l'**exception GCP limitée à A2** (7350829b, 813ab515), avec le paquet v2.6.6 (490a28f1), puis l'ancrage par R02. La voie B (8cfead0e) est caduque. La sauvegarde W1 n'est PAS un prérequis : le propriétaire l'a suspendue, et le risque est accepté au § 7 de la fiche v1.1. 2. Lecture HW1 UNIQUE (w1chain 0.2, hors ligne, par R03). C-B est la première hypothèse « EXPLORATOIRE POSITIVE » ou « CONFIRMÉE SUR W1 » dans l'ordre HW1-5, HW1-1, HW1-2, HW1-4, HW1-3. **S'il n'y en a aucune, l'emplacement reste vide et il n'y aura jamais de verdict C-B.** 3. W2 : collecte LaunchLab sur des fenêtres NEUVES (w2arms orch), puis verdict `w2arms.cb` (Dossier B v1.9 : c1 à c5, α = 0,05/3, 10 000 tirages ; pour HW1-5, net > 0 à 10 slots et sans les 5 meilleurs pools) |
| **Données** | Les archives W1 existantes pour les étapes 1 et 2, puis une collecte W2 (pages `getTransactionsForAddress` du programme LaunchLab) |
| **Volume** | n_min = **414** positions du candidat retenu (Dossier B v1.9) |
| **Durée** | Étape 1 : ≈ **49 h** (fiche R02 v1.1, e2a93ea8). Étape 2 : — (non mesuré). Étape 3 : pour HW1-5, ≈ 125 positions par jour, soit ≈ 3,3 jours de données ([DA] § 3), plus la collecte et le calcul ; pour les autres hypothèses HW1, plus long, non mesuré |
| **Coût exact et source** | Étape 1 : coût de référence ≈ **53,9 $ HT, soit ≈ 64,7 $ TTC pour 49 h**, sous le plafond de l'exception, **66 $ TTC** (fiche R02 v1.1 e2a93ea8 ; exception 7350829b, 813ab515). Le tarif est à reconfirmer le jour J. A1 (80 $) et l'option C sont hors cadre : il faudrait une décision nouvelle. Étape 2 : 0 $. Étape 3 : par fenêtre de 4 jours (1 612 800 slots ≈ 7,47 équivalents P0), ≈ 220 000 à 333 000 crédits, à raison de 29 400 à 44 600 crédits par équivalent P0 avec f = 1 ([W1P] `credit_budget/unit`). C'est une déclaration de R01, que R02 n'a pas recalculée. C'est 0 $ dans l'offre Free (1 M crédits par mois ; relevés 31f63f90, 28917f6d, eeaaad19), tant que `getTransactionsForAddress` y reste servi : c'est un fait mesuré, non expliqué ([W1P] `cap_scope`) |
| **Essais consommés** | **5**, ceux de la lecture HW1 (N : 168 → 173). L'évaluation W2 du candidat retenu coûte **+0** (Dossier B v1.9 § 5, admission à +0 ; R-0.5) |
| **PREMIÈRE opération autorisée aujourd'hui** | **Aucune.** Clause manquante : la **signature du § 7 de la fiche R02 v1.1 (e2a93ea8)** par le propriétaire, pour le paquet v2.6.6 (490a28f1). Cadre des autorisations : registre a4b9d467 et amendement d784ef31 (R02) |

### CPMM R-CP1

| Rubrique | Contenu |
|---|---|
| **Étapes** | 1. Le propriétaire choisit la source de la liste U-2 (hôte Raydium, ou crédits Helius via `getProgramAccounts`). 2. Fiche de gel ancrée par R02 : liste U-2 hachée à T0, code cpmmcost 0.3 (7deb7b7) et cpmmprereg 0.2 (059a3b5). 3. Étape 0 : vecteurs publics V-1′, ≤ 100 crédits ; audit du décodeur C-1 à C-3 (G-0), sinon STOP. 4. Comptage des DÉCLENCHEURS sur les 7 jours avant T0 (A1 (b)), puis l'arrêt de puissance. 5. Étape 1 : pilote sur 24 pools pendant D jours, ≤ 50 000 crédits. **G-1 = premier verdict économique indépendant** : NO-GO si la borne haute unilatérale à 95 % est < 0, INCONCLUSIF si moins de 30 entrées ou moins de 20 pools, sinon GO_PILOTE. GO_PILOTE est le mot maximal de G-1 : il ne fait que proposer une confirmation. 6. Seulement après GO_PILOTE : une confirmation sur une fenêtre NOUVELLE (CONFIRMÉ, NON CONFIRMÉ ou INCONCLUSIF). C'est la SEULE voie vers un verdict positif |
| **Données** | Transactions brutes des 24 pools CPMM établis sur la fenêtre du pilote ; les 7 jours avant T0, pour le comptage seul ; les AmmConfig lus et hachés |
| **Volume** | Pilote : cible de puissance **155 entrées** (α 0,05, puissance 0,80) ; plancher de G-1 : 30 entrées ET 20 pools. Confirmation : n_c = **221** entrées si σ_c = 2,5 %, davantage si le σ du pilote est plus grand ([PR] § 5) |
| **Durée** | D jours. R03 le recalcule pour 24 pools (CP-3, [NP] § 2.4) : — (non mesuré). L'attendu sort du comptage des déclencheurs ; c'est une estimation de planification, optimiste |
| **Coût exact et source** | Étape 0 : ≤ 100 crédits. Étape 1 : ≤ 50 000 crédits, comptage A1 (b) inclus. Les deux sont dans l'offre Free existante, à 0 $ ([W1P] `data/provider` ; relevés du propriétaire), à condition que le quota restant du mois, relevé par le propriétaire, le permette. Source U-2 : hôte Raydium, 0 crédit (accès réseau à autoriser) ; ou `getProgramAccounts` Helius, à chiffrer par R03 sur la tarification archivée (b6794b16). Confirmation : non chiffrée tant que le pilote n'est pas fait. Les crédits sont une déclaration de R01, que R02 n'a pas recalculée |
| **Essais consommés** | **1** (R-CP1 et son témoin : 168 → 169, plafond 170). Il n'en restera alors qu'un seul |
| **PREMIÈRE opération autorisée aujourd'hui** | **Aucune.** Clause manquante : la décision du propriétaire sur la source U-2 et le GO de l'étape 0 ([PR] § 9). Tout le code est prêt et PASS R02. Cadre des autorisations : registre a4b9d467 et amendement d784ef31 (R02) |

**Comparaison des deux chemins.**
- **R-CP1** est le chemin le plus court et le moins cher vers un premier verdict indépendant (G-1). Il coûte 0 $ dans
  l'offre Free et 1 essai. Il demande deux décisions : la source U-2, puis le GO de l'étape 0.
- **C-B** passe d'abord par une dépense cloud ≤ 66 $ TTC (≈ 64,7 estimés) et par 5 essais. Il peut aussi s'arrêter sans aucun
  verdict, si aucune hypothèse HW1 n'est positive.
- **Ni l'un ni l'autre ne produira de verdict positif avant une confirmation sur données neuves.**

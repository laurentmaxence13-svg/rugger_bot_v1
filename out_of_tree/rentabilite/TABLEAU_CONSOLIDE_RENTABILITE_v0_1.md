# Rentabilité chiffrée — tableau consolidé de toutes les stratégies évaluées, et chemin vers un premier verdict indépendant (v0.1)

RUGGER 01, 23/11/2026. Directive du propriétaire « PRIORITÉ ABSOLUE : RENTABILITÉ CHIFFRÉE », relayée par R04.
Soumis à R02 pour vérification.
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
| [VB] | `w1_exploratory_measures/NOTE_VOIE_B_PROJECTION_v0_4.md` (v0.4.1) | 6c86c464… | Avis R02 257bf065 |
| [W1P] | `W1_PROTOCOL_v2.6.2.json` (gelé) | 0b88317a… | Gel R02 |
| [PR] | `cpmm_pilot/cpmmprereg_pkg/PREENREGISTREMENT_CPMM_RCP1_v0_2.md` | 66ab4ab4… | PASS R02 (059a3b5) |
| [NP] | `cpmm_pilot/NOTE_CPMM_ETAT_ET_PILOTE_v0_2.md` | b4c6562c… | R02 |

**Méthode d'IC commune** (latelab, latesel, cdgate, w1loss) : intervalle à 95 % bilatéral de la moyenne, par
bootstrap de grappes de créateurs (le pool si le créateur est absent), 2 000 tirages, graine 20261120.

**Vocabulaire du verdict** : règle gelée de R02 (§ 3.2), appliquée à l'IC publié.
- NÉGATIF si la borne haute est < 0. Une borne haute bilatérale à 95 % < 0 implique une borne haute unilatérale à
  95 % < 0.
- POSITIF EN PAPER exige en plus 50 cycles qualifiés, 20 créateurs et un net > 0 avec 1 échec : aucune ligne ne
  l'atteint.
- INCONCLUSIF sinon.

**Modèle d'exécution commun à W1** (moteur gelé) : 0,1 SOL ; atterrissage après 4 slots ; 2 transactions de
105 000 lamports ; 0 échec (gelé) ; frais de courbe causaux.

## Tâche 1 — Tableau consolidé

| Stratégie | n réel (grappes) | Brut moyen | Net moyen, moteur gelé | Net en coûts complets | Frais courbe / tx | Latence / échecs modélisés | IC (méthode, niveau) | Comparaison au placebo | Statut | Verdict (§ 3.2) | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **MASTER W1** | 128 | −0,72 % | **−4,26 %** (loyer NON modélisé) | — (non mesuré). L'arithmétique du [DA] donne ≈ −6,3 % avec un loyer perdu de 2,05 % (mesure P0), mais ce n'est pas un rejeu | 3,34 % / 0,21 % | 4 slots / 0 | — (non mesuré pour le net global ; seules les classes de la ventilation en ont) | Placebo W1 −4,59 % ; écart apparié **+1,23 % [−2,23 ; +4,82]** (grappes, 95 %) : non significatif | EXPLORATOIRE (lecture préliminaire ; le verdict officiel W1 n'est pas produit) | Non attribuable : pas d'IC du net | [DA] § 1 et § 8 ; ea152a32 ; da1e5758 |
| **latelab L1** (`age:120`, moitié 1) | 178 (174) | — (non mesuré : latelab ne décompose pas les frais) | **−5,14 %** (loyer perdu) | — (échecs non modélisés) ; loyer récupéré −3,21 % | — (non mesuré) | 4 slots / 0 ; horloge 60 s | [−7,42 ; −2,90], 95 % | Placebo descriptif, non apparié : −5,67 % [−7,54 ; −3,75] | EXPLORATOIRE (découverte) | **NÉGATIF** | [NT] § 1 ; 7351512d |
| **latelab L3** (`age:300`, moitié 1) | 82 (77) | — (non mesuré) | **−7,81 %** | — ; loyer récupéré −5,94 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−10,77 ; −4,76], 95 % | Même placebo (−5,67 %) | EXPLORATOIRE | **NÉGATIF** | [NT] § 1 ; 7351512d |
| **latelab L1, crible** (moitié 2) | 106 (83) | — (non mesuré) | **−10,29 %** | — ; loyer récupéré −8,47 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−13,81 ; −6,35], 95 % | Placebo moitié 2 : −10,41 % [−13,02 ; −7,36], descriptif | EXPLORATOIRE (crible pré-enregistré) | **NÉGATIF** | [NT] § 2 bis |
| **latesel T1** (moitié 2) | 34 (34) | — (non mesuré) | **−5,59 %** | — ; loyer récupéré −3,67 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−11,17 ; −0,09], 95 % | Placebo moitié 2 : −10,41 %. L'écart d'environ +5 points est descriptif et NON apparié | EXPLORATOIRE (seuils fixés sur la moitié 1) | **NÉGATIF** | [NT] § 2 bis ; f3c6c9e3 |
| **latesel T3'** (moitié 2) | 23 (23) | — (non mesuré) | **−10,62 %** | — ; loyer récupéré −8,80 % | — (non mesuré) | 4 slots / 0 ; 60 s | [−18,03 ; −4,18], 95 % | Placebo moitié 2 : −10,41 % | EXPLORATOIRE ; n < 30, sous le plancher | **NÉGATIF** | [NT] § 2 bis |
| **C-A** (MASTER, palier ≤ 15 000 ppm, lu à 12 500) | 46 | — (non mesuré dans mes sources) | **−5,45 %** | — (non mesuré) | — (non mesuré dans mes sources) | 4 slots / 0 | [−10,89 ; −0,55], 95 % | — (non mesuré) | EXPLORATOIRE (porte) ; RETIRÉ | **NÉGATIF** | [DA] § 3 ; da1e5758 / f5d1388e ; R02 2333dcff |
| **C-C** (CPMM après migration) | **aucune position** | — | — | — | — | — | — | — | Emplacement VIDE : 12 pools migrés, porte inatteignable | — | [DA] § 3 ; R02 d4a01934 |
| **C-D** (tardif, palier ≤ 2 500 ppm) | 46 (41) | **−1,94 %** | **−4,59 %** (loyer perdu de 2,04 % inclus) | — (échecs non modélisés) ; à 10 slots −4,70 % ; loyer récupéré −2,64 % | 0,49 % / 0,21 % | 4 slots (sensibilité 10) / 0 ; glissement à l'achat −3,5 % | [−7,40 ; −2,42], 95 % | Placebo à palier bas : −1,82 %, descriptif, non apparié | EXPLORATOIRE (porte W1) ; RETIRÉ | **NÉGATIF** | [NT] § 2 ter ; 2b173f10 |
| **C-E** (précoce, palier ≤ 2 500 ppm, compte fermé) | **aucune position** (jamais évalué ; figé pour W2 seulement) | — | — | — | — | — | — | — | Recevable, NON recommandé (espérance ≈ 0, δ +2 %) | — | [CE] ; R02 85d2e959 |
| **Placebo du palier bas** (comparateur de C-D) | 35 (34) | **+0,89 %** | **−1,82 %** (loyer perdu de 2,04 % inclus) | — (échecs non modélisés) ; loyer récupéré +0,17 %, ≈ +0,07 % avec le frais de nettoyage de 105 000 lamports | 0,50 % / 0,21 % | 4 slots / 0 ; glissement à l'achat +0,5 % | [−3,29 ; −0,33], 95 % | C'est lui, le comparateur | EXPLORATOIRE, observé APRÈS regard | **NÉGATIF** (loyer perdu) | [NT] § 2 ter ; 2b173f10 ; [CE] |
| **C-B** (une hypothèse HW1 gelée) | **aucune position** | — | — | — | — | — | — | — | **SCELLÉ (HW1)** : lisible seulement après le verdict officiel W1 | — | [DA] § 3 ; w1chain 0.2 |
| **CPMM R-CP1** (pools établis) | **aucune position** | — | — | — | — | — | — | — | INDÉPENDANT (prévu : fenêtre neuve après T0) ; préenregistré | — | [PR] |

**Lecture du tableau (constat, sans extrapolation).**
- Les 9 lignes chiffrées ont toutes un net moyen négatif. Les 8 lignes qui ont un IC du net sont toutes NÉGATIVES :
  la borne haute est sous 0.
- Un seul brut positif est mesuré : celui du placebo à palier bas, +0,89 %. C'est une observation faite après regard,
  pas une règle.
- **Aucune démonstration de rentabilité nette n'existe aujourd'hui.** Les deux seules pistes qui peuvent encore en
  produire une, C-B et R-CP1, n'ont aucune position.

## Tâche 2 — Chemin le plus court vers un PREMIER verdict économique indépendant

### C-B

| Rubrique | Contenu |
|---|---|
| **Étapes** | 1. Verdict officiel W1 sur le cloud (paquet A2, dernière version v2.6.6, d0c2ccd), ancré par R02. Prérequis du [VB] § 4 : la sauvegarde W1 est terminée ; au 20/11, le lot 6 attendait un nouveau jeton du propriétaire. Son état actuel n'est pas dans mes sources. 2. Lecture HW1 UNIQUE (w1chain 0.2, hors ligne, par R03). C-B = la première hypothèse « EXPLORATOIRE POSITIVE » ou « CONFIRMÉE SUR W1 » dans l'ordre HW1-5, HW1-1, HW1-2, HW1-4, HW1-3. **Si aucune : l'emplacement reste vide, et il n'y aura jamais de verdict C-B.** 3. W2 : collecte LaunchLab sur des fenêtres NEUVES (w2arms orch). Verdict `w2arms.cb` (Dossier B v1.9 : c1 à c5, α = 0,05/3, 10 000 tirages ; pour HW1-5, net > 0 à 10 slots et sans les 5 meilleurs pools) |
| **Données** | Les archives W1 existantes pour les étapes 1 et 2, puis une collecte W2 (pages `getTransactionsForAddress` du programme LaunchLab) |
| **Volume** | n_min = **414** positions du candidat retenu (Dossier B v1.9) |
| **Durée** | Étape 1 : ≈ 46 à 52 h (option A1), ≈ 36 à 43 h (A2) ou ≈ 5 à 10 h (C), selon le [VB] § 1-2. Étape 2 : — (non mesuré). Étape 3, pour HW1-5 : ≈ 125 positions par jour, soit ≈ 3,3 jours de données ([DA] § 3), plus le temps de collecte et de calcul ; pour les autres hypothèses HW1 : plus long, non mesuré |
| **Coût exact et source** | Étape 1 : A1 ≈ 61 à 70 $ TTC (plafond 80) ; A2 ≈ 48 à 57 $ (plafond 66) ; C ≈ 8 à 15 $ (plafond 17). Source : tarif 1,048112 $/h relevé le 14/11, « à revérifier par le propriétaire » ([VB] § 2). Étape 2 : 0 $. Étape 3 : par fenêtre de 4 jours (1 612 800 slots ≈ 7,47 équivalents P0), ≈ 220 000 à 333 000 crédits, à raison de 29 400 à 44 600 crédits par équivalent P0 avec f = 1 ([W1P] `credit_budget/unit`). C'est 0 $ dans l'offre Free (1 M crédits par mois, relevés 31f63f90, 28917f6d, eeaaad19), à condition que `getTransactionsForAddress` y reste servi : c'est un fait mesuré, non expliqué ([W1P] `cap_scope`) |
| **Essais consommés** | 5 pour la lecture HW1 (N : 168 → 173). Le décompte de l'évaluation W2 du candidat est à confirmer par R02 (non trouvé dans mes sources) |
| **PREMIÈRE opération autorisée aujourd'hui** | **Aucune.** Clause manquante : l'accord écrit du propriétaire pour l'étape 1 (option A1, A2 ou C, montant maximal TTC, DEADLINE), selon le [VB] § 4, plus la fin de la sauvegarde W1 |

### CPMM R-CP1

| Rubrique | Contenu |
|---|---|
| **Étapes** | 1. Le propriétaire choisit la source de la liste U-2 (hôte Raydium, ou crédits Helius via `getProgramAccounts`). 2. Fiche de gel ancrée par R02 : liste U-2 hachée à T0, code cpmmcost 0.3 (7deb7b7) et cpmmprereg 0.2 (059a3b5). 3. Étape 0 : vecteurs publics V-1′, ≤ 100 crédits ; audit du décodeur C-1 à C-3 (G-0), sinon STOP. 4. Comptage des DÉCLENCHEURS sur les 7 jours avant T0 (A1 (b)), puis l'arrêt de puissance. 5. Étape 1 : pilote sur 24 pools pendant D jours, ≤ 50 000 crédits. **G-1 = premier verdict économique indépendant** : NO-GO si la borne haute unilatérale à 95 % est < 0, INCONCLUSIF si moins de 30 entrées ou moins de 20 pools, sinon GO_PILOTE. 6. Seulement après GO_PILOTE : une confirmation sur une fenêtre NOUVELLE (CONFIRMÉ, NON CONFIRMÉ ou INCONCLUSIF). C'est la SEULE voie vers un verdict positif |
| **Données** | Transactions brutes des 24 pools CPMM établis sur la fenêtre du pilote ; les 7 jours avant T0, pour le comptage seul ; les AmmConfig lus et hachés |
| **Volume** | Pilote : cible de puissance **155 entrées** (α 0,05, puissance 0,80) ; plancher de G-1 : 30 entrées ET 20 pools. Confirmation : n_c = **221** entrées si σ_c = 2,5 %, davantage si le σ du pilote est plus grand ([PR] § 5) |
| **Durée** | D jours. R03 le recalcule pour 24 pools (CP-3, [NP] § 2.4) : — (non mesuré). L'attendu sort du comptage des déclencheurs ; c'est une estimation de planification, optimiste |
| **Coût exact et source** | Étape 0 : ≤ 100 crédits. Étape 1 : ≤ 50 000 crédits, comptage A1 (b) inclus. Les deux sont dans l'offre Free existante, à 0 $ ([W1P] `data/provider` ; relevés du propriétaire), à condition que le quota restant du mois, relevé par le propriétaire, le permette. Source U-2 : hôte Raydium, 0 crédit (accès réseau à autoriser) ; ou `getProgramAccounts` Helius, à chiffrer par R03 sur la tarification archivée (b6794b16). Confirmation : non chiffrée tant que le pilote n'est pas fait |
| **Essais consommés** | **1** (R-CP1 et son témoin : 168 → 169, plafond 170). Il n'en restera alors qu'un seul |
| **PREMIÈRE opération autorisée aujourd'hui** | **Aucune.** Clause manquante : la décision du propriétaire sur la source U-2 et le GO de l'étape 0 ([PR] § 9). Tout le code est prêt et PASS R02 |

**Comparaison des deux chemins.**
- **R-CP1** est le chemin le plus court et le moins cher vers un premier verdict indépendant (G-1). Il coûte 0 $ dans
  l'offre Free et 1 essai. Il demande deux décisions : la source U-2, puis le GO de l'étape 0.
- **C-B** passe d'abord par une dépense cloud de 8 à 70 $ TTC et par 5 essais. Il peut aussi s'arrêter sans aucun
  verdict, si aucune hypothèse HW1 n'est positive.
- **Ni l'un ni l'autre ne produira de verdict positif avant une confirmation sur données neuves.**

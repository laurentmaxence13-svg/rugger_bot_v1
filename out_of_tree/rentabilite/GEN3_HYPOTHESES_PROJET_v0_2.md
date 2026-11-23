# T-R01-3 — Génération 3, hors de la famille « 10 min » : deux fiches en PROJET (v0.2)

RUGGER 01, 23/11/2026. Relance du propriétaire (« identifier les prochaines hypothèses indépendantes économiquement
justifiées »), relayée par R04. Soumis à R02 pour recevabilité.

**v0.2.**
- R02 a jugé la v0.1 (7c3c5282) RECEVABLE EN PROJET (audit a3f194dc).
- Cette version intègre ses réserves en texte seul, marquées **[R02 a3f194dc]**.
- Aucune règle d'entrée, aucun seuil ni aucune note de la grille n'est modifié.

**Statut : PROJET.**
- Rien n'est ancré, aucun essai n'est consommé.
- **Indépendantes de R-CP1** : aucune des deux n'utilise de déclencheur de prix sur 10 minutes. Elles survivent à
  tout verdict de la génération 1.
- **Interdits respectés** :
  - aucune cellule ni classe de W1 ;
  - aucune donnée de confirmation ;
  - rien de HW1 ;
  - aucun résultat de pilote.
- Chaque barrière de coûts vient de la carte T-R01-2 (barmap 0.1, f99c456 ; CARTE_SEUIL_RENTABILITE_v0_1 e5cc3091).

## 0. Cadre commun (b4edc143 § 2 ; a21f90f3)

- **Lieu.** Pools Raydium CPMM établis, univers U-1 à U-4.
- **Ordre, sortie, coûts, garde.** Ceux de R-CP1 (cpmmcost 0.3 ; TP/SL ±2 %, horloge de 30 min ; compte fermé ;
  garde de 20 000 ppm), sauf mention contraire.
- **Fenêtre.** Une génération = une fenêtre DISJOINTE des générations 1 et 2. Il y faut une autorisation de crédits
  distincte et une autorisation chiffrée d'essais au-delà de 173 (174 et 175).
  - **[R02 a3f194dc]** Les essais 174 et 175 demandent une NOUVELLE tranche du propriétaire, distincte du texte D de
    la génération 2, avec des crédits distincts.
- **α.**
  - Pilote : 0,05 par hypothèse (n = 155, mot maximal GO_PILOTE).
  - Confirmation sur une fenêtre NOUVELLE : α₃ = 0,025 × 2⁻¹ = **0,0125** (b4edc143 § 2).
  - Holm avec K = 2 : premier pas 0,00625 → **n_c = 279** (σ_c = 2,5 %, δ = +0,5 %) ; 238 si une seule hypothèse
    reste.
  - **[R02 a3f194dc]** α₃ et ces n_c ne valent que sous l'option (i) du texte D. Avec l'option (ii), ils sont à
    recalculer avant toute fiche de gel.
- **Seuils.** Uniquement par un principe externe déclaré, ou une médiane de population avant T0 (méthode A1 (b)).
- **Code.** Il sera écrit sur le modèle de cpmmgen2 si la génération 3 est retenue : règle, témoin, comptage avant
  T0 ; tests et mutants ; audit R02 avant le gel.

## G3-1 — « Écart inter-pools » (loi du prix unique)

- **Mécanisme.**
  - Le même jeton se négocie dans plusieurs pools CPMM à WSOL, de paliers différents.
  - Un gros swap dans un pool écarte son prix de celui du pool frère. L'arbitrage doit ramener les deux prix.
  - **L'acteur qui perd** est le trader dont le swap a déplacé le pool : il a payé l'impact, et l'arbitrage le
    récupère.
- **Variables à la décision.**
  - Spot après chaque swap des DEUX pools du même mint (`cpmmx.timeline`, réserves journalisées, parts AmmConfig).
  - Temps de bloc.
  - L'écart se mesure au dernier état connu de chaque pool, au temps t (causal).
- **Entrée.**
  - Au swap i du pool A, au temps t : spot_A / spot_B − 1 ≤ −b, où B est le pool frère du même mint, à son
    dernier swap ≤ t.
  - On achète dans A (le moins cher) ; délai de 3 600 s par paire.
  - **b = barrière de la carte pour A**, soit 1,12 % (0,25 %, 100 SOL). C'est un principe externe déclaré : on
    n'entre que si l'écart couvre au moins nos coûts d'aller-retour.
- **Sortie.** Celle de R-CP1 (TP +2 % / SL −2 % sur la valeur exacte, horloge de 30 min). Une sortie à la
  convergence (|écart| ≤ 0,25 %) serait un 2e seuil : elle n'est pas retenue.
- **Témoin.** Apparié par pool A, à date aléatoire, avec le délai ; graine de sa fiche.
- **Barrière (carte).** 1,12 % si A est à 0,25 % avec ≈ 100 SOL ; 1,32 % à 50 SOL. Si A est à 1 % : 2,63 %, donc
  l'hypothèse ne vise que des pools A à 0,25 %.
- **Données.**
  - Il faut des PAIRES de pools du même mint : la liste U-2 doit être construite par mint, ce qui dépend de la
    source U-2 (décision du propriétaire).
  - La collecte double par rapport au pilote : ≤ 2 × 50 000 crédits ; 0 $ dans l'offre Free si le quota le permet.
  - **NON ÉVALUABLE** si moins de 10 paires existent à T0.
  - **[R02 a3f194dc] Pool frère CPMM obligatoire.** Le pool frère B doit lui aussi être un pool Raydium CPMM, le seul
    décodeur audité. Aucun autre lieu (AMM v4, CLMM, autres DEX) n'est lu.
  - **[R02 a3f194dc] Comptage de population AVANT toute fiche de gel.** On compte les mints qui ont au moins 2 pools
    CPMM à WSOL d'au moins 100 SOL de réserve, sans aucun rendement. On s'attend à ce que ces paires soient rares.
    Sans ce comptage, ou s'il donne moins de 10 paires : **NON ÉVALUABLE, aucun essai consommé**.
- **n.** 155 au pilote ; n_c = 279 (Holm, K = 2).
- **Réfutabilité.** G-1 NO-GO si la borne haute est < 0.
  - **[R02 a3f194dc]** Si l'écart est fermé par un arbitrage dans le même bloc, avant nos 4 slots, l'hypothèse est
    réfutée par ce fait même. C'est un résultat NÉGATIF admissible, pas un défaut de mesure.
- **Complémentarité.** C'est un axe NOUVEAU (structure de marché inter-pools), sans lien avec les déclencheurs de
  prix ou de participants des générations 1 et 2.

## G3-2 — « Approfondissement de liquidité »

- **Mécanisme.**
  - Un dépôt de liquidité important, qui fait au moins doubler la réserve en une transaction, vient d'un acteur qui
    engage du capital en anticipant du volume (projet, teneur de marché informé). C'est un signal d'information.
  - Il abaisse aussi notre coût : la carte donne 1,12 % à 100 SOL, 1,02 % à 200 SOL, 0,99 % à 300 SOL.
  - **L'acteur qui perd** n'est pas identifié avec précision : notation 2 au critère de plausibilité.
- **Variables à la décision.**
  - Les événements de liquidité `lp_changes` du pool (dépôts et retraits, avec slot et ordre), dans
    `cpmmx.timeline`.
  - Les réserves avant le dépôt et ses montants (`LpChangeEvent` : `token_0_vault_before`, `token_1_vault_before`, `token_0_amount`, `token_1_amount`, `change_type` = 0 pour un dépôt).
- **Entrée.**
  - Au 1er swap réel qui suit un dépôt LP portant la réserve quote d'au moins R à au moins 2 R dans la même
    transaction : achat ; délai de 3 600 s.
  - Le facteur 2 est déclaré. Il n'a pas de principe externe ancré : notation 1 aux degrés de liberté.
- **Sortie, coûts, témoin.** Communs. Le témoin est apparié par pool, à date aléatoire.
- **Barrière (carte).** ≈ 1,0 % après le doublement d'une réserve de 100 SOL.
- **Données.** Déjà dans la timeline de la collecte de la fenêtre : 0 crédit au-delà de la fenêtre de la génération.
  **NON ÉVALUABLE** si moins de 30 dépôts éligibles sont comptés avant T0 (méthode A1 (b)).
  - **[R02 a3f194dc] Conduite déclarée d'avance.** Moins de 30 dépôts éligibles sur [T0 − 7 j ; T0) : NON ÉVALUABLE,
    **aucun essai consommé**, pas de fiche de gel, et aucun abaissement du seuil de 30.
- **n.** 155 au pilote ; n_c = 279.
- **Réfutabilité.** G-1. Le nombre d'événements peut être faible : `power_stop` le déclare d'avance.
- **Complémentarité.** C'est un axe NOUVEAU (liquidité, côté offre de LP), orthogonal au prix et aux participants
  traders.

## Notation sur la grille gelée a21f90f3 § 1 (à contrôler par R02)

| Critère | G3-1 écart inter-pools | G3-2 approfondissement de liquidité |
|---|---|---|
| Plausibilité | **3** : mécanisme nommé (loi du prix unique) ; l'acteur qui perd est le trader qui a déplacé le pool ; barrière ≤ 1,2 % (1,12 %, carte) | **2** : mécanisme nommé, acteur perdant imprécis ; barrière ≤ 2 % (≈ 1,0 %) |
| Information nouvelle | **3** : axe non testé (inter-pools) | **3** : axe non testé (liquidité côté LP) |
| Degrés de liberté | **2** : 1 seuil, la barrière de la carte (principe externe déclaré) | **1** : facteur 2 sans principe externe |
| Coût | **1** : fenêtre nouvelle et pools frères, > 10 000 crédits | **1** : fenêtre nouvelle, > 10 000 crédits |
| Durée | **1** : inconnue avant comptage, notée au pire | **1** : idem |
| Disponibilité des données | **1** : paires non collectées aujourd'hui (U-2 par mint) | **3** : `lp_changes` déjà dans `cpmmx.timeline` |
| Réfutabilité | **3** : un pilote à n 155 peut rendre NÉGATIF | **3** |
| Confirmation indépendante | **3** : même univers, fenêtre suivante | **3** |
| **Score (8 à 24)** | **17** | **17** |

**Départage (§ 1).**
- (1) Moins de degrés de liberté : **G3-1 (2) devant G3-2 (1)**.
- Classement proposé : **G3-1 > G3-2**.

**Ce qui manque pour passer en génération 3.**
- Une tranche du propriétaire DISTINCTE du texte D : +2 essais (174, 175) et les crédits de la fenêtre. Pour G3-1, il
  faut aussi une source U-2 qui donne les pools CPMM par mint, et le comptage de population des paires.
- Pour G3-2 : le comptage des dépôts éligibles avant T0, au moins 30.
- La fin de la génération 2, ou une fenêtre disjointe des deux premières.
- Le code, sur le modèle de cpmmgen2, audité avant le gel.

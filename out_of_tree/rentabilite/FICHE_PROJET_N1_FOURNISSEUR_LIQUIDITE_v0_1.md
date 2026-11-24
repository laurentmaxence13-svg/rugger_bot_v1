# PROJET de fiche N1 « fournisseur de liquidité » sur la fenêtre G2-3 (v0.1)

RUGGER 01, 24/11/2026. Décision R04-3 : principe N1 retenu, PAPER uniquement, essai 170.
- **PROJET, NON gelé, NON ancré.** R02 statue d'abord sur la recevabilité : même fenêtre, correction multiple,
  univers, puissance.
- Aucune donnée de la fenêtre n'est lue ; aucun crédit n'est dépensé.
- Ce n'est pas un trade du Master : cela ne compte jamais pour 50/20.

**Estimand.** « Une position de fournisseur de liquidité de 0,1 SOL, ouverte et fermée chaque jour, est-elle nette
positive, coûts complets compris, sur CES 4 pools, dans la fenêtre future ? » Aucune généralisation.

**Univers.**
- Les **4 pools nommés de G2-3** (AEZjoU, Gms3Ma, G8kgi7, GdxFyc), CPMM 0,25 %, liste hachée à T0 (fiche G2-3
  v0.4).
- Aucun filtre de rotation n'est appliqué : il n'y a donc aucune mesure à faire sur les pages pré-T0 d'A2r.
  - Si R02 préfère un univers choisi par rotation (dossier N1 § 5), il faudrait d'abord un script de comptage de
    volume et de TVL avant T0, sans rendement. Il serait écrit puis soumis à R02 avant toute exécution.

**Fenêtre.** [24/11/2026 10:21:26Z ; 06/12/2026 10:21:26Z), D = 12 j : la même que G2-3, jamais lue. Les pages
collectées pour G2-3 suffisent : **0 crédit de plus**.

**Unité et positions.**
- 1 position par pool et par jour j = 0 à 11 : ouverture à T0 + j × 86 400 s, fermeture 86 400 s plus tard
  (`lpcost.lp_position`).
- Soit 48 pool-jours au plus.
- Un pool-jour non valorisable (par exemple un événement LP non daté au moment de l'atterrissage) est **publié**. Sa
  valeur de comptage est À FIXER PAR R02, par analogie avec K01 : sortie nulle avec les 6 transactions ?

**Coûts.**
- `lpcost` 0.1 : garde de 20 000 ppm, pires états H-1, 6 transactions à 105 000 lamports, compte fermé.
- Sensibilités : (1, 1, 1) échec ; garde à 50 000 ppm ; loyers perdus.
- Le témoin est la détention des mêmes jetons (`hold_pnl`). Il est descriptif.

**Inférence (reprise de g23five, sans le modifier).**
- Bootstrap par blocs pool-jour stratifié par pool, 10 000 tirages, graine = sha de CETTE fiche[:8].
- Planchers : ≥ 30 pool-jours entrés ; ≥ 3 pools ; Kish ≥ 2,5 ; aucun pool > 50 %. Avec 4 pools et 12 j égaux :
  Kish = 4, part 25 %.
- GO_PILOTE seulement si la borne basse est > 0 sur l'ensemble ET sans le pool le plus fourni. NO-GO si la borne
  haute est < 0. Sinon INCONCLUSIF.
- Les résultats sont publiés par pool, avec la décomposition des frais perçus et de la perte d'inventaire.
- Adaptateur à écrire, environ 1 h : `decision_time` = heure d'ouverture du pool-jour ; aucune autre transformation.

**Puissance.**
- 48 pool-jours au plus ; σ par pool-jour NM, donc la puissance est NM.
- **« Sous la cible » (155) d'office** : le pilote ne peut donner qu'un premier mot G-1, jamais une confirmation.

**Points de recevabilité soumis à R02.**
1. **Même fenêtre que G2-3** :
   - les deux hypothèses portent sur les mêmes pools et les mêmes jours, donc leurs résultats sont corrélés ;
   - ce sont pourtant des mécanismes différents : G2-3 achète un signal d'acheteurs, N1 est payé par le flux.
2. **Correction multiple** :
   - précédent R-CP1 / B1 : un α de 0,05 par hypothèse au pilote, puis Holm à la confirmation ;
   - autre option : Holm entre G2-3 et N1 dès le pilote.
3. **Univers** : les 4 pools de G2-3, choisis pour leurs déclenchements G2-3 et non pour la rotation. C'est un biais
   possible, dans les deux sens.
4. **Valeur d'un pool-jour non valorisable**, à fixer.
5. **Essai 170**, alloué par R04-3.

**Jalon 3 (confirmation).** Mêmes pools, fenêtre neuve, n_c à fixer avec le σ du pilote. Durée et crédits NM.

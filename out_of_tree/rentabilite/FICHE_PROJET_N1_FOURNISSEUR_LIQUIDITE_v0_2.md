# PROJET de fiche de gel N1 « fournisseur de liquidité » sur la fenêtre G2-3 (v0.2)

RUGGER 01, 24/11/2026.
- Décision R04-4 (24/11, 20:55Z) : N1 engagé, essai 170, PAPER uniquement. R02 juge N1 RECEVABLE sur la fenêtre
  G2-3 (note 0b64abd6, registre 62c99f8a).
- **PROJET, NON ancré.** Aucune donnée de la fenêtre lue ; aucune mesure pré-T0 exécutée ; 0 crédit.
- À ancrer par R02 avec son code AVANT toute lecture de la fenêtre, donc avant le 06/12/2026 10:21:26Z.
- Ce n'est pas un trade du Master : cela ne compte jamais pour 50/20. Étiquettes : MASTER_RESEARCH_PAPER,
  HISTORICAL_REPLAY, LP_SIDE_RESEARCH.

Les éléments demandés par R02 (note 0b64abd6, point 4) sont numérotés N-1 à N-11.

**N-1. Estimand.** « Une position de fournisseur de liquidité de 0,1 SOL est déposée au début de chaque jour et
retirée à la fin du jour, coûts complets compris. Son net est-il positif sur CES pools, dans CETTE fenêtre ? »
- **Primaire (le mot)** : la moyenne du net par pool-jour, coûts complets.
- **Comparaison à la détention (descriptive)** :
  - `lp_vs_hold`, la position LP moins la détention des mêmes jetons achetés à l'entrée et vendus par la même règle ;
  - `hold_pnl`, le résultat de cette détention.
  Les deux sont publiés avec leurs bornes au même bootstrap, sans verdict.
  - **À confirmer par R02** : si « vs détention » dans 0b64abd6 désigne le primaire, l'écart `lp_vs_hold` deviendrait
    le mot et le net passerait en descriptif. Je ne choisis pas à sa place.

**N-2. Frais.**
- **Part LP** : 0,25 % × (1 − 12 % − 4 %) = **0,21 % du volume**. Les parts protocole et fonds sont lues dans
  l'AmmConfig U-1, hachée avec son slot (`cpmmcost.fees_from_amm_config`).
- **Frais créateur** : **500 ppm s'il figure dans l'AmmConfig lue**.
  - Il est payé par nos deux échanges (entrée, sortie) et ne revient jamais aux fournisseurs.
  - `lpcost` le prend dans `curve.Fees`.

**N-3. Coûts figés.**
- **105 000 lamports** par transaction (`cpmmcost`).
- **6 transactions** par aller-retour (`lpcost.transactions`) : échange d'entrée, dépôt, retrait, échange de sortie,
  fermeture WSOL, nettoyage. Soit 630 000 lamports, 0,63 % de la mise.
- Garde d'achat de 20 000 ppm ; pires états H-1 à l'entrée et à la sortie ; latence de 4 slots.
- Sensibilités : (1, 1, 1) échec ; garde à 50 000 ppm.

**N-4. Loyer.**
- Compte fermé : les 2 loyers (jeton de base, jeton LP) sont rendus.
- Après 3 nettoyages échoués, les 2 loyers sont perdus. C'est une sensibilité, (0, 0, 3), et elle est publiée.

**N-5. Règle et mesure de rotation (`n1rot` 0.1, fixée AVANT la mesure).**
- **Rotation** :
  - par jour = volume côté SOL / (2 × réserve SOL avant le premier swap du jour) ;
  - par pool = la médiane des 7 jours de [T0 − 7 j ; T0), sur les pages PRÉ-T0 d'A2r ;
  - aucun rendement LP n'est calculé.
- **Règle** : un pool est retenu si sa rotation est ≥ au seuil ; N1 est évaluable avec ≥ 3 pools. Sinon il est NON
  ÉVALUABLE : pas d'ancrage, essai 170 non consommé.
- **Seuil : CHOIX DE R02 avant l'exécution.**
  - Proposé : `cost_break_even` = 419 % par jour (443 % avec le frais créateur), la rotation à laquelle la part LP
    des frais paie les coûts figés à mouvement de prix nul.
  - Variante : `dossier_15` = 15 % par jour.
- Exécution par R03 après l'audit seulement. Le résultat est haché et ancré AVEC cette fiche.

**N-6. Liste des pools.**
- Les pools retenus par N-5, parmi les 4 de G2-3 (liste 812d311b…, fiche G2-3 v0.5), dans cet ordre :
  - `AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca`
  - `Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr`
  - `G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh`
  - `GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A`
- La liste retenue et son sha (`n1rot`, `list_sha256`) sont recopiés ici avant l'ancrage.
- Aucun autre pool n'est possible : ce sont les seules pages de fenêtre collectées.

**N-7. Fenêtre et pages.**
- [24/11/2026 10:21:26Z ; 06/12/2026 10:21:26Z), D = 12 j.
- Ce sont les **mêmes pages que G2-3**, collectées par R03 (cpmmpilot 0.2.8) : **0 crédit de plus**.
- Positions : jour j = 0 à 11, décision à T0 + j × 86 400 s, retrait à T0 + (j + 1) × 86 400 s, atterrissage de
  l'horloge après la latence gelée (`lpcost.lp_position`). Au plus 1 position par pool et par jour, soit au plus
  48 pool-jours.
- **Pool-jour non valorisable** (par exemple un événement LP d'autrui au point d'atterrissage) : il est publié et
  compte comme une sortie nulle avec les 6 transactions.
  - Valeur proposée : −(0,1 SOL + 630 000) = **−100 630 000 lamports** aux échecs gelés.
  - Elle est **À FIXER PAR R02** ; c'est l'analogue LP de K01.

**N-8. Inférence : le bootstrap de `g23five`, avec la graine propre de CETTE fiche.**
- Bootstrap par blocs pool-jour stratifié par pool, 10 000 tirages, graine = int(sha de la fiche N1 ANCRÉE[:8], 16).
  Elle est distincte de celle de G2-3.
- **Planchers** : ≥ 30 pool-jours entrés ; ≥ 3 pools ; Kish ≥ 2,5 ; aucun pool > 50 %. Sinon INCONCLUSIF, avant
  tout NO-GO.
- **GO_PILOTE** seulement si la borne basse à 95 % est > 0 sur l'ensemble ET sans le pool le plus fourni. **NO-GO**
  si la borne haute est < 0. Sinon **INCONCLUSIF**.
- Résultats par pool. Les frais perçus et la perte d'inventaire estimés, `hold_pnl` et `lp_vs_hold` sont descriptifs.
- **Adaptateur** (`n1verdict`, à écrire puis à auditer avant l'ancrage) :
  - `decision_time` = l'heure d'ouverture du pool-jour ;
  - la valeur de N-7 pour les pool-jours non valorisables ;
  - ensuite `g23five` 0.1.1, sans modification.

**N-9. Multiplicité.**
- Proposition, selon le précédent R-CP1 / B1 : α = 0,05 unilatéral par hypothèse au pilote. G2-3 et N1 sont deux
  hypothèses distinctes sur les mêmes pages. Les deux mots sont publiés ensemble, avec la mention « 2 hypothèses sur
  la même fenêtre ».
- Holm entre G2-3 et N1 en confirmation.
- **À aligner sur le texte de 0b64abd6**, que je n'ai pas ; R02 corrige si sa note dit autre chose.

**N-10. Essai.** L'essai 170 (R04-3 / R04-4). Il n'est consommé qu'à l'ancrage ; il ne l'est pas si N-5 donne NON
ÉVALUABLE.

**N-11. Portée restreinte.**
- Le mot ne vaut que pour ces pools, cette fenêtre et ce protocole quotidien (dépôt au début du jour, retrait à la
  fin, 0,1 SOL).
- Aucune généralisation : ni à d'autres pools, ni à d'autres durées de détention, ni au Master.
- Un GO_PILOTE autorise seulement à PROPOSER une confirmation sur les mêmes pools dans une fenêtre neuve.

**Puissance.**
- Au plus 48 pool-jours ; σ par pool-jour NM.
- **« Sous la cible » d'office** : le pilote ne donne qu'un premier mot, jamais une confirmation.

**Code à ancrer avec la fiche.**

| Code | Rôle | Empreinte |
|---|---|---|
| `lpcost` 0.1 | coût | MANIFEST c4ffa128…, audit R02 en attente |
| `n1rot` 0.1 | rotation | MANIFEST 009715844a213ac77cbc9983c9572440d9e83f662fb93f3a34dbed615e42c039, audit R02 en attente |
| `g23five` 0.1.1 | inférence | MANIFEST 06a27862…, audit en attente |
| `n1verdict` | adaptateur | à écrire |
| `cpmmcost` 0.3 | réutilisé sans modification | a0bd2adb… |
| `cpmmx` | réutilisé sans modification | — |
| `cpmmpilot` 0.2.8 | pages, R03 | sha à venir |

Rien ici n'est un résultat économique.

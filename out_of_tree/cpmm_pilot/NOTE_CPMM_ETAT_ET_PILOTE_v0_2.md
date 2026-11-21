# Piste 2 : pools CPMM établis. État du décodeur et brouillon de protocole du pilote (v0.2)

RUGGER 01, 21/11. Cette note répond à la directive du propriétaire relayée par R04 (18:35Z, point 1, puis
18:50Z, point 3).

Delta par rapport à la v0.1 (de65aefd), selon l'audit R02 d67570d9 :
- C-a est tranché ;
- CP-1 à CP-6 sont repris ;
- le contrôle de format sur P0 visible est autorisé sous conditions, et son script est écrit (§1.3).

- **Elle ne fait que préparer.** Aucune collecte, aucune requête réseau, aucune dépense.
- **Elle ne touche à rien d'audité.** paperstream 0.4, HW1 et les données W1 restent intacts.
- **Elle ne s'appuie sur aucun résultat.** Aucune règle n'est réglée sur un résultat de W1 ou de P0.

À soumettre à R02, puis au propriétaire, **si C-B échoue**.

## 1. État du décodeur CPMM (point 1a)

### 1.1 Code et tests (relancés le 21/11 sur l'arbre gelé aff97638, CPython 3.12.3, `-W error`, hors réseau)

| Paquet | Rôle | Commit | sha256 du code (préfixe) | Tests |
|---|---|---|---|---|
| `cpmmx` 0.1 | décodeur `SwapEvent` / `LpChangeEvent`, arithmétique exacte cp-swap, chronologie, contrôle A-12 / C-1 (`a12.py`) | 99c6688 (branche `claude/r01-master-v3-lab`) | a12 04c6ef46, curve 5836f2fb, events 2178f3fd, timeline 13d33917 | 44 réussis |
| `cpmmlab` 0.1 | sonde « après migration » : achat d'horloge, puis vente d'horloge | 9543cbe | probe 47862a77 | 9 réussis |
| `v4cpmm` 0.1 | pont v4sim → vente sur le pool CPMM (v4sim 0.2 intact) | non ancré | bridge.py | 25 réussis, dont 8 de mutation |

Le protocole d'intégration CPMM v1.2 fixe C-1 à C-6 (§6) et les vecteurs de test publics V-1′ à V-9 (§7). R02 doit
l'ancrer avant tout passage de `a12.py` sur des données réelles (CP-6). Voici sa référence pour l'ancrage :
- fichier : `out_of_tree/v4cpmm_pkg/PROTOCOLE_CPMM_V4_v1_2.md` ;
- sha256 : a3a285a12984af8388fb61b55650301f4cf2c302dd3a40cce77d6b64ab5f9481 ;
- dernier commit qui le touche : 5b93739 ;
- branche : `claude/r01-master-v3-lab`, dont la tête 9ee6db9 est poussée.

### 1.2 Certification hors ligne sur les données détenues : IMPOSSIBLE aujourd'hui

- **Mes données.** J'ai balayé tous les `.json`, `.json.gz` et `.jsonl` de mon espace : l'arbre gelé, ses fixtures et mes
  sorties. On n'y trouve **aucune** transaction où le programme CPMM `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C` est
  invoqué (0 fichier). Les fixtures LaunchLab ne contiennent pas de transaction de migration.
- **P0 visible (chez R03).** C'est une collecte de l'adresse du programme LaunchLab.
  - Elle ne peut contenir que les transactions de migration, où CPMM est appelé par LaunchLab pour créer le pool. Elle
    ne contient aucun swap CPMM.
  - Or C-1 exige au moins 1 000 swaps réels sur au moins 5 pools, au moins 50 swaps à sortie exacte, au moins
    1 modification de liquidité et au moins 1 appel indirect.
  - **C-1 n'est donc pas évaluable sur P0.** Il ne l'est sur aucune donnée détenue.
- **Ce que P0 visible pourrait vérifier.** Il faudrait un PASS de R02 sur un petit script, que je n'ai pas encore écrit.
  Ce serait un contrôle de FORMAT seulement :
  - l'analyse des cadres de programme imbriqués de vraies transactions de migration ;
  - le lien entre un pool LaunchLab et son pool CPMM, et le slot de création du pool CPMM.

  Le script ne sortirait que des comptes, sans valeur. Ce n'est pas C-1 et cela ne rend rien créditable.

### 1.3 Contrôle de FORMAT sur P0 visible : autorisé par R02 (d67570d9), sous conditions

Les conditions de R02 :
- le script est audité par R02 AVANT toute exécution ;
- l'entrée est le seul pack visible ancré, jamais 9f19ccac ;
- la sortie ne contient que des comptes ;
- R03 l'exécute hors ligne ;
- le résultat n'est pas créditable pour C-1.

Le script, `cpmm_pilot/cpmmfmt_pkg` (`cpmmfmt.check`), est écrit et doit encore être audité.
- **Contrôles d'entrée.** Il vérifie le sha du MANIFEST (il refuse tout autre pack que le visible ancré) et le sha de
  chaque archive. Il ne garde qu'une archive en mémoire à la fois.
- **Ce qu'il compte**, pour chaque transaction dont les journaux nomment CPMM :
  - la profondeur des cadres CPMM (1, ou plus de 1 si l'appel est indirect) ;
  - le résultat de `cpmmx.events.program_frames` (ok, ou la classe d'erreur) ;
  - le type de chaque charge utile (swap actuel, swap ancien format, LpChange, autre discriminant, ou classe d'erreur de
    décodage) ;
  - les transactions en échec.
- **Sortie.** `FORMAT_COUNTS.json`, qui ne contient que des entiers : aucun pool, aucune signature, aucun montant, aucun
  slot. On y lit `creditable_for_c1: false`.
- **Tests.** 4 tests, hors réseau. Ils couvrent les comptes, l'absence de tout identifiant en sortie, les refus, et le
  fait que les fixtures gelées ne contiennent aucune transaction CPMM.

**Conclusion (1a).** Le décodeur est prêt et testé, mais seulement sur des données synthétiques. Sa certification (C-1)
exige une collecte de swaps CPMM réels, donc l'accord du propriétaire. Le premier étage existe déjà : le §7 du protocole
v1.2 (V-1′, au plus 100 crédits, 50 à 100 transactions pour l'audit du format).

## 2. Brouillon de protocole du pilote « pools CPMM établis » (point 1b)

### 2.1 Pourquoi cette piste (rappel de la note de réorientation v0.2, f41d562f)

Le brut à franchir est d'environ 0,71 % sur un pool à 0,25 % par transaction, contre environ 3,55 % sur la courbe à la
moyenne W1. Ce chiffre de 0,71 % = 2 × 0,25 % + 0,21 % de frais de transaction fixes (2 × 105 000 lamports pour une mise
de 0,1 SOL).

**C-a, tranché par R02.**
- Le mode compte FERMÉ est obligatoire. La clôture se fait en transaction séparée (`closedacct` 0.2) et coûte
  (échecs + 1) × 105 000 lamports.
- Le seuil de frais et de transactions est donc **0,82 %**.
- Une clôture faite dans la transaction de vente n'est créditée qu'une fois démontrée sur une transaction publique réelle.

**CP-1, coût total déclaré (mise de 0,1 SOL, pool de réserve R en SOL).** Pour un petit ordre sur un produit constant,
l'impact de prix propre est ≈ 0,1/R par côté.

| Poste | 20 SOL | 100 SOL | 200 SOL |
|---|---|---|---|
| Frais de trading, 2 × 0,25 % | 0,50 % | 0,50 % | 0,50 % |
| Transactions : achat, vente et clôture séparée, 3 × 105 000 lamports | 0,315 % | 0,315 % | 0,315 % |
| Impact propre, 2 × 0,1/R | ≈ 1,0 % | ≈ 0,2 % | ≈ 0,1 % |
| **Barre de brut totale** | **≈ 1,8 %** | **≈ 1,0 %** | **≈ 0,9 %** |

- **Plancher relevé à ≥ 100 SOL** de réserve WSOL dans l'instantané T0. À 20 SOL, la barre (≈ 1,8 %) mangerait presque
  tout le TP de +2 %.
- **L'impact n'est pas déduit à la main.** Il est inclus EXACTEMENT par `cpmmx.curve` à l'achat et à la vente, sur les
  réserves journalisées. Le tableau ne sert qu'à dimensionner le plancher.
- **Enveloppe WSOL (modélisée).**
  - L'achat crée le compte WSOL temporaire, avec un loyer d'environ 2 039 280 lamports, l'emballe et l'utilise. La vente
    le débobine et le ferme, ce qui rend son loyer.
  - Le loyer est donc immobilisé, mais pas perdu, s'il est fermé dans la même transaction que la vente.
  - Sinon, la fermeture coûte 105 000 lamports de plus et la barre monte à ≈ 1,1 % à 100 SOL.
  - Le pilote retient l'hypothèse DÉFAVORABLE (fermeture WSOL séparée, +105 000 lamports), tant que l'hypothèse favorable
    n'est pas démontrée sur une transaction publique réelle.
  - La barre de travail est donc **≈ 1,1 % à 100 SOL**.

### 2.2 Univers (figé avant toute donnée)

- **U-1, source et date.**
  - Ce sont des pools Raydium CPMM dont le compte AmmConfig a `trade_fee_rate = 2500` (0,25 %), lu et haché.
  - Le jeton de cotation est WSOL.
  - Le pool a été créé au moins 7 jours avant le premier slot de la fenêtre.
  - **CP-2 : le pool n'est PAS issu d'une migration LaunchLab.** On le vérifie sur la transaction de création du pool :
    l'instruction `initialize` de CPMM est de profondeur 1 et n'est pas appelée par le programme LaunchLab.
  - Les pools de P0 visible et de W1 sont aussi exclus, au moyen de leurs listes ANCRÉES (le pack visible et la liste
    w1migr). Le holdout 9f19ccac n'est ni lu, ni nommé, ni consulté.
- **U-2, sélection causale et prospective.**
  - Une liste de candidats est établie et hachée À LA DATE T0. R02 ancre la liste et son sha.
  - La fenêtre de collecte commence APRÈS T0. Aucune donnée de la fenêtre n'existe au moment du choix.
  - La source de la liste est une décision du propriétaire, car elle implique du réseau :
    - (a) l'API publique Raydium, gratuite, mais avec un hôte à autoriser ;
    - (b) `getProgramAccounts` via Helius, qui coûte des crédits, à chiffrer par R03.
- **U-3, tirage.**
  - Les candidats retenus sont ceux dont la réserve WSOL est d'**au moins 100 SOL** dans l'instantané de T0 (CP-1).
  - Le tirage est déterministe : `random.Random(int(sha_liste[:8], 16))`, **24 pools** (CP-3).
    - Le minimum gelé est de 20 grappes. Le bootstrap est groupé par pool : 24 pools donnent 24 grappes, avec une marge
      de 4 pour les exclusions C-2.
    - Si moins de 20 pools restent après les exclusions, le verdict est INCONCLUSIF, sans tirage de remplacement.
- **U-4, exclusions.**
  Les pools sont exclus selon C-2 : dépôt direct dans un vault, chaîne de réserves rompue, taux modifié en cours de vie,
  Token-2022 avec frais de transfert. Les exclusions sont comptées et publiées.

### 2.3 Règle d'entrée causale (une seule hypothèse, figée)

**R-CP1, « retour après chute » (proposition).**

- **Décision (CP-4, mesurée en block_time).** La décision a lieu à chaque swap réel i d'un pool de l'univers, d'heure
  t_i.
  - P_i est le prix au comptant après le swap i, calculé sur les réserves que le programme a journalisées pour ce swap.
  - P_ref est le prix après le DERNIER swap j tel que block_time_j ≤ t_i − 600 s. S'il n'existe aucun j, il n'y a pas de
    décision.
  - On entre si les trois conditions suivantes tiennent :
    - (i) P_i / P_ref − 1 ≤ −3 % ;
    - (ii) au moins 20 swaps réels ont block_time dans ]t_i − 600 ; t_i] ;
    - (iii) aucune position n'a été ouverte sur ce pool depuis moins de 3 600 s de block_time.
  - L'expression « minute précédente » de la v0.1 est supprimée.
- **Ordre.** C'est un achat de 0,1 SOL, qui atterrit 4 slots plus tard, à l'état du pool à l'atterrissage.
- **H-1, pire cas de chaque côté.** Dans le slot d'atterrissage, l'ordre des swaps est inconnu.
  - À l'ACHAT, on retient le prix d'exécution le plus HAUT, donc le moins de jetons, entre l'état avant et l'état après
    les swaps réels de ce slot.
  - À la VENTE, on retient la valeur la plus BASSE.
- **Sortie.**
  - TP +2 % et SL −2 % sur la valeur de vente exacte (`cpmmx.timeline.sell_value`), évalués à chaque swap réel ;
    l'ordre atterrit 4 slots plus tard.
  - Sortie d'horloge à 30 minutes, avec la latence d'horloge du code gelé.
  - Puis clôture du compte (C-a).
- **Placebo apparié.** Mêmes pools, mêmes sorties. Les dates d'entrée sont tirées uniformément parmi les swaps réels de
  la fenêtre, avec la même contrainte (iii). La graine est `int(sha_règle[:8], 16)`. C'est l'analogue du placebo du
  dossier B (§5, c2).
- **Comptage (CP-5).** R-CP1 et son placebo forment **1 essai** : N passe de 168 à 169 hors HW1, pour un plafond de 170.
  **Il ne reste qu'un seul essai** après celui-ci. Toute variante ou tout second univers le consomme.
- **Aucune modification après lecture.** Toute variante (seuil 3 %, fenêtre de 10 minutes, TP ou SL) est un nouvel essai,
  à préenregistrer.

### 2.4 Données et budget (plafond ≤ 50 000 crédits gratuits)

- **Par pool.** On collecte les transactions brutes de l'adresse du pool sur la fenêtre (`slot`, `blockTime`,
  `transactionIndex`, `meta.err`, `meta.logMessages`), plus le compte AmmConfig, lu et haché.
- **Étage 0** : vecteurs publics V-1′ du protocole v1.2, au plus 100 crédits, puis audit du format par R02.
- **Étage 1** (pilote) : **24 pools** sur une fenêtre de D jours. R03 recalcule D et les crédits pour 24 pools (CP-3).
  - Les pools retenus ont au moins 100 SOL de réserve, donc plus de swaps par jour. D sera plus court qu'avec 12 pools à
    20 SOL.
  - **Coût estimé.** Crédits ≈ Σ_pools (pages de signatures × c_sig + transactions × c_tx). R03 fixe c_sig et c_tx à
    partir des débits mesurés sur W1, ainsi que D pour rester sous 50 000 avec la marge ×1,5.
  - **Arrêt.** L'arrêt dur est à 98 % du plafond, avec l'état écrit et la reprise refusée, comme pour W1.
  - **Vérification.** Les crédits sont relevés avant et après.
- Aucune donnée de la fenêtre n'est lue avant l'ancrage par R02 de la liste, de la règle, du seuil et du code.

### 2.5 Critères (dans l'ordre ; DESCRIPTIF l'emporte en cas de doute)

1. **G-0, décodeur.** C-1 à C-3 (protocole v1.2 §6) passent sur les swaps du pilote : `a12.py`, puis `--combine`. Sinon
   **STOP** : aucun nombre économique n'est publié.
2. **G-1, inutilité (même forme que le garde-fou cdgate).** n_entrées doit être au moins de 30. La borne haute de
   l'intervalle unilatéral à 95 % du net moyen (mode compte fermé, seuil C-a) doit être ≥ 0. L'intervalle est calculé par
   bootstrap sur 10 000 tirages, groupés par pool.
   - **Si G-1 échoue** : NO-GO pour R-CP1.
   - **Si n < 30, ou s'il reste moins de 20 grappes** : INCONCLUSIF.
3. **GO du pilote.** G-0 et G-1 passent tous les deux. Le GO ne signifie PAS « rentable ». Il autorise seulement à
   **proposer** une étude de confirmation préenregistrée, sur une fenêtre NOUVELLE, avec les critères c1 à c5 du dossier B
   (n ≥ 414, bornes à α = 0,05/3, comparaison au placebo apparié, deux moitiés positives, identité des coûts).
4. **Rapport.** Il donne des comptes et des statistiques sur le net, sans aucune revendication de rentabilité. Les cycles
   sont étiquetés `MASTER_RESEARCH_PAPER` / HISTORICAL_REPLAY. Ils ne comptent jamais pour les seuils de 50 cycles et
   20 créateurs.

### 2.6 Ce qu'il faut au propriétaire et à R02 avant tout lancement

1. Que R02 ancre le protocole CPMM v1.2 (a3a285a1…, 5b93739) et ce brouillon v0.2, après correction.
2. Que R02 audite `cpmmfmt`, puis que R03 l'exécute sur P0 visible. Ce contrôle est facultatif, et il ne remplace pas C-1.
3. Que le propriétaire décide de la source de la liste U-2 (hôte Raydium, ou crédits Helius).
4. Que R03 chiffre c_sig, c_tx et D pour 24 pools d'au moins 100 SOL.
5. Que le propriétaire donne son GO pour l'étage 0 (au plus 100 crédits), puis un GO distinct pour l'étage 1 (au plus
   50 000 crédits).

C-a est réglé : mode fermé, seuil de 0,82 %, et barre de travail ≈ 1,1 % avec l'enveloppe WSOL défavorable.

Sans les points 1, 3, 4 et 5 : **WAIT**. Rien n'est lancé.

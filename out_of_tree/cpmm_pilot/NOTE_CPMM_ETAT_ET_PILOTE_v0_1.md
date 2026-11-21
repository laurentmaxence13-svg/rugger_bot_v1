# Piste 2 : pools CPMM établis. État du décodeur et brouillon de protocole du pilote (v0.1)

RUGGER 01, 21/11. Cette note répond à la directive du propriétaire relayée par R04 (18:35Z, point 1).

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

Le protocole d'intégration CPMM v1.2 fixe C-1 à C-6 (§6) et les vecteurs de test publics V-1′ à V-9 (§7). Il est rédigé,
mais **R02 ne l'a pas encore ancré**. Or il doit l'être avant tout passage de `a12.py` sur des données réelles.

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
  - **Réserve.** Le protocole v1.2 (§2 et V-1′) écarte les pools liés à P0 pour la mise au point du module. Ce contrôle
    demande donc une décision explicite de R02.

**Conclusion (1a).** Le décodeur est prêt et testé, mais seulement sur des données synthétiques. Sa certification (C-1)
exige une collecte de swaps CPMM réels, donc l'accord du propriétaire. Le premier étage existe déjà : le §7 du protocole
v1.2 (V-1′, au plus 100 crédits, 50 à 100 transactions pour l'audit du format).

## 2. Brouillon de protocole du pilote « pools CPMM établis » (point 1b)

### 2.1 Pourquoi cette piste (rappel de la note de réorientation v0.2, f41d562f)

Le brut à franchir est d'environ 0,71 % sur un pool à 0,25 % par transaction, contre environ 3,55 % sur la courbe à la
moyenne W1. Ce chiffre de 0,71 % = 2 × 0,25 % + 0,21 % de frais de transaction fixes (2 × 105 000 lamports pour une mise
de 0,1 SOL).

**Point à trancher par R02 (C-a).**
- Le seuil de 0,71 % ne compte pas la clôture du compte de jeton. Avec la clôture du modèle `closedacct` 0.2, en
  transaction séparée, on ajoute (échecs + 1) × 105 000 lamports, soit environ +0,105 point : le seuil passe à
  **≈ 0,82 %**.
- Sans clôture, le loyer perdu (≈ 2 039 280 lamports, soit ≈ 2,04 %) rend la piste sans objet.
- Proposition : mode compte FERMÉ obligatoire, et seuil déclaré à 0,82 %. Si la clôture se fait dans la transaction de
  vente, on revient à 0,71 %, mais il faut montrer que c'est possible.

### 2.2 Univers (figé avant toute donnée)

- **U-1, source et date.** Ce sont des pools Raydium CPMM dont le compte AmmConfig a `trade_fee_rate = 2500` (0,25 %),
  lu et haché. Le jeton de cotation est WSOL. Le pool a été créé au moins 7 jours avant le premier slot de la fenêtre.
- **U-2, sélection causale et prospective.**
  - Une liste de candidats est établie et hachée À LA DATE T0. R02 ancre la liste et son sha.
  - La fenêtre de collecte commence APRÈS T0. Aucune donnée de la fenêtre n'existe au moment du choix.
  - La source de la liste est une décision du propriétaire, car elle implique du réseau :
    - (a) l'API publique Raydium, gratuite, mais avec un hôte à autoriser ;
    - (b) `getProgramAccounts` via Helius, qui coûte des crédits, à chiffrer par R03.
- **U-3, tirage.**
  - Les candidats retenus sont ceux dont la réserve WSOL est d'au moins 20 SOL dans l'instantané de T0.
  - Le tirage est déterministe : `random.Random(int(sha_liste[:8], 16))`, 12 pools.
  - La liste ne contient aucun pool lié à P0 (9f19ccac), à W1 ou à W2.
- **U-4, exclusions.**
  Les pools sont exclus selon C-2 : dépôt direct dans un vault, chaîne de réserves rompue, taux modifié en cours de vie,
  Token-2022 avec frais de transfert. Les exclusions sont comptées et publiées.

### 2.3 Règle d'entrée causale (une seule hypothèse, figée)

**R-CP1, « retour après chute » (proposition).**

- **Décision.** À chaque swap réel d'un pool de l'univers, le prix de la minute précédente est calculé sur les réserves
  journalisées AVANT ce swap. On entre si les trois conditions suivantes tiennent :
  - (i) le prix a baissé d'au moins 3 % sur les 10 minutes qui précèdent ;
  - (ii) il y a eu au moins 20 swaps réels sur ces 10 minutes ;
  - (iii) aucune position n'a été ouverte sur ce pool dans les 60 dernières minutes.

  L'ordre est un achat de 0,1 SOL. Il atterrit 4 slots plus tard, à l'état du pool à l'atterrissage. Dans le slot
  d'atterrissage, on retient la plus basse des valeurs avant et après les swaps réels (H-1).
- **Sortie.**
  - TP +2 % et SL −2 % sur la valeur de vente exacte (`cpmmx.timeline.sell_value`), évalués à chaque swap réel ;
    l'ordre atterrit 4 slots plus tard.
  - Sortie d'horloge à 30 minutes, avec la latence d'horloge du code gelé.
  - Puis clôture du compte (C-a).
- **Placebo apparié.** Mêmes pools, mêmes sorties. Les dates d'entrée sont tirées uniformément parmi les swaps réels de
  la fenêtre, avec la même contrainte (iii). La graine est `int(sha_règle[:8], 16)`. C'est l'analogue du placebo du
  dossier B (§5, c2).
- **Comptage.** R-CP1 et son placebo forment **1 essai**, donc N passe de 168 à 169 hors HW1. Le plafond de N du plan est
  fixé par R02 à l'écriture (note v0.2).
- **Aucune modification après lecture.** Toute variante (seuil 3 %, fenêtre de 10 minutes, TP ou SL) est un nouvel essai,
  à préenregistrer.

### 2.4 Données et budget (plafond ≤ 50 000 crédits gratuits)

- **Par pool.** On collecte les transactions brutes de l'adresse du pool sur la fenêtre (`slot`, `blockTime`,
  `transactionIndex`, `meta.err`, `meta.logMessages`), plus le compte AmmConfig, lu et haché.
- **Étage 0** : vecteurs publics V-1′ du protocole v1.2, au plus 100 crédits, puis audit du format par R02.
- **Étage 1** (pilote) : 12 pools sur une fenêtre de D jours.
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
   - **Si n < 30** : INCONCLUSIF.
3. **GO du pilote.** G-0 et G-1 passent tous les deux. Le GO ne signifie PAS « rentable ». Il autorise seulement à
   **proposer** une étude de confirmation préenregistrée, sur une fenêtre NOUVELLE, avec les critères c1 à c5 du dossier B
   (n ≥ 414, bornes à α = 0,05/3, comparaison au placebo apparié, deux moitiés positives, identité des coûts).
4. **Rapport.** Il donne des comptes et des statistiques sur le net, sans aucune revendication de rentabilité. Les cycles
   sont étiquetés `MASTER_RESEARCH_PAPER` / HISTORICAL_REPLAY. Ils ne comptent jamais pour les seuils de 50 cycles et
   20 créateurs.

### 2.6 Ce qu'il faut au propriétaire et à R02 avant tout lancement

1. Que R02 ancre le protocole CPMM v1.2 et ce brouillon, après correction.
2. Que R02 tranche C-a : mode fermé et seuil à 0,82 %, ou démonstration de la clôture dans la transaction de vente.
3. Que le propriétaire décide de la source de la liste U-2 (hôte Raydium, ou crédits Helius).
4. Que R03 chiffre c_sig, c_tx et D.
5. Que le propriétaire donne son GO pour l'étage 0 (au plus 100 crédits), puis un GO distinct pour l'étage 1 (au plus
   50 000 crédits).

Sans ces cinq points : **WAIT**. Rien n'est lancé.

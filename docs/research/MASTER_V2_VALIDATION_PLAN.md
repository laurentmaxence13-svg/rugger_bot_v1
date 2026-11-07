# D — Plan de validation quantitative MASTER V2

Préparé le 2026-11-07 par RUGGER 01. **Révision 2.** Elle intègre deux sources :
- la revue méthodologique indépendante du plan D : 26 amendements, 27 incohérences entre le code et le plan, étapes de la directive §10 non couvertes ;
- le commit `90d8827` : plancher de slot à 200 ms, borne d'âge d'entrée déclarée par chaque politique, embargo couvrant tout l'horizon d'issue.

Statut : **proposition**, à auditer par RUGGER 02.

Ce plan ne crée aucune autorisation. Aucune collecte, aucun achat de données, aucune dépense, aucune transaction réelle, aucun trade PAPER opérationnel et aucune activation LIVE n'a lieu sans l'accord explicite du propriétaire.

**Code de référence.** Toutes les références `fichier:ligne` portent sur le worktree `wt_v2` au commit `341d3f4`. RUGGER 02 a rendu son PASS sur `93fe66e`, puis sur `90d8827` (rapport `fe78424f…`) [FAIT]. Ce dernier PASS fixe deux conditions avant tout rejeu P0 :
- **C1** : RUGGER 03 mesure sur P0, par fenêtres glissantes, la durée minimale des slots. Elle doit rester ≥ 200 ms.
- **C2** : la constante `MIN_CUTOFF_GAP_SLOTS` de l'outil d'export de RUGGER 03 est alignée sur le plancher.

Le commit `341d3f4` (paramètres de rejeu explicites, protocole P0 à 4 slots de latence) attend son audit.

## Conventions

**Étiquettes de preuve**

| Étiquette | Sens |
|---|---|
| **[FAIT]** | Code lu à la ligne citée, ou fait vérifié du projet. |
| **[MESURE INTERNE]** | Mesure d'un agent RUGGER, non reproduite ici, ou obtenue sous hypothèse (par exemple le s090, à taux SOL/USD déclaré). |
| **[CALCUL]** | Nombre dérivé dans ce plan de chiffres cités. La formule est donnée. |
| **[HYPOTHÈSE]** | Non démontré. |

**Statut d'implémentation**, pour chaque critère, mesure ou procédure :
- **« implémenté (fichier:ligne) »** ;
- **« à implémenter (ce qui manque) »**.

Une procédure « à implémenter » ne peut pas servir de garde-fou tant qu'elle n'est pas codée, testée et auditée PASS par RUGGER 02. Le §9 liste ces travaux par priorité.

**Catégories** (directive §12). Aucune politique n'est MASTER CANDIDATE.
- **MASTER CHALLENGER** : les politiques du banc, codées sur des caractéristiques causales natives SOL. Elles sont falsifiables sur P0, puis sur une fenêtre future figée.
- **MASTER RESEARCH** : ce qui exige des données ou du code nouveaux.

Dans le code, tout bundle porte `policy_status='MASTER_RESEARCH'` (`bot/master_v2/harness.py:259`). Le classement en CHALLENGER est une décision documentée, pas un champ du code.

## 1. Principes non négociables

### 1.1 Causalité

Une décision prise à l'événement `k` ne lit que `events[:k+1]`.

Implémenté [FAIT] :
- boucle d'entrée : `bot/market/replay.py:189-190` ;
- aucune décision au milieu d'une transaction : `bot/master_v2/harness.py:115-116` ;
- caractéristiques causales par construction : `bot/master_v2/features.py:28-97`.

Limites [FAIT] :
- La décision à `k` voit l'événement `k` sans retard de flux de données. Seule la latence d'exécution existe (`replay.py:44`).
- L'âge et la détention se lisent sur `block_time`, à la seconde (`features.py:37, 67`, `harness.py:142`).
- La latence est constante.

À implémenter, en sensibilités (livrable B, B-T3 et B-T4) :
- un retard du flux de 0, 1 ou 2 slots, distinct de la latence ;
- le temps calculé comme slot × durée mesurée du régime ;
- une latence tirée dans une distribution pré-enregistrée.

L'arrondi de 1 s de `block_time` est déjà compté dans le dimensionnement des fenêtres et de l'embargo (`harness.py:157, 168, 180`, commit `90d8827`).

### 1.2 Coûts réels, dans la limite du modèle audité

Modélisé, implémenté [FAIT] :
- **Frais du pool, estimés causalement.** C'est le plus grand taux compatible avec la plus longue suite cohérente d'événements jusqu'à la décision (`replay.py:147-172, 197-204`). Le rejeu L1 l'impose (`bot/p4/historical_research_replay.py:165-171`).
- **Frais de base et de priorité.** Par défaut, 5 000 et 100 000 lamports par transaction (`replay.py:46-47, 55-56` ; `historical_research_replay.py:138-139`).
- **Latence fixe en slots** (`replay.py:44, 114-119, 205, 252`).
- **Impact propre sur la courbe.** Les trades réels suivants sont rejoués à montant identique sur la courbe décalée (`replay.py:217-245`).

Non modélisé à ce jour [FAIT] :
- **Tentatives échouées.** Le paramètre est un frais fixe par transaction propre (`historical_research_replay.py:140, 459-461`). Il est nul par défaut. Depuis `341d3f4`, la CLI peut le fixer (`--replay failed_attempt_fee_lamports=…`, `tools/master_v2_research.py:213`). Il n'existe ni taux d'échec, ni ordre manqué, ni nouvel essai.
- **Tolérance de glissement et rejet d'ordre** : aucun `min_out` (`replay.py:208`).
- **Pourboires Jito.**
- **Sandwichs** (B-C8).
- **Frais de transfert Token-2022** (B-C5).
- **Réaction des autres traders à notre ordre.** Leurs montants sont rejoués à l'identique (`replay.py:19-20`).
- **Sorties après migration.** La position devient `migrated_unpriced` (`replay.py:239-245`), et P0 ne contient aucun swap CPMM.

Chaque résultat publie ces limites.

Plancher de coût [MESURE INTERNE] : un aller-retour immédiat de 0,1 SOL coûte 2,2 à 3,7 %. Cela comprend les frais de pool, de 1,0 à 1,75 % par côté en estimation causale, plus environ 0,21 % de frais de transaction.

### 1.3 Comptabilité stricte

Implémenté [FAIT] :
- seul un cycle clos a un P&L (`historical_research_replay.py:464` ; `bot/master_v2/validation.py:34-39`) ;
- les positions ouvertes, hors fenêtre, migrées ou divergentes sont comptées par issue, avec leur valeur de marché quand elle existe (`tools/master_v2_research.py:66-89`) ;
- une moyenne pessimiste compte chaque position non close comme une perte totale (`tools/master_v2_research.py:164-169`).

Limite : un critère calculé sur les seuls cycles clos favorise les pools restés actifs. La décision porte donc sur **toutes les entrées** (§5, critère 1, à implémenter).

### 1.4 Pré-enregistrement

Avant toute lecture d'un segment d'évaluation, deux éléments sont figés par empreinte.

**(a) La politique et son environnement d'exécution.** L'empreinte couvre :
- la politique et ses paramètres ;
- la règle de sortie ;
- les paramètres de rejeu ;
- l'empreinte du code ;
- le MANIFEST ;
- les fenêtres.

Implémenté (`harness.py:227-236`, `validation.py:197-201`).

**(b) Le plan d'évaluation.** À implémenter. Aujourd'hui, aucune empreinte ne le couvre :
- `evaluate` accepte un embargo libre, pourvu qu'il dépasse le minimum exigé ;
- les fractions du découpage sont fixes (0,25 × 4, `validation.py:153`) mais non hachées ;
- la graine 7 et les 10 000 tirages du bootstrap ne sont pas hachés non plus (`tools/master_v2_research.py:123, 171-172`).

Le plan (b) comprend :
- les fractions et l'embargo du découpage ;
- la graine et le nombre de tirages du bootstrap ;
- le niveau α, unilatéral ou bilatéral ;
- les mesures primaires et les seuils de décision ;
- la famille d'hypothèses et la méthode de correction ;
- la grille de stress et la définition des sous-périodes.

Il est inscrit au registre avant la première évaluation, comme une entrée d'un type distinct, qui n'entre pas dans le N d'essais.

**Empreinte de code.** À étendre. `CODE_MODULES` (`harness.py:43-47`) omet deux groupes.

1. Les modules qui établissent le créateur et sa signature :
   - `bot/live/compiled_launchlab.py` ;
   - `bot/live/migration_rpc_json.py` ;
   - `bot/live/solana_signatures.py` ;
   - `bot/live/wire.py` ;
   - `bot/scanner/transaction_parser.py` ;
   - `bot/p3/certification.py` ;
   - `bot/p3/platform_admin_history.py`.

   Ces modules décident des filtres de politique, des grappes de créateurs et de la disjonction. Chaîne d'imports lue : `historical_research_replay.py:56-58`, `compiled_launchlab.py:9-10`, `solana_signatures.py:12-15`.
2. Le code d'évaluation : `tools/master_v2_research.py` et `bot/master_v2/registry.py`.

Cible : la fermeture transitive des modules exécutés. À défaut, l'empreinte de l'arbre git complet.

### 1.5 Tout essai compte

Implémenté [FAIT] :
- chaque configuration est inscrite au registre chaîné **avant** son exécution (`tools/master_v2_research.py:214-217`, `registry.py:46-59`) ;
- `evaluate` refuse un bundle non inscrit, ainsi que l'omission d'un essai inscrit sur le même MANIFEST (`tools/master_v2_research.py:129-134`) ;
- le DSR porte sur tous ces essais (`tools/master_v2_research.py:148-151, 174-176`).

Limites [FAIT] :
- **Comptage par MANIFEST** (`registry.py:62-63`). P0, W1 et W2 ne sont pas reliés (§2.1).
- **Ancrage et horodatage déclaratifs.** L'ancrage de la tête hors de l'outil n'est pas imposé (`registry.py:8-9`). `registered_at` est déclaré par l'appelant (`registry.py:46-49`, option `--at`). Une troncature de la fin du registre est indétectable localement (`MASTER_V2_HARNESS.md:48`).

Règle : la tête de chaîne est envoyée à RUGGER 02 avant **et** après chaque évaluation. Sans cela, l'évaluation n'a pas valeur de preuve.

### 1.6 Fenêtre de collecte, purge et embargo

**Implémenté** [FAIT] :
- **Coupure.** Aucune entrée après la coupure (`harness.py:117-123`).
- **Clôture dans la fenêtre.** Un cycle n'est clos que si sa sortie tombe au plus tard à `window_slot_max` (`historical_research_replay.py:496-503`).
- **Écart de fenêtre.** L'écart entre la coupure et la fin doit couvrir la détention bornée : `ceil((max_hold_s + 1) × 1000 / 200) + 2 × latence` slots. Sinon, la fenêtre est refusée (`harness.py:160-168, 183-193`).
- **Embargo sur l'horizon d'issue** (commit `90d8827`, PASS RUGGER 02).
  - L'horizon d'issue d'un pool va de sa création à `création + A_max + H_max`. A_max est l'âge d'entrée maximal déclaré par la politique (`max_entry_age_s`), H_max sa détention bornée.
  - L'embargo doit couvrir `ceil((A_max + H_max + 2) × 1000 / 200) + 2 × latence` slots. Code : `outcome_horizon_slots` (`harness.py:171-180`) et `required_embargo_slots` (`tools/master_v2_research.py:109-120`).
  - `evaluate` refuse trois cas : un embargo plus court, une détention non bornée, une politique sans borne d'âge (`tools/master_v2_research.py:113-118, 137-140`).
  - Chaque politique déclare sa borne (`bot/master_v2/policies.py:19-20, 37-38, 66-67, 104-105, 148-149, 181-182`), vérifiée par `tests/test_master_v2_slot_horizon.py`.
  - Exemple [CALCUL, vérifié par ce test] : `fill-momentum` aux valeurs par défaut (A_max = 300 s) avec H_max = 45 s exige 1 739 slots, au lieu des 750 par défaut.
- **Plancher de 200 ms par slot** (`historical_research_replay.py:174-178`). Toutes les bornes de ce plan sont recalculées sur ce plancher. L'ancien plancher de 350 ms laissait les détentions déborder des fenêtres.

Durées de slot observées :

| Source | Durée par slot | Statut |
|---|---|---|
| Les 3 fixtures du dépôt | 210 à 222 ms | [MESURE INTERNE] RUGGER 01, `historical_research_replay.py:174-177`. Le test vérifie que le plancher reste sous la mesure et que la mesure reste sous 350 ms. |
| P0, moyenne | 214,5 ms | [MESURE INTERNE] RUGGER 03, 2026-11-07 |
| 4 pools de P0 tirés au hasard | 208 à 214,5 ms | [MESURE INTERNE] RUGGER 03, 2026-11-07 |

**À implémenter.** L'embargo par défaut de `lifecycle` reste de 750 slots (`tools/master_v2_research.py:202`, `bot/master_v2/lifecycle.py:47`). C'est moins que l'horizon de 900 s que ce relevé décrit (`lifecycle.py:14`). C'est sans conséquence sur P0, qui ne sert qu'à l'exploration, mais à corriger avant tout usage sur W1. Cette observation vient de RUGGER 01 dans la présente révision, pas de la revue.

### 1.7 Indépendance

RUGGER 02 audite le code avant toute exécution sur données, puis chaque résultat avant toute promotion. Une politique conçue sur des données ne peut pas être promue sur ces mêmes données (directive §12).

### 1.8 Autorisation

Aucune collecte, aucun achat, aucune dépense et aucune transaction réelle n'a lieu sans l'accord explicite du propriétaire. Les résultats historiques de P0 ne sont jamais modifiés.

## 2. Données et segments

| Jeu | Contenu | Rôle autorisé |
|---|---|---|
| **P0** | Voir le détail ci-dessous. | **Exploration seulement.** P0 a déjà servi au diagnostic (s090) et ne peut plus rien valider. |
| **W1** (futur) | Fenêtre contiguë, collectée **après** le gel des règles. | Entraînement (walk-forward, §6) puis validation, en ordre chronologique, avec purge, embargo et créateurs disjoints. |
| **W2** (futur) | Fenêtre postérieure à W1, jamais lue. | **Holdout final**, descellé une seule fois (§5.3). |

**Détail de P0** [FAIT, faits vérifiés] :
- 724 pools collectés, 293 847 transactions, dont 514 pools rejouables ;
- slots 466 226 737 à 466 442 736, soit 216 000 slots ;
- 363 pools à créateur signé vérifié, 266 créateurs distincts ;
- export MANIFEST `e5d3c0f7…` ;
- coupure `entry_cutoff_slot` 466 442 576, écart de 160 slots avant la fin ;
- contenu : trades de courbe LaunchLab seulement. Aucun swap CPMM, aucune transaction échouée, aucune série SOL/USD causale, aucun historique des créateurs hors fenêtre.

**Durée de P0** [MESURE INTERNE, RUGGER 03, 2026-11-07] :
- 46 274 s, soit environ 12,85 h, de la première transaction (slot 466 226 951) à la dernière (slot 466 442 696) ;
- 214,5 ms par slot en moyenne, recoupé sur un pool AMM SOL/USDC de la même période ;
- l'écart de 160 slots vaut donc environ 34 s.

L'ancienne mention « environ 24 h » reposait sur 400 ms par slot ; elle est retirée.

**Commit du code de collecte** : non vérifiable ici. Il n'apparaît ni dans les faits vérifiés ni dans les dépôts locaux. Il reste à fournir par RUGGER 03.

Chaque nouvelle fenêtre exige l'accord du propriétaire : volume, crédits, fournisseur.

Sur P0, `chronological_split` découpe en quatre segments (`validation.py:153-194`). Le « holdout » de P0 reste pourtant de l'exploration, puisque P0 a déjà été lu.

### 2.1 Mode d'évaluation W1/W2 — à implémenter

Ce mode doit être codé, puis audité par RUGGER 02 avant toute demande de collecte de W2.

- **W1** n'est découpé qu'en entraînement et validation, selon des fractions pré-enregistrées. L'entraînement porte les plis walk-forward du §6.
- **W2** est un MANIFEST distinct, évalué en entier comme holdout, sans redécoupage.
- **N du DSR sur W2** : le nombre cumulé d'essais inscrits pour la famille de la politique, sur P0, W1 et W2.
- **Écart-type des Sharpe des essais** : celui du segment de sélection de W1. Le plan d'évaluation pré-enregistré fixe le sort des essais de P0 qui n'ont pas de Sharpe sur W1.

État du code [FAIT] :
- `chronological_split` impose quatre segments, chacun de fraction strictement positive (`validation.py:162`) ;
- `evaluate` découpe chaque MANIFEST en quatre, avec les fractions par défaut (`tools/master_v2_research.py:146`), et refuse les exécutions faites sur des MANIFEST différents (`tools/master_v2_research.py:125-127`) ;
- `registry.trials_for` ne compte que les essais du même MANIFEST (`registry.py:62-63`).

Sur W2, le DSR ne compterait donc que les exécutions faites sur W2. Avec une seule politique, il ne serait pas calculé : il faut au moins deux Sharpe utilisables (`tools/master_v2_research.py:174-176`).

Tant que ce mode n'existe pas et n'a pas reçu un PASS de RUGGER 02, aucune validation n'est produite sur W1 ni sur W2 : la décision reste **WAIT**.

### 2.2 Référence MASTER actuelle

Faits [FAIT] :
- La politique opérationnelle raisonne en USD. Sans série SOL/USD causale, toutes ses décisions attendent (`sol_usd_rate_unavailable`, `historical_research_replay.py:330-331`).
- Avec un taux déclaré, son bras est identique à `early_sniping`. L'historique des créateurs y entre comme `prior_launches=0` (`historical_research_replay.py:18-19, 36-39`).
- Le rejeu L1 accepte désormais une série SOL/USD causale (`bot/p4/sol_usd_series.py`, `historical_research_replay.py:332-342`). Mais aucune série n'existe pour P0 (faits vérifiés).

[HYPOTHÈSE, à confirmer par RUGGER 02] Une série causale ne lèverait pas à elle seule la duplication, car celle-ci tient à `prior_launches=0`.

Conséquences :
- La comparaison directe de MASTER V2 avec le MASTER actuel reste en **WAIT**. Preuves manquantes : une série SOL/USD causale et l'historique des créateurs à la date.
- Le s090, calculé à taux déclaré, n'est qu'un diagnostic.
- Le bras dupliqué est exclu de toute comparaison économique, conformément à la décision du propriétaire.
- La référence opérationnelle du banc V2 est `immediate-snipe`, accompagnée de l'abstention et des placebos.

### 2.3 Indépendance des créateurs

- **Créateurs liés.** Le créateur retenu est le signataire de la création (`historical_research_replay.py:229-264`) [FAIT]. Des créateurs financés par un même portefeuille ne sont donc pas regroupés (B-A1, B-A4). L'intervalle par créateurs peut ainsi sous-estimer la dépendance. À implémenter : un bootstrap à deux niveaux, créateur et bloc horaire, publié en sensibilité.
- **Disjonction entre fenêtres.** Elle n'est imposée qu'à l'intérieur d'un même MANIFEST (`validation.py:186-189`) [FAIT]. À implémenter : sur W2, les pools d'un créateur déjà vu dans P0 ou W1 forment une strate publiée séparément.
- **Créateur non décodé.** Ces pools partagent la clé `None` (`validation.py:186`) [FAIT]. Ils passent tous en `creator_overlap` après le premier segment où l'un d'eux apparaît. À implémenter : les publier à part.

## 3. Taille d'échantillon

### 3.1 Dispersion de référence

[MESURE INTERNE] Le s090 a été produit par RUGGER 03, code `fe8eb51`, avec un taux SOL/USD de 90,1128 déclaré, non causal. Il donne :
- 33 cycles clos et 32 créateurs ;
- une moyenne de −16,2 % et une médiane de −19,7 % ;
- un intervalle à 95 % de [−21,2 % ; −11,2 %].

[CALCUL] Erreur type : 10 / (2 × 1,96) ≈ 2,55 points. Écart-type : 2,55 × √33 ≈ 14,7 points.

Ce σ appartient à une autre politique, calculée à taux déclaré et dominée par les pertes. Ce n'est pas une propriété de MASTER V2.

[HYPOTHÈSE] Une politique gagnante aurait une queue droite plus épaisse, donc une dispersion plus grande. D'où les colonnes σ = 30 et σ = 60 points.

### 3.2 Nombre de cycles nécessaires

Pour détecter un avantage net moyen δ par cycle, avec une puissance de 80 %, en approximation normale.

**Test unilatéral à α = 5 %** [FAIT, faits vérifiés] :

| δ | σ = 15 points | σ = 30 points | σ = 60 points |
|---|---|---|---|
| +2 % | 348 | 1 392 | 5 565 |
| +5 % | 56 | 223 | 891 |
| +10 % | 14 | 56 | 223 |

Le critère 1 du §5 exige qu'une borne basse d'intervalle **bilatéral** à 95 % soit strictement positive. Le bootstrap est bilatéral à α = 0,05 (`validation.py:72, 95-96`). Cela équivaut à un test unilatéral à α = 2,5 %, qui demande environ 1,27 fois plus de cycles.

**Test unilatéral à α = 2,5 %, applicable au critère 1** [CALCUL : n = ((1,960 + 0,842) × σ / δ)², arrondi au-dessus] :

| δ | σ = 15 points | σ = 30 points | σ = 60 points |
|---|---|---|---|
| +2 % | 442 | 1 766 | 7 064 |
| +5 % | 71 | 283 | 1 131 |
| +10 % | 18 | 71 | 283 |

[HYPOTHÈSE] Le regroupement par créateur multiplie ces tailles par `1 + (m − 1)ρ`, soit de 1,05 à 1,6. Ici, m est le nombre moyen de cycles par créateur et ρ la corrélation intra-créateur.

Ces tailles sont des **minimums optimistes**, pour trois raisons :
- l'approximation normale est fragile pour des rendements à queue droite épaisse ;
- σ = 14,7 points est une mesure interne d'une autre politique ;
- le facteur de grappe est une hypothèse.

**À implémenter avant toute demande de fenêtre :**
- une puissance calculée par simulation, en rééchantillonnant par créateur des distributions plausibles ;
- la MinTRL compte tenu du N d'essais (livrable B, §5.2).

La puissance doit couvrir l'ensemble des critères du §5 : comparaisons appariées avec correction de multiplicité, sous-périodes, stress. Le seul critère 1 ne suffit pas.

**Conséquence.** Les tailles ci-dessus concernent le rejeu de recherche. Elles ne comptent pas pour la porte protégée de 50 cycles économiques qualifiés et 20 créateurs indépendants, qui reste un minimum distinct, propre au Master opérationnel (§5.2). Même atteinte, cette porte ne prouverait pas un petit avantage. Au critère 1, δ = +5 % avec σ = 15 points demande déjà 71 cycles. Une promotion exige la taille calculée pour l'avantage revendiqué.

### 3.3 Taille de W2 fixée à l'avance — à implémenter

- **Cible pré-enregistrée.** Le nombre cible de cycles de W2 et une durée calendaire maximale sont pré-enregistrés. La cible découle de plusieurs éléments : l'avantage revendiqué, le σ supposé, le facteur de grappe, le N d'essais (MinTRL), et les taux d'entrée et de clôture observés sur W1.
- **Aucun arrêt optionnel.** Personne ne regarde W2 avant la fin. Si la durée maximale est atteinte avant la taille cible, la décision est WAIT pour données insuffisantes, et non un test.
- **Points intermédiaires.** Si le propriétaire en souhaite, on pré-enregistre un plan séquentiel de groupe avec dépense d'α. Cette méthode standard ne figure pas au livrable B ; sa référence est à vérifier par RUGGER 02.
- **Lien avec le livrable E.** Ce calcul alimente la demande d'autorisation du livrable E, sans valoir autorisation.
- **Écart de fenêtre.** Toute fenêtre future prévoit, entre la coupure et la fin, au moins `ceil((H_max + 1) × 1000 / 200) + 2 × latence` slots. Pour H_max = 900 s, l'horizon le plus long du relevé de cycle de vie (`lifecycle.py:14`), et une latence de 4 slots, cela fait 4 513 slots [CALCUL], soit environ 16 min à 214,5 ms par slot. Sinon, les sorties longues sont refusées, comme sur P0.

## 4. Mesures

Par politique et par segment, coûts inclus. Les mesures sur cycles clos sont toujours accompagnées des mesures sur toutes les entrées.

| Mesure | Statut |
|---|---|
| P&L net ; P&L et rendement moyens par cycle ; médiane du P&L ; taux de réussite ; profit factor ; drawdown maximal dans l'ordre des sorties ; moyenne des 10 % pires et des 10 % meilleurs cycles | Implémenté : `cycle_metrics` (`validation.py:42-69`), appelé par `evaluate` (`tools/master_v2_research.py:163`). Cycles clos seulement. |
| Issues par segment ; positions non closes : nombre, valeur de marché, non valorisables, migrées ; moyenne pessimiste | Implémenté (`tools/master_v2_research.py:66-89, 164-169`). |
| Intervalle à 95 % par rééchantillonnage de grappes de créateurs | Implémenté (`validation.py:72-97`, `tools/master_v2_research.py:170-172`), sur les cycles clos et à partir de 2 cycles. À implémenter : le même intervalle sur toutes les entrées. |
| PSR contre zéro | Implémenté (`validation.py:121-134`, `tools/master_v2_research.py:173`). Moments empiriques (`validation.py:100-109`). |
| DSR contre l'espérance du maximum des essais | Implémenté par MANIFEST (`validation.py:137-150`, `tools/master_v2_research.py:174-176`). Voir les règles ci-dessous. |
| Quantiles 5, 25, 50, 75 et 95 % du rendement net ; P(perte) ; P(rendement ≤ −90 %) | À implémenter (B-Q3). |
| E[log(1 + f·r)] et sa borne basse à 5 %, avec f = taille d'entrée / capital de référence pré-enregistré | À implémenter (B-Q3). |
| Taille effective n_eff en grappes créateur × bloc temporel ; intervalle par bootstrap stationnaire en blocs temporels, en sensibilité au bootstrap par créateur | À implémenter (B-Q4 ; livrable B, §5.2). |
| PSR et DSR avec moments calibrés par bootstrap | À implémenter. Sur environ 33 cycles, les moments empiriques sous-estiment fortement l'asymétrie et le kurtosis (livrable B, §5.2, ligne PSR). |
| N d'essais, écart-type de leurs Sharpe et segment de calcul | À implémenter. Ces Sharpe viennent aujourd'hui du seul segment d'exploration et ne distinguent ni placebos, ni diagnostics, ni sensibilités (`tools/master_v2_research.py:148-151`). |
| Pools exclus pour données manquantes, par segment et par motif | À implémenter. Le bundle les liste (`harness.py:246-253, 264`), mais `evaluate` ne les voit pas : son découpage ne lit que `bundle['pools']` (`tools/master_v2_research.py:141-146`). |
| Sensibilité aux frais et au glissement ; avantage sur les références (directive §9) | À implémenter : §5, critères 3 et 4. |
| Décomposition du résultat | À implémenter : §7.2, point 5. |

**Règles du DSR**, à implémenter :
- **Seuil de publication.** Le DSR n'est publié qu'avec au moins 5 essais utilisables (livrable B, §5.2). Le code accepte aujourd'hui 2 essais (`validation.py:141-142`, `tools/master_v2_research.py:175-176`).
- **Écart-type.** L'écart-type des Sharpe des essais est un écart-type d'échantillon. Le code utilise aujourd'hui `pstdev` (`validation.py:143`).
- **N.** Il compte toutes les configurations sélectionnables, diagnostics compris.
- **Placebos et sensibilités.** Les familles nulles de placebos sont inscrites mais publiées à part. Les sensibilités sont inscrites hors du N.

## 5. Critères de décision

### 5.0 Porte W1 avant W2

Seules les politiques qui satisfont les critères 1, 3 et 5 sur la validation de W1 sont pré-enregistrées pour W2. Les seuils sont les mêmes, avec un intervalle par créateurs.

Leur nombre est fixé à l'avance et reste petit : chaque politique supplémentaire consomme de la puissance dans la correction de multiplicité. Les politiques écartées sur W1 restent inscrites au registre, avec leur résultat négatif.

Statut : procédure à pré-enregistrer. Elle dépend des critères 1, 3 et 5, eux-mêmes à implémenter.

### 5.1 Critères sur W2 : passage de CHALLENGER à CANDIDATE

Une politique ne passe en CANDIDATE que si, sur le holdout W2 descellé une seule fois, elle remplit les six critères suivants.

**Critère 1 — Espérance nette positive sur toutes les entrées.**

La borne basse de l'intervalle par créateurs de l'espérance nette est strictement positive **sur toutes les entrées**, pas seulement sur les cycles clos.

Statut : à implémenter.
- [FAIT] La durée maximale n'agit qu'au prochain événement réel (`replay.py:246-252`, `harness.py:150`). Une position dans un pool devenu inactif reste ouverte, hors P&L (U3).
- Seule la durée maximale dépend du temps. Les autres déclencheurs ne changent d'état qu'à un événement.

Il faut coder, puis faire auditer avant W1, une **sortie à l'horloge** :
- la décision est prise à l'instant `entrée + max_hold_s`, sur l'état de la courbe à cet instant. Sans événement, la courbe ne change pas : la vente est exactement calculable ;
- le slot de décision est estimé depuis le dernier événement avec le plancher de 200 ms ; la sensibilité à la durée mesurée (environ 214,5 ms sur P0) est publiée ;
- l'ordre atterrit après la latence, une fois appliqués les événements réels des slots atteints ;
- le cycle n'est clos que si ce slot ne dépasse pas `window_slot_max`.

Jusque-là, le critère s'applique à la moyenne pessimiste `mean_return_open_as_total_loss` (`tools/master_v2_research.py:166-169`). Son intervalle par créateurs reste à coder.

La part d'entrées non closes, toutes causes confondues (ouvertes, hors fenêtre, migrées, divergentes), est publiée. Au-delà d'un seuil pré-enregistré, la politique est déclarée non évaluable et la décision est WAIT. Valeur proposée par la revue : 5 % des entrées. C'est une proposition, à confirmer dans le plan d'évaluation.

**Critère 2 — DSR d'au moins 0,95, tous essais comptés.**

Le N est inter-fenêtres, au sens du §2.1, et suit les règles du §4.

Statut : DSR implémenté par MANIFEST (`validation.py:148-150`). Comptage inter-fenêtres à implémenter.

**Critère 3 — La politique bat chaque référence avec un écart significatif.**

Statut : à implémenter. `evaluate` ne fait aucune comparaison appariée (`tools/master_v2_research.py:123-181`).

- **Unité.** Chaque pool éligible du segment : créateur signé vérifié, pool non exclu, créé avant la coupure. Une abstention vaut un P&L net de zéro, comme dans `bot/p4/creator_disjoint_shadow_audit.py:151-152`.
- **Statistique.** La différence appariée par pool, moyennée, avec un intervalle par rééchantillonnage de grappes de créateurs.
- **Références :**
  - l'abstention (zéro) ;
  - `immediate-snipe` ;
  - un placebo de timing : mêmes pools que la politique, âge d'entrée tiré dans la distribution de ses propres âges d'entrée ;
  - un placebo de sélection : même nombre d'entrées, pools tirés au hasard parmi les éligibles, mêmes âges.
- **Familles nulles.** Chaque placebo forme une famille nulle de K tirages pré-enregistrés. Ces tirages sont inscrits au registre, mais exclus du N du DSR, puisqu'aucun placebo ne peut être sélectionné.
  - Le placebo actuel `placebo-random-entry` n'est pas « à moments comparables ». Il tire une seule fois par pool un âge uniforme entre 0 et `max_age_s` (120 s par défaut), avec un seul sel (`policies.py:26-51`).
- **Multiplicité.** La famille est l'ensemble des comparaisons politiques × références. On applique la règle déjà enregistrée dans le dépôt : Bonferroni, α famille de 1/20, soit 1/480 par hypothèse pour une famille de 24 (`bot/policy_research.py:51-58`, `POLICY_RESEARCH_METHOD.md:130-135`).
  - Adaptation : 1/480 reste applicable tant que la famille compte au plus 24 comparaisons. Au-delà de K = 24, le seuil devient (1/20)/K.
  - Remplacer cette règle par Holm, ou par un StepM de Romano-Wolf studentisé, exige une décision du propriétaire. Le StepM serait à implémenter en interne, car `arch` 8.0.0 ne studentise pas (livrable B, §5.2).

**Critère 4 — La politique reste positive sous stress.**

Chaque condition est pré-enregistrée et inscrite au registre comme **sensibilité**, hors du N du DSR. Une sensibilité ne peut ni sélectionner une politique, ni rouvrir un holdout (`POLICY_RESEARCH_METHOD.md:145-150`).

La grille couvre la grille déjà enregistrée dans le dépôt : frais ×1 et ×2, délai de décision 0 et 250 ms (`bot/policy_research.py:58`). Grille V2 et état du code :

| Condition | État du code |
|---|---|
| Frais de pool +25 % et ×2 | Non implémentable sans code : `execution_model()` force l'estimateur causal, sans multiplicateur (`historical_research_replay.py:165-171`). Il faut ajouter un multiplicateur explicite et haché. |
| Frais de priorité ×5, soit 500 000 lamports par transaction | Possible par la CLI depuis `341d3f4` (`--replay priority_fee_lamports=500000`, `tools/master_v2_research.py:213`), et hachée dans le pré-enregistrement. Audit RUGGER 02 de `341d3f4` en attente. |
| Latence portée de 2 à 4 slots | Même état que la ligne précédente. 2 slots de plus valent environ 429 ms à 214,5 ms par slot [CALCUL] : cela couvre le délai de 250 ms enregistré. Sur P0, une latence de 4 slots impose `max_hold_s ≤ 29` (§7.1). Le protocole P0 retient déjà 4 slots comme latence de base (commit `341d3f4`). Avec une détention de 25 s, un stress à 6 slots tient encore : 130 + 12 = 142 slots ≤ 160. |
| Taux d'échec de 0, 10 et 34 % (B-C1) | À implémenter. Un échec réel retarde ou annule une entrée ou une sortie. Il faut modéliser un taux d'échec, avec frais et nouvel essai décalé d'au moins la latence. Le paramètre actuel n'ajoute qu'un frais fixe par transaction propre, nul par défaut (`historical_research_replay.py:140, 459-461`). |

L'ancienne formule « au taux observé dans la fenêtre » est retirée. P0 ne contient aucune transaction échouée. La part de signatures échouées des fixtures, environ un tiers (`historical_research_replay.py:42-43`), concerne les transactions des autres traders, pas les nôtres : elle ne peut pas servir de calibration.

**Critère 5 — Stabilité, sans dépendance à un seul créateur ni à un seul pool.**

Statut : à implémenter. `evaluate` ne calcule ni sous-période ni concentration (`tools/master_v2_research.py:123-181`).
- **Sous-périodes.** Les deux moitiés chronologiques du holdout, découpé par slot d'entrée selon un découpage pré-enregistré, ont chacune une moyenne nette positive.
- **Retraits successifs.** La borne basse de l'intervalle reste strictement positive après retrait du créateur le plus contributif, puis du pool le plus contributif, puis des deux meilleurs cycles (B-Q7).
- **Règle retirée.** L'ancien critère « aucun ne pèse plus de 20 % du P&L » est retiré : il est mal défini quand le P&L total est proche de zéro ou mêle gains et pertes.
- **Régimes.** Quand des étiquettes de régime existent, on publie le tau de Kendall du classement des politiques entre régimes (B-R2).

**Critère 6 — PASS de RUGGER 02** sur le code, les données et le calcul.

Statut : procédure.

### 5.2 Seuils protégés et portée du statut CANDIDATE

Les cycles de rejeu, y compris sur W2, relèvent de la recherche HISTORICAL_REPLAY. Ils ne comptent **jamais** pour les seuils protégés de 50 cycles économiques qualifiés et de 20 créateurs indépendants. Le bundle porte d'ailleurs `counted_in_master_gate=False` et `admissible_in_paper_ledger=False` (`harness.py:265-267`).

Ces seuils restent **inchangés** : ils ne sont jamais abaissés ni contournés, et aucun fill de recherche, de rejeu ou du démonstrateur DexScreener n'est requalifié en trade du Master.

Le statut CANDIDATE n'autorise rien de ce qui suit :
- une modification de la politique opérationnelle ;
- un trade PAPER opérationnel ;
- une activation LIVE.

Chacune de ces étapes exige l'accord explicite du propriétaire.

### 5.3 Descellement unique et holdout consommé

Statut : à implémenter. Le scellement n'est aujourd'hui que procédural [FAIT] :
- `evaluate --holdout --unseal` peut être relancé sans laisser de trace (`tools/master_v2_research.py:135-136, 157-159, 240-241`) ;
- les bundles contiennent les lignes des pools du holdout (`harness.py:258-264` ; `MASTER_V2_HARNESS.md:47`).

Règles :
1. **Entrée de descellement.** Avant tout descellement, on inscrit au registre une entrée « descellement ». Elle porte l'empreinte du plan d'évaluation et la liste des pré-enregistrements concernés. La tête de chaîne est envoyée à RUGGER 02.
2. **Descellement unique.** Un second descellement pour le même MANIFEST est refusé par le code.
3. **Holdout consommé.** En cas d'échec, la politique est rejetée et le résultat négatif est conservé au registre. Toute variante conçue après cette lecture exige une nouvelle fenêtre jamais lue (W3), sous réserve de l'accord du propriétaire.
4. **Ancrage.** Sans tête ancrée hors de l'outil, avant **et** après l'évaluation, celle-ci n'a pas valeur de preuve (§1.5).

## 6. Optimisation

Rien de ce qui suit n'existe encore dans `bot/master_v2` ni dans `tools/master_v2_research.py`. Tout est à coder, puis à faire auditer.

- **Famille déclarée.** Avant le premier essai d'une grille, on inscrit au registre trois éléments :
  - la liste complète des configurations, avec leurs empreintes ;
  - l'identifiant d'hypothèse du livrable B, par exemple B-T1 ;
  - l'objectif primaire.

  Un essai ajouté ensuite forme une nouvelle famille, signalée comme telle, et reste compté dans le N du DSR. Le registre ne stocke aujourd'hui que des essais isolés (`registry.py:46-59`).
- **Walk-forward sur l'entraînement de W1.**
  - Les plis sont chronologiques, ancrés par date de création.
  - Chaque pli applique une purge de l'horizon d'issue (A_max + H_max), un embargo et des créateurs disjoints.
  - Une configuration n'est retenue que si elle est positive sur au moins deux plis hors échantillon (B-T2).
- **PBO par CSCV.**
  - Il se calcule sur la matrice pools × configurations des P&L nets par pool, l'abstention valant zéro.
  - Le découpage utilise S = 6 ou 8 blocs temporels et ne scinde jamais un créateur (livrable B, §5.2 et B-Q2).
  - Si le PBO dépasse 0,5, la sélection est rejetée.
  - Variante possible : CPCV avec N = 6 et k = 2. La purge et le regroupement par créateur sont alors à coder à part, car `skfolio` purge en nombre d'observations (livrable B, §5.2).
- **Plateau.** On retient la configuration qui maximise le minimum, sur ses voisins immédiats de grille, de la borne basse de l'intervalle par créateurs. On ne retient pas un maximum isolé.
- **Paramètres hors de portée du banc actuel** (directive §9) [FAIT] :
  - la taille de position est fixée à 0,1 SOL (`historical_research_replay.py:70`). `run_policy` ne la transmet pas (`harness.py:250-251`) et elle est absente du pré-enregistrement (`harness.py:227-236`) ;
  - le glissement maximal n'est pas modélisé, faute de `min_out` (`replay.py:208`) ;
  - l'exposition simultanée et les limites de drawdown ne peuvent pas être étudiées, car chaque pool est rejoué isolément.

  Ces paramètres exigent une couche portefeuille, de catégorie MASTER RESEARCH. À titre de repère, le registre PAPER existant plafonne à 3 positions ouvertes (`bot/p4/live_like_paper_ledger.py:123, 186`).

Une configuration choisie sur un segment ne peut plus servir de preuve sur ce même segment.

## 7. Expériences sur P0 (exploration)

### 7.1 Contraintes P0

**Durée maximale de détention** [CALCUL, vérifié par `tests/test_master_v2_slot_horizon.py`] :
- avec une latence de 2 slots : `max_hold_s ≤ 30`, car ceil(31 000 / 200) + 4 = 159 ≤ 160 ;
- avec une latence de 4 slots : `max_hold_s ≤ 29`, car ceil(30 000 / 200) + 8 = 158 ≤ 160, alors que 30 s donnerait 163.

Le code refuse toute fenêtre trop courte (`harness.py:191-192`). Le test vérifie le refus pour 31, 45 et 54 s. Les anciennes limites de 54 et 53 s reposaient sur le plancher erroné de 350 ms ; elles sont retirées.

**Latence de base sur P0** (commit `341d3f4`, audit en attente). À 214,5 ms par slot, les 2 slots par défaut ne font plus que 0,43 s, au lieu des 0,8 s visés (observation O1 de RUGGER 02).
- La valeur par défaut reste inchangée, car elle entre dans les empreintes des résultats L1 enregistrés.
- Le protocole P0 fixe donc la latence explicitement (`run --replay latency_slots=4`), soit environ 0,86 s. Cette valeur est hachée dans chaque pré-enregistrement.
- La détention de 25 s, avec `exit_horizon_ms=25000`, tient dans l'écart de 160 slots :
  - même si C1 forçait le plancher à 175 ms : ceil(26 000 / 175) + 8 = 157 ≤ 160 ;
  - même pour un stress de latence à 6 slots : 130 + 12 = 142 ≤ 160.

**Plan d'exploration P0** [FAIT, faits vérifiés] :
- 15 essais pré-enregistrés, ré-émis avec une latence de 4 slots, `max_hold_s = 25` et `exit_horizon_ms = 25000` ;
- deux règles de sortie : E_SHORT (durée maximale 25 s) et E_SL (stop-loss 0,10, prise de profit 0,20, durée maximale 25 s) ;
- précondition : C1, la durée minimale des slots mesurée sur P0 par RUGGER 03 ;
- **rien n'a encore été exécuté ni inscrit**. RUGGER 03 n'exécute le code d'une autre session que sur décision explicite du propriétaire ;
- les versions précédentes, à 45 s puis à 30 s avec 2 slots de latence, sont retirées et ne sont inscrites nulle part. La version à 45 s est d'ailleurs refusée par le code.

Ces 15 essais formeront le N du DSR de P0. Tout essai ajouté après lecture des résultats est inscrit et compté. Aujourd'hui, les placebos et les diagnostics entrent dans ce N sans distinction (`tools/master_v2_research.py:148-151, 174-176`). Sur P0, cela ne fait que rendre le DSR plus prudent.

**Embargo.** `evaluate` applique automatiquement le maximum entre 750 slots et l'horizon exigé (`tools/master_v2_research.py:137-140`). Si le plan inclut `fill-momentum` à ses valeurs par défaut (A_max = 300 s), l'embargo exigé est de ceil((300 + 25 + 2) × 1000 / 200) + 8 = 1 643 slots [CALCUL], soit environ 5,9 min à 214,5 ms par slot.

**Cycle de vie.** Par défaut, `lifecycle` ne décrit que le segment d'exploration (`lifecycle.py:47-72`, `tools/master_v2_research.py:200-201`).
- Décrire les 514 pools exige `--segment all`. Ce choix retire au « holdout » de P0 même sa valeur de répétition générale.
- Ce choix est décidé et noté avant l'exécution.
- `MASTER_V2_HARNESS.md:61` dit encore « sur les 514 pools » sans mentionner `--segment all`. Ce document est à corriger à part ; la présente révision ne le modifie pas.

**Portée.** Les résultats de P0 servent à formuler des règles, jamais à les valider.

### 7.2 Ordre des expériences

**1. Cycle de vie, sans aucune politique.** Implémenté (`lifecycle.py:21-72`).

**2. Courbe du moment d'entrée.** `diagnostic-fixed-delay` avec des délais de 0, 5, 15, 30, 60 et 120 s, avec les deux règles de sortie fixées à l'avance, E_SHORT et E_SL, toutes deux à 25 s de détention. Implémenté (`policies.py:166-191`).

Cette courbe compare des populations différentes [FAIT] :
- une décision n'est prise qu'à un événement réel (`replay.py:189-193`) ;
- une entrée au délai d n'existe donc que si un trade survient entre d et d + 30 s (`max_lateness_s`, `policies.py:174, 187-188`).

À implémenter, pour chaque délai, en plus du rendement par cycle :
- le nombre de pools encore actifs ;
- le P&L par pool éligible, l'abstention valant zéro ;
- les markouts par délai (B-T5) ;
- les références de sortie « vendre immédiatement » et « tenir jusqu'à l'horizon » (B-S2).

**3. Placebos.** `placebo-no-trade` et `placebo-random-entry`. Implémentés (`policies.py:15-23, 26-51`). Les placebos appariés du §5, critère 3, restent à implémenter.

**4. Familles.** `immediate-snipe`, `delayed-confirmation` et `fill-momentum`, à leurs valeurs par défaut non réglées. Implémentées (`policies.py:54-79, 82-127, 130-163`).

À implémenter, en catégorie MASTER RESEARCH :
- étendre `ExitRule` à des sorties sur caractéristique causale : première vente du créateur, ou flux net négatif sur une fenêtre (B-S1) ;
- journaliser chaque décision de détention, et pas seulement le déclencheur final (`harness.py:152-153`).

Aujourd'hui, la politique n'est plus consultée après l'entrée (`harness.py:138-154`).

**5. Décomposition du résultat.** À implémenter. `evaluate` ne la calcule pas, mais chaque ligne de cycle contient les données nécessaires :
- **coûts certains** : frais de pool au taux `fee_rate_ppm` à l'achat et à la vente, plus `tx_costs` (`historical_research_replay.py:466-471`) ;
- **mouvement de prix pendant la détention** : valeur de liquidation au déclenchement (`exit_trigger.mark`, `harness.py:153`), recalculée hors frais, moins la mise ;
- **glissement des stops** : `received` moins `exit_trigger.mark`, dû à la latence après le déclenchement.

[MESURE INTERNE] Sur le s090, l'essentiel des −16,2 % viendrait du chemin de prix et de l'exécution retardée des stops. Cette décomposition permettra de le confirmer ou de le réfuter sur les exécutions V2. Elle reste une mesure descriptive d'exploration.

Ces résultats ne servent qu'à **formuler** des règles. Les règles retenues sont ensuite figées, puis jugées sur W1, puis sur W2.

## 8. Registre des hypothèses et des résultats (directive §12)

Statut : à implémenter. Le registre actuel ne contient que des pré-enregistrements (`registry.py:46-59`).

- **Identifiant et étape.** Chaque pré-enregistrement porte un identifiant d'hypothèse (par exemple B-T1 ou B-S1) et son étape dans la boucle : RECHERCHE → HYPOTHÈSE → PROTOTYPE → TEST → AUDIT → COMPARAISON → DÉCISION → AMÉLIORATION.
- **Types d'entrées.** Le registre distingue plusieurs types d'entrées :
  - essai ;
  - famille déclarée ;
  - plan d'évaluation ;
  - sensibilité ;
  - tirage de placebo ;
  - descellement ;
  - résultat.

  Seuls les essais sélectionnables entrent dans le N du DSR.
- **Résultats.** Après chaque évaluation, une entrée « résultat » est chaînée au registre. Elle lie l'empreinte du bundle à celle de la sortie d'`evaluate`. Les résultats négatifs sont conservés comme les positifs.
- **Exécution récurrente.** Aucune n'est annoncée tant qu'aucune tâche planifiée n'est réellement en place.

## 9. Travaux de code avant toute validation sur W1 ou W2

Les incohérences relevées par la revue se répartissent en deux groupes.

**Déjà résolues**, retirées de la liste :
- **par le commit `90d8827`, PASS RUGGER 02** : l'embargo couvre l'âge d'entrée et la détention (C15) ; le plancher passe à 200 ms ;
- **par le texte de ce plan** :
  - C16 : `lifecycle` et `--segment all`, §7.1 ;
  - C20 : la taille d'échantillon au critère 1, §3.2 ;
  - C25 : le commit de collecte non vérifiable, §2 ;
  - C26, pour sa partie texte : la règle P0 et le plan à 15 essais, §7.1. La décomposition reste à coder (n° 16) ;
  - C27 : l'alignement des stress et de la multiplicité sur le design enregistré, §5.1.

**Restent à faire**, par priorité. Chaque travail est codé avec des tests hors réseau, puis audité PASS par RUGGER 02 avant usage.

### Priorité 1 — bloquant

| # | Travail | Requis avant | Références |
|---|---|---|---|
| 1 | Fait : PASS RUGGER 02 sur `90d8827` (rapport `fe78424f…`). Restent C1 (mesure P0 par RUGGER 03), C2 (constante de l'outil d'export de RUGGER 03) et l'audit de `341d3f4` | Toute exécution, P0 compris | `historical_research_replay.py:174-178` ; `harness.py:157-193` ; `tools/master_v2_research.py:109-140` |
| 2 | Empreinte de code sur la fermeture transitive des modules exécutés, y compris le décodage du créateur et le code d'évaluation | W1 (souhaitable dès P0) | C1 ; `harness.py:43-53` |
| 3 | Plan d'évaluation pré-enregistré et haché (§1.4 b), avec les types d'entrées du registre (§8) | W1 | C2, C19 ; `tools/master_v2_research.py:123, 137-140, 171-172` |
| 4 | Mode W1/W2 : découpage configurable, W2 évalué en entier, N du DSR inter-fenêtres | W1 (découpage), W2 (N) | C3, C4 ; `validation.py:162` ; `registry.py:62-63` |
| 5 | Sortie à l'horloge ; intervalle sur toutes les entrées ; seuil de non-clôture | W1 | C18 ; `replay.py:246-252` ; `harness.py:150` |
| 6 | Pools exclus publiés par segment et par motif | W1 | C17 ; `tools/master_v2_research.py:141-146` |
| 7 | Comparaisons appariées par pool éligible ; placebos de timing et de sélection en familles nulles ; correction de multiplicité | W1 | C11, C12 ; `policies.py:26-51` ; `bot/policy_research.py:51-58` |
| 8 | Sous-périodes et robustesse par retraits successifs | W1 | C13 |
| 9 | Puissance par simulation et MinTRL | Toute demande de fenêtre | §3.2, §3.3 |
| 10 | Descellement inscrit, second descellement refusé, ancrage de la tête avant et après | W2 | C5, C6, C7 ; `tools/master_v2_research.py:135-136, 157-159` ; `registry.py:8-9, 46-49` |
| 11 | Stress : multiplicateur des frais de pool (les paramètres de rejeu sont exposés en CLI et hachés depuis `341d3f4`) ; modèle d'échec avec nouvel essai ; sensibilités hors du N | W2 | C8, C9, C10, C19 ; `tools/master_v2_research.py:213` ; `historical_research_replay.py:140, 165-171, 459-461` |

### Priorité 2 — nécessaire à la qualité de la preuve

| # | Travail | Requis avant | Références |
|---|---|---|---|
| 12 | Mesures du §4 : quantiles, P(perte), P(≤ −90 %), E[log], n_eff, bootstrap en blocs temporels, PSR et DSR à moments calibrés, DSR avec au moins 5 essais et écart-type d'échantillon | W1 | C21, C22 ; `validation.py:100-109, 137-145` |
| 13 | Optimisation : famille déclarée, walk-forward, PBO/CSCV, plateau | Entraînement sur W1 | C14 |
| 14 | Registre des hypothèses et des résultats | W1 | §8 ; `registry.py:46-59` |
| 15 | Créateurs : clé `None` publiée à part ; strate des créateurs déjà vus ; bootstrap créateur × bloc horaire | W1 (`None`), W2 (strate) | C24 ; `validation.py:186-189` |
| 16 | Décomposition du résultat | Lecture des résultats P0 | C26 ; `harness.py:153` |
| 17 | Couche portefeuille : taille, exposition simultanée, drawdown, en catégorie MASTER RESEARCH | Toute étude de ces paramètres | C23 ; `harness.py:196-197, 250-251` |

### Priorité 3 — utile

| # | Travail | Références |
|---|---|---|
| 18 | Sorties sur caractéristique causale et journal des décisions de détention | `harness.py:138-154` ; B-S1 |
| 19 | Retard du flux de données, temps slot × durée du régime, latence aléatoire | `replay.py:44` ; `features.py:37` ; B-T3, B-T4 |
| 20 | Embargo de `lifecycle` couvrant ses horizons (observation de RUGGER 01) | `tools/master_v2_research.py:202` ; `lifecycle.py:14, 47` |
| 21 | Correction de `MASTER_V2_HARNESS.md:61` (`--segment all`) | Document, hors de ce plan |

## 10. Couverture de la directive §10 (simulation réaliste des cycles)

État au commit `90d8827`. Bilan : 7 étapes couvertes, dont l'étape 15 pour les seuls cycles clos ; 8 partielles ; 1 non couverte.

| # | Étape | Statut | Preuve | Manque |
|---|---|---|---|---|
| 1 | Création du token | Couvert | `creation_facts` lit la plus ancienne transaction stockée, avec vérification des signatures Ed25519, de l'instruction externe et du signataire (`historical_research_replay.py:229-264`). | — |
| 2 | Premières transactions | Partiel | L'historique complet depuis le lancement est exigé (`replay.py:183-186` ; `historical_research_replay.py:514-544`). La mesure `early_slot_payers` existe (`features.py:63-65`). | P0 ne contient aucune transaction échouée. Snipes échoués et congestion sont invisibles, car les caractéristiques ne lisent que les événements de courbe réussis (`features.py:28-97`). |
| 3 | Informations disponibles au MASTER | Partiel | Événements de ce pool et faits de création seulement (`features.py:28-97` ; `harness.py:124, 201`). | Aucun historique des créateurs (`prior_launches=0`, `historical_research_replay.py:18-19`), aucun graphe de financement, aucun autre pool, aucune série SOL/USD dans V2 (`sol_usd_used=False`, `harness.py:267`). Aucun retard de flux distinct de la latence (`replay.py:44, 189-190`). Le MASTER actuel ne se rejoue pas (§2.2). |
| 4 | Calcul des signaux | Couvert | `native_features`, causal par construction (`features.py:28-97`). | — |
| 5 | Décision BUY, WAIT ou NO_TRADE | Couvert | `PolicyArm.entry` (`harness.py:111-136`) : décision journalisée, jamais au milieu d'une transaction, NO_TRADE définitif après la coupure. | — |
| 6 | Latence d'exécution | Partiel | Latence constante en slots (`replay.py:44, 114-119, 205, 252`). L'arrondi de 1 s est compté dans les fenêtres et l'embargo (`harness.py:157-180`). | Ni distribution, ni atterrissage manqué, ni nouvel essai. Temps lu sur `block_time` (`features.py:37` ; `harness.py:142`). Latence réglable par la CLI depuis `341d3f4` (`--replay latency_slots=…`, `tools/master_v2_research.py:213`). Le protocole P0 la fixe à 4 slots, avec `max_hold_s = 25`. |
| 7 | Prix d'achat simulé réalisable | Partiel | Remplissage exact sur l'état de la courbe après les événements réels jusqu'au slot s + latence. Refus explicite si la courbe l'interdit (`replay.py:205-213`). | Ni `min_out`, ni tolérance de glissement : un ordre réel rejeté serait rempli (`replay.py:208`). Sandwichs et MEV non modélisés (B-C8). |
| 8 | Quantité de tokens obtenue | Couvert | `fill.amount_out` (`replay.py:213-214`). | — |
| 9 | Frais et slippage | Partiel | Frais de pool causal (`replay.py:147-172, 197-204` ; `historical_research_replay.py:165-171`). Frais de base et de priorité par transaction (`replay.py:55-56, 215, 230, 262`). Impact propre exact sur la courbe. | Tentatives échouées : frais fixe nul par défaut, réglable par `--replay` depuis `341d3f4` (`historical_research_replay.py:140, 459-461`). Pas de Jito, de plafond de glissement ni de frais Token-2022 (B-C5). Pas de décomposition (§7.2, point 5). |
| 10 | Évolution du marché | Couvert | Trades réels suivants rejoués sur la courbe décalée, avec divergence explicite (`replay.py:217-245`). | — |
| 11 | Décisions successives | Partiel | WAIT et NO_TRADE journalisés jusqu'à l'entrée (`harness.py:111-136`). | Après l'entrée, la politique n'est plus consultée : seuls les seuils fixes d'`ExitRule` s'appliquent (`harness.py:138-154`). Seul le déclencheur final est noté (`harness.py:152-153`). Une seule entrée, sortie totale (`replay.py:175-176`). |
| 12 | Déclenchement de la sortie | Partiel | Déclencheurs évalués à chaque événement réel, dans l'ordre opérationnel (`harness.py:147-151` ; `replay.py:246-252`). | La durée maximale n'agit qu'au prochain événement : une position dans un pool silencieux reste ouverte, hors P&L (`tools/master_v2_research.py:66-89`). Aucune sortie sur caractéristique causale (B-S1). |
| 13 | Prix de vente simulé réalisable | Partiel | Vente exacte `sell_exact_in` sur la courbe décalée, après la latence, avec contrôle de l'inventaire et des réserves réelles (`replay.py:221-232` ; `bot/market/launchlab_curve.py:113-127`). Une vente impossible devient `counterfactual_divergence`, jamais inventée. | Une position qui atteint la migration devient `migrated_unpriced`, sans sortie CPMM (`replay.py:239-245` ; `historical_research_replay.py:489-493`). P0 ne contient aucun swap CPMM. |
| 14 | SOL récupérés | Couvert | `result.received` (`replay.py:229`). | — |
| 15 | P&L net | Couvert pour les cycles clos | `received − spent − tx_costs − échecs` (`historical_research_replay.py:459-468`). Par segment dans `evaluate` (`tools/master_v2_research.py:92-100, 160-163`). | Les entrées non closes n'ont qu'une valeur de marché et une moyenne pessimiste (`tools/master_v2_research.py:164-169`). Pas de décomposition brut/net. |
| 16 | Comparaison avec la référence | Non couvert | Un bundle ne porte qu'une politique (`harness.py:258-267`). | `evaluate` ne calcule ni différence appariée ni test contre une référence (`tools/master_v2_research.py:123-181`). Le MASTER actuel ne peut pas servir de référence (§2.2). Le placebo aléatoire n'est pas apparié (`policies.py:26-51`). |

Règles finales du §10 :

| Règle | Statut | Preuve et manque |
|---|---|---|
| Aucune information future dans une décision passée | Couvert | `replay.py:5-6, 189-190` ; `features.py:28-97`. Seul `lifecycle` lit le futur des pools, à titre descriptif et sur l'exploration par défaut (`lifecycle.py:47-72`). |
| Aucune vente inventée si elle n'est pas exécutable | Couvert | `counterfactual_divergence` (`replay.py:222-227, 255-260`) ; `migrated_unpriced` (`replay.py:239-245` ; `historical_research_replay.py:489-493`). |
| Positions ouvertes, migrations et données manquantes comptabilisées explicitement | Partiel | Positions ouvertes et migrées comptées par segment (`tools/master_v2_research.py:70-89, 164-169`). Les pools exclus sont listés dans le bundle (`harness.py:246-253, 264`), mais `evaluate` les ignore (`tools/master_v2_research.py:141-146, 179-181`). |

## Annexe — Traçabilité de la revue

Aucun amendement n'est rejeté en entier. Ont été rejetées les seules parties contredites par le commit `90d8827` ou par les faits vérifiés :
- le plancher de 350 ms (A4, A6, A8, A10, A16) ;
- les valeurs de 54 s, 53 s et 45 s (A6, A10) ;
- l'affirmation « le code ne couvre que H_max » (A8) ;
- les exemples de 990 et 2 580 slots (A8, A16), recalculés à 1 739 et 4 513 slots.

| Amendement | Priorité | Traitement | Où |
|---|---|---|---|
| A1 Mode W1/W2, N inter-fenêtres | must | Intégré | §2.1, §5.1 critère 2, §9 n° 4 |
| A2 Pré-enregistrement du plan d'évaluation, empreinte de code | must | Intégré, lignes mises à jour | §1.4, §9 n° 2 et 3 |
| A3 Puissance à α = 2,5 %, hypothèses étiquetées | must | Intégré, tableau recalculé à l'identique | §3.1, §3.2 |
| A4 Toutes les entrées, sortie à l'horloge | must | Adapté : plancher de 200 ms ; seuil de 5 % gardé comme proposition | §1.3, §5.1 critère 1, §9 n° 5 |
| A5 Comparaison appariée, placebos, multiplicité | must | Adapté : Bonferroni étendu à (1/20)/K au-delà de 24 comparaisons | §5.1 critère 3, §9 n° 7 |
| A6 Stress | must | Adapté : P0 à latence 4 → 29 s ; design enregistré couvert (frais ×2, latence ≥ 250 ms) ; « taux observé » remplacé par 0/10/34 % | §5.1 critère 4, §9 n° 11 |
| A7 Descellement unique | must | Intégré | §5.3, §9 n° 10 |
| A8 Embargo sur l'horizon d'issue | must | Constaté **implémenté** à `90d8827` (formule à 200 ms + 2 s) ; reste l'embargo de `lifecycle` | §1.6, §9 n° 1 et 20 |
| A9 Seuils protégés, CANDIDATE n'autorise rien | must | Intégré | §5.2, §3.2 |
| A10 Contraintes P0 | must | Adapté : ≤ 30 s, ou ≤ 29 s à 4 slots ; plan ré-émis à 4 slots de latence et 25 s de détention, rien d'inscrit | §7.1 |
| A11 Mesures complémentaires | should | Intégré, avec statuts | §4 |
| A12 Optimisation | should | Intégré | §6, §9 n° 13 et 17 |
| A13 Stabilité, retrait de la règle des 20 % | should | Intégré | §5.1 critère 5, §9 n° 8 |
| A14 Coûts modélisés et non modélisés | should | Intégré | §1.2 |
| A15 Référence MASTER actuelle | should | Intégré, complété : la série SOL/USD est désormais acceptée par L1, mais aucune n'existe pour P0 | §2.2 |
| A16 Taille de W2 fixée à l'avance | should | Adapté : 4 513 slots pour 900 s à latence 4 | §3.3 |
| A17 Indépendance des créateurs | should | Intégré | §2.3, §9 n° 15 |
| A18 Courbe d'entrée conditionnée par l'activité | should | Intégré | §7.2, point 2 |
| A19 Décomposition | should | Intégré, lignes mises à jour | §7.2, point 5, §9 n° 16 |
| A20 Registre des hypothèses et des résultats | should | Intégré, avec types d'entrées | §8, §9 n° 14 |
| A21 Porte W1 avant W2 | should | Intégré | §5.0 |
| A22 Commit de collecte non vérifiable | could | Intégré : mention marquée non vérifiable | §2 |
| A23 Retard de flux, temps en slots, latence aléatoire | could | Intégré brièvement ; arrondi de 1 s déjà compté à `90d8827` | §1.1, §9 n° 19 |
| A24 Sorties sur caractéristique causale | could | Intégré brièvement | §7.2, point 4, §9 n° 18 |
| A25 Règles du DSR | could | Intégré | §4 |
| A26 Étiquettes de preuve | could | Intégré, avec une quatrième étiquette [CALCUL] | Conventions |

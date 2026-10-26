# P1.6g — Observation des créations LaunchLab non datées

## Référence et périmètre

Contrôles initiaux conformes : branche `main`, HEAD et `main` exactement
`f6dc7dd4e17f0cc61fe5e0f2bd7d95fbad662fc1`, statut Git complet vide.
Lecture d'AGENTS.md et du plan technique. Branche locale créée uniquement :
`fix/p16g-undated-launch-observation`.

Fichiers modifiés/ajoutés :

- `bot/analyser/paper_engine.py` : sélection temporelle, observation distincte,
  audit et indicateurs ; intégration au quota/FIFO existants.
- `bot/scanner/launch_detector.py` : validation minimale de la date avant son
  utilisation, sans changer la détection des instructions ou leurs métadonnées.
- `tests/test_undated_launch_observation.py` : **65 cas**, paramétrages inclus.
- Ce document.

Aucun changement de schéma. `paper_trader.py`, `tx_recovery.py`, `db.py`,
`transaction_parser.py`, `research_pipeline.py`, `main.py`, `backfill.py` et leurs
paramètres sont inchangés par rapport à la référence (vérification des contenus,
avec normalisation des fins de ligne Windows). Aucun commit, push ou fusion.

## Diagnostic et reproduction avant correction

Les lignes de référence suivantes désignent le code original :

| Source | Cause démontrée | Conséquence reproduite |
|---|---|---|
| `launch_detector.py:18-35` | `blockTime=None` accepté ; les autres valeurs non nulles sont envoyées directement à `datetime.fromtimestamp` | NULL produit bien une création avec date/latence nulles ; 0, négatif, booléen et flottant sont acceptés ; chaîne et entier hors plage peuvent lever une exception |
| `tx_recovery.py:130-170` | Le cache, toutes les créations et le receipt `done` sont écrits atomiquement, y compris avec `block_time=NULL` | La création non datée existe durablement ; un rejeu terminé ne relance pas sa récupération |
| `paper_engine.py:194-207` | `block_time BETWEEN ? AND ?` exclut NULL | Le candidat persisté est absent de `recent_candidates` puis de la FIFO normale |
| `paper_engine.py:695`, `:717-718`, `:807` | Statut/audit/âge supposent un `signal_time` convertible en entier | Injecter la réception comme signal fabriquerait une date et un âge de lancement |
| `paper_engine.py:280-314` | Historique créateur filtré seulement par présence/ordre SQL de la date | Les valeurs historiques invalides ou converties par l'affinité SQLite demandent une validation distincte |

Le premier test de bout en bout démontre successivement, sur les modules
originaux : création stockée avec NULL, sélection classique vide, collecte sans
audit explicite. Il échoue sur l'audit attendu. Six autres cas échouent sur la
validation des dates : 0, −1, True, 1000,5, chaîne `"1000"`, entier hors plage.
Résultat original : **7 failed**. Le dernier cas provoque `OSError`, la chaîne
`TypeError` ; les quatre autres exposent une date acceptée à tort.

La modification du parseur est indispensable : un changement dans le moteur seul
ne peut observer une création que le parseur rejette avant son stockage. Le patch
reste limité à la date et à la latence. Les discriminators, instructions internes/
externes, métadonnées par création, règles de conflits et atomicité P1.6b ne sont
pas modifiés.

## Contrat temporel et politique retenue

| Temps | Source conservée | Usage autorisé |
|---|---|---|
| A : lancement | `launch_candidates.block_time`, issu du `blockTime` fourni pour la transaction | Éligibilité et âge de lancement uniquement si exploitable |
| B : réception | `launch_candidates.detected_at`, écrit depuis le `received_at` de la récupération | Âge de **file d'observation**, jamais âge de lancement |
| C : cotation | `paper_prices.timestamp`, heure locale de capture après la récupération du prix | Série d'observations ; pas une date blockchain ni une heure d'exécution réelle |

Le parseur (`launch_detector.py:22-34`) exige un entier Python strict, positif,
représentable et non postérieur à la réception datée avec fuseau. Booléens,
flottants même intégraux, chaînes, dates nulles/négatives/futures ou hors plage
deviennent **NULL dans le résultat parsé**, avec latence NULL. La transaction
brute n'est pas modifiée : le cache garde la valeur du fournisseur, ou l'absence
de clé. Une date valide conserve exactement son résultat et sa latence antérieurs.

Le moteur (`paper_engine.py:195-300`) vérifie aussi les dates déjà persistées :
entier positif, non futur au contrôle et non postérieur à une réception exploitable.
Lorsqu'un cache existe pour la signature exacte, son `blockTime` doit être du bon
type, égal à la date stockée, et sa création doit correspondre au mint, creator et
pool disponibles. Le suffixe canonique `:mint` sert uniquement à retrouver la
signature brute selon le contrat P1.6b ; aucune recherche par simple proximité de
mint, date ou creator.

Cette vérification évite notamment qu'un ancien True, flottant intégral ou nombre
textuel converti en INTEGER par SQLite soit considéré valide malgré son payload
contraire. Les anciennes lignes invalides ne sont **pas réparées** : leur valeur
originale reste stockée ; elles sont traitées comme non datées. Les NULL restent
NULL. Sans payload disponible, le moteur conserve la confiance historique dans
un entier persistant exploitable ; son type d'origine, s'il a été perdu par SQLite,
ne peut être reconstitué. Il ne s'agit pas d'une vérification blockchain externe.

## Observation distincte et FIFO

`_undated_candidates` prépare une observation par mint, avec toutes ses identités
transactionnelles conservées dans l'audit. Une observation de prix exige :

1. Création déjà identifiée structurellement par le scanner.
2. Métadonnées creator/pool cohérentes entre les identités regroupées pour ce mint.
3. Une réception ISO avec fuseau, positive et non future.
4. Âge de file inférieur ou égal au `max_age` existant, calculé depuis la plus
   ancienne réception valide de ces identités.

La réception choisie et la signature du candidat qui la fournit sont explicites
dans l'audit. Un rejeu ou une seconde signature plus tardive pour le même mint ne
prolonge pas la fenêtre. Une réception absente, malformée, naïve ou future n'est
jamais remplacée par l'heure de traitement. Des métadonnées contradictoires sont
affichées par identité, sans choisir un creator/pool de synthèse et sans cotation.

Les éléments non datés rejoignent la **même file candidate** persistante que les
éléments datés ; aucune nouvelle lane ni modification du schéma de planification.
Le budget total reste `max_candidates`, diagnostics compris. L'algorithme P1.6a
garde sa priorité aux positions, sa réserve d'une place candidate et l'alternance
pour un budget d'une place. Les nouveaux mints rejoignent la fin de file.

Réception inexploitable, conflit ou fenêtre expirée : un diagnostic utilise une
place, puis une empreinte durable dans l'audit empêche de le retraiter indéfiniment
tant que les données ne changent pas. Une réception valide permet des observations
répétées jusqu'à expiration. La fenêtre est recontrôlée après l'attente de prix.
Le démarrage d'un nouveau processus ne remet pas ces limites à zéro.

Les tests parcourent 24 candidats initiaux, datés et non datés, avec une arrivée
entre les cycles et un budget de 10 : tous sont visités sur quatre cycles, sans
dépassement de quota. Le nouvel arrivant attend derrière les 24 éléments déjà en
file ; promettre sa visite dès le troisième cycle total serait incorrect. Le test
avec budget 1 et redémarrage démontre la progression des positions et des mints
non datés avec l'alternance persistante.

## Refus PAPER et cohérence des observations

`_observe_undated` (`paper_engine.py:885`) ne fait appel ni à `build_features`, ni
à `decide`, ni à l'historique créateur. Les cotations utilisent le chemin on-chain
existant puis son repli de marché habituel. Elles passent par les validations,
transactions et protections P1.4/P1.5 existantes.

L'appel d'observation à `record_quote` a **signal_time=None, model=None et
allow_entry=False**. Le trader existant enregistre le prix puis revient sans
réserver de fonds, créer un portefeuille ou ouvrir un trade. Aucun changement de
ce trader. Une position apparue entre-temps est laissée à sa lane de gestion avec
son signal et son modèle ; elle n'est pas gérée avec les valeurs absentes de cette
voie d'observation.

L'audit non daté contient notamment :

```json
{
  "signal_time": null,
  "age_seconds": null,
  "prior_launches": null,
  "features": null,
  "score": null,
  "decision_finale": "OBSERVATION_NON_DATEE",
  "launch_observation": {
    "status": "NON_DATE_PRIX_OBSERVE",
    "launch_time_verified": false,
    "entry_allowed": false,
    "reception_source": "launch_candidates.detected_at"
  }
}
```

Les timestamps B/C et l'âge de file sont fournis séparément. Les autres statuts
comprennent `NON_DATE_PRIX_ABSENT`, `NON_DATE_PRIX_EN_ATTENTE`,
`NON_DATE_RECEPTION_INVALID`, `NON_DATE_RECEPTION_EXPIRED` et
`NON_DATE_METADATA_CONFLICT`.

`paper_signal_status.signal_time` est NOT NULL. La voie non datée utilise donc le
statut dans `paper_mint_audit.report_json`, sans insérer une fausse valeur dans
`paper_signal_status` ou une décision stratégique dans `paper_decisions`.
L'audit est un dernier instantané par mint, pas un journal exhaustif de tentatives.

Un mint ayant à la fois une identité datée et une identité non datée garde leurs
métadonnées distinctes. Le chemin daté choisit le pool correspondant à son propre
creator/date, au lieu de prendre le dernier pool du mint. Son audit ajoute
`undated_identities`, en modes shadow_final et validated. La date connue ne remplit
aucune ligne NULL et n'est pas prêtée à l'autre transaction.

Le chemin daté recontrôle également sa source/identité sous le verrou SQLite après
les attentes asynchrones (`paper_engine.py:1033`). Si elle n'est plus vérifiable,
la cotation de ce passage est abandonnée avec un audit de refus, avant features,
décision ou ouverture. Une position déjà ouverte continue à être gérée avec son
signal historique. Les gardes scanner P1.6f et financier P1.6d restent actifs pour
les nouvelles entrées datées. Les TP/SL des positions ouvertes restent inchangés.

Prix, audit et éventuelle mise à jour de conflit de cette observation partagent la
transaction SQLite. Une erreur d'audit annule le nouveau prix ; aucune permission
positive n'est fabriquée. La progression de FIFO, écrite avant l'I/O comme en
P1.6a, n'est pas annulée. Une répétition identique ne rajoute pas de prix ; une
cotation contradictoire garde le premier prix et incrémente le conflit existant.

## Réconciliation et consommateurs persistants

Possibilité examinée sans réseau : un payload en cache ou une ligne
`research_launches` peut porter une date. **Aucune réconciliation automatique n'est
ajoutée**. Une date trouvée plus tard ne prouve pas à elle seule comment réécrire
atomiquement les identités historiques et préserver les comparaisons strictes de
receipt P1.6b. Une ligne de recherche scalaire ne remplace pas les identités des
créations multiples. Le candidat reste non daté, même si le cache est actualisé.

Les tests vérifient l'absence de copie depuis une autre transaction et l'absence de
modification du receipt terminé. Les mints non datés sont exclus de l'historique
créateur exploitable ; demander cet historique sans signal retourne l'inconnu,
pas un faux zéro de lancements précédents.

Aucune écriture de date dans `research_launches`, aucun remplacement de
`blockTime` dans `research_tx_cache`, aucun nouvel événement historique CSV ne sont
produits par l'observation. Pour deux créations NULL sans autre date persistante,
l'export du dataset reste vide. Le CSV des prix peut contenir leurs observations,
avec un timestamp de capture : ce n'est pas un dataset de lancements ni une
permission d'entrée.

L'export P1.6e reste inchangé et conserve ses propres règles de lecture du payload
brut et de repli sur une date historique persistante. Cette mission ne certifie
donc pas toutes les dates d'un ancien corpus CSV ; notamment son filtre préexistant
ne compare pas les entiers futurs du payload à une heure de réception. Aucun
backtest sur ces dates incertaines n'est exécuté ou validé ici.

## Indicateurs

`paper_report` ajoute uniquement `launch_time_diagnostics` :

- nombres de lignes candidates datées et non datées ;
- nombres de mints concernés, dont les mints exclusivement non datés ;
- mints non datés ayant des prix, sans en déduire une entrée ;
- lignes non datées exclues des nouvelles entrées et mints exclusivement exclus ;
- répartition des statuts d'audit et nombre de mints encore sans audit.

Les cohortes de mints datés et non datés peuvent se recouper lorsqu'un mint porte
plusieurs identités ; les compteurs par ligne permettent de le voir. Un prix
existant prouve une observation du mint, pas nécessairement une observation de
chaque identité. Les compteurs historiques et le ratio `quote_coverage` ne sont pas
modifiés : l'anomalie distincte du ratio supérieur à 100 % reste hors périmètre.
Aucun taux de couverture de marché n'est déduit.

## Validation isolée et résultats exacts

Sources/fixtures suivies uniquement, sans `.env`, secrets, base utilisateur ou
données de marché. Copies :

- Correctif : `C:\Users\maxen\AppData\Local\Temp\rugger_p16g_5z873sew`.
- Deuxième baseline : `C:\Users\maxen\AppData\Local\Temp\rugger_p16g_baseline_8z4xo229`.

Python 3.13.15 et pytest 9.1.1 du venv existant. Aucune installation. Le lanceur
neutralise `dotenv`, interdit les connexions et résolutions vers des services et
désactive les plugins automatiques ; seuls les socketpair locaux nécessaires au
réveil interne d'asyncio sont admis. Aucun scanner réel ou moteur en boucle réelle.

Commande principale depuis chaque copie, avec l'interpréteur du venv par chemin
absolu :

```text
python -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
```

| Validation | Résultat réellement obtenu |
|---|---|
| Première baseline, avant patch | **349 passed, 1 skipped, 242 subtests passed** (23,21 s) |
| Reproduction initiale sur modules originaux | **7 failed** (0,40 s), défauts attendus |
| Baseline rejouée avec dispositif réseau adapté aux threads | **349 passed, 1 skipped, 242 subtests passed** (26,18 s) |
| Suite finale avec 65 nouveaux cas intégrés | **414 passed, 1 skipped, 242 subtests passed** (27,41 s) |

Le skip reste `tests/test_research_pipeline.py:17` : base utilisateur absente. Elle
n'a pas été ouverte pour supprimer ce skip. Les 65 nouveaux cas sont effectivement
présents au dépôt ; les sous-tests existants ne sont pas comptés une seconde fois.

Passages intermédiaires : 30 passed/3 subtests sur le premier groupe ciblé ;
45 passed/1 failed sur les premières nouvelles fixtures ; 393 passed/2 failed/
1 skipped/242 subtests sur un premier passage complet. Le test FIFO supposait à
tort une visite du nouvel arrivant avant la fin de tous les éléments déjà en file.
L'autre échec était une barrière de concurrence, accompagnée d'avertissements de
création de boucle asyncio : l'exception socketpair du dispositif de test utilisait
un booléen global partagé entre threads. Elle a été rendue locale au thread dans
la copie, en conservant le blocage réseau. Le groupe concerné a ensuite donné
63 passed/13 subtests. Un autre passage ciblé a donné 56 passed/2 failed : la fixture
lisait le troisième champ de retour, `cache_changed`, au lieu du deuxième,
`cooldown`. Ces corrections de fixtures/dispositif n'ont pas changé la production.
Les passages complets verts suivants ont donné 407, puis 413, puis les 414 tests
finaux après ajout des derniers cas et du recontrôle de source sous verrou.

### Couverture des 30 exigences

| Exigences | Preuves dans les nouveaux tests | Résultat |
|---|---|---|
| 1-5 : NULL, multi-créations, métadonnées, absence de date fabriquée, diagnostic | `null_payload_recovery_storage_observation_audit_without_entry`, `multiple_null_creations_preserve_each_identity_and_pool`, `null_outer_and_inner_creations_are_both_observed` | Chaîne complète payload → récupération → stockage → observation → audit ; pas d'entrée |
| 6-9 : cotation sûre, refus, PnL, signal_time | `unusable_dates_end_to_end_without_latency_trade_or_fake_signal`, `invalid_new_observation_price_cannot_create_financial_data`, `undated_observation_does_not_call_financial_or_strategic_guards` | Prix validés ; signal/âge/features inconnus ; aucun trade ni fonds créés |
| 10 : historique créateur | `unknown_launches_do_not_inflate_creator_history`, `old_stored_affinity_is_detected_using_original_payload` | Non datés exclus ; bool/float/texte d'origine contrôlés lorsqu'ils sont en cache |
| 11-12 : dates normales et invalides | Six reproductions parseur, douze variantes end-to-end, comparaison originale/corrigée des payloads normaux | Données valides identiques ; mauvaises dates à NULL pour les nouvelles récupérations |
| 13-14 : réception et temps distincts | `invalid_reception_is_diagnostic_only_not_silently_replaced`, `missing_reception_column_is_visible_without_a_fake_time`, `repeated_mint_cannot_extend_window_with_a_later_reception` | Réception explicite, pas de remplacement ni prolongation par rejeu |
| 15-17 : rejeu, reprise, doublons | `replay_and_sqlite_restart_preserve_null_and_do_not_duplicate`, `identical_mint_duplicates_are_one_observation`, `metadata_conflict_is_visible_without_mixing_or_quoting` | Déduplication persistante et conflits explicites |
| 18 : swaps et SPL seuls | `non_creations_do_not_become_undated_candidates` | Aucun faux candidat |
| 19-21 : charge/FIFO/positions/TP/SL | `fifo_bounded_cycles_include_dated_undated_and_new_arrivals`, `one_slot_persisted_rotation_cannot_starve_open_positions`, `open_position_priority_tp_sl_and_no_undated_trade` | Quota respecté, progression des deux voies et clôtures normales |
| 22-23 : P1.6f/P1.6d | Deux tests d'intégration dédiés + suites existantes | Les entrées datées restent bloquées par scanner dégradé et historique de perte incomplet |
| 24-25 : export P1.6e et atomicité P1.6b | `undated_candidates_never_create_exported_block_time`, `null_multi_recovery_atomic_rollback_on_second_creation` + suites existantes | Dataset NULL vide ; rollback cache/candidats/receipt puis reprise réussie |
| 26-27 : non-régression et fonds | Huit comparaisons détaillées ci-dessous, absence de portefeuille créé pour l'observation seule | Capital, allocation, frais, TP/SL et PnL préservés |
| 28 : cohésion | `report_separates_dated_and_undated_from_permission`, `mixed_dated_and_undated_same_mint_never_borrow_metadata_or_date`, `quotes_keep_original_conflict_and_replay_policy` | Audit/status distincts, identités non fusionnées, premier prix conservé |
| 29 : erreurs et attente | Tests verrou SQLite, échec d'audit, absence/cooldown de prix, expiration après await, changement de source de date pendant await | Pas de signal stratégique ou financier positif inventé ; rollback prix/audit |
| 30 : aucun service externe | Toutes les exécutions sous dispositif réseau bloqué, RPC/prix entièrement synthétiques | Aucun appel externe, téléchargement ou boucle réelle |

### Comparaison financière et des sorties datées

Après le dernier changement de production : chargement séparé du moteur original
et corrigé, bases synthétiques distinctes. Les résultats complets des parseurs sont
identiques pour des payloads normaux d'une, deux et trois créations.

Huit scénarios : entrée simple, TP, SL, TP puis rejeu, trois créations, refus
financier, refus scanner, mode validated avec le modèle baseline existant.
Comparaison exacte des huit tables `launch_candidates`, `paper_prices`,
`paper_trades`, `paper_portfolio`, `paper_decisions`, `paper_signal_status`,
`paper_mint_audit`, `paper_collection_schedule` : **identiques dans les huit cas**.
Les champs préexistants du rapport sont identiques ; seul le nouveau bloc de
diagnostic est volontairement ajouté. CSV dataset et prix identiques octet par
octet. Script et résultat : `dated_comparison_runner.py` et
`dated_comparison.json` dans la copie du correctif.

| Scénario financier | Avant | Après |
|---|---|---|
| Entrée simple | Position 1 SOL, capital initial/réalisé 10 SOL | Identique |
| Prix 1 → 1,2, TP | PnL +0,18 SOL, capital 10,18 SOL | Identique |
| Prix 1 → 0,8, SL | PnL −0,22 SOL, capital 9,78 SOL | Identique |
| TP puis rejeu | Une seule position/clôture, capital 10,18 SOL | Identique |
| Trois créations datées | Trois positions, capital réalisé 10 SOL | Identique |
| Limite max_open=0 | Aucune entrée | Identique |
| Scanner refusant | Aucune entrée, capital 10 SOL | Identique |
| Modèle baseline existant en mode validated | Position 1 SOL, capital 10 SOL | Identique |

Les fichiers de code et tests du dépôt sont identiques aux fichiers de la copie
ayant obtenu le résultat final. Syntaxe AST contrôlée sans écrire de pyc et
`git diff --check` sans erreur.

## Limites restantes

- Les temps reçus du fournisseur et les horloges locales ne sont pas une vérité
  terrain vérifiée par réseau. Une date de réception invalide peut empêcher toute
  cotation ; le diagnostic reste disponible.
- Sans payload historique, l'affinité SQLite peut avoir effacé le type d'origine
  d'une date. Aucune réparation rétrospective ou garantie externe n'est inventée.
- La FIFO limite les traitements et appels de prix par cycle, pas le coût de
  lecture/qualification de tous les candidats persistants. Ces lectures et certains
  contrôles de payload croissent avec la taille de l'historique. Aucun test de débit
  réel ou de volumétrie massive n'est revendiqué.
- Une charge supérieure à la capacité peut faire expirer un candidat avant sa
  cotation. La fenêtre n'est jamais prolongée pour améliorer artificiellement les
  résultats. La progression FIFO ne garantit pas une visite avant expiration.
- Le diagnostic est par mint et conserve ses identités, tandis que les prix et
  finances restent par mint selon le contrat existant. Ce n'est pas un ledger de
  décisions indépendant pour chaque occurrence transactionnelle.
- Un verrou SQLite peut différer prix, audit et clôtures ; le patch garantit le
  refus sûr, pas une disponibilité impossible malgré une base verrouillée.
- Une date obtenue ultérieurement demande une réconciliation conçue séparément ;
  aucun receipt terminé ni candidat historique n'est migré ici. Les règles propres
  de l'export historique ne sont pas élargies ou certifiées par cette branche.
- Aucune couverture exhaustive, rentabilité ou exécution réaliste n'est démontrée.
  **Aucun GO global P2.**

## Rollback précis

Procédure documentaire, non exécutée. Depuis la racine, vérifier d'abord qu'aucun
travail ultérieur n'est à conserver, puis :

```powershell
git restore --source=f6dc7dd4e17f0cc61fe5e0f2bd7d95fbad662fc1 --worktree -- bot/analyser/paper_engine.py bot/scanner/launch_detector.py
Remove-Item -LiteralPath '.\tests\test_undated_launch_observation.py', '.\P1_6G_UNDATED_LAUNCH_OBSERVATION.md'
git status --porcelain=v1 --untracked-files=all
git switch main
```

Suppressions de fichiers explicites, sans récursion. Aucune base réelle n'a été
ouverte ou migrée ; aucun rollback de données utilisateur n'est nécessaire pour
cette mission. La branche locale peut être conservée. Aucun portefeuille réel,
ordre, signature, RPC, WebSocket, API, installation ou service payant utilisé.

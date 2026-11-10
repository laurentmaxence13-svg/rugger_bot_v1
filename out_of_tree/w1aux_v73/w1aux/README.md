# w1aux — outils auxiliaires W1 (S0 et audit de couverture getBlock)

**Hors de l'arbre gelé.** Ce répertoire ne s'ajoute pas à `aff97638`. Il n'en modifie aucun fichier et ne contient aucune logique d'évaluation. Il importe en lecture seule `bot.market.backfill`, `bot.market.w1_collection` et `bot.market.collector` du checkout gelé.

Pour l'exécuter :
- le répertoire courant doit être le checkout gelé ;
- le parent de `w1aux/` doit figurer dans `PYTHONPATH`.

Rien n'est envoyé sur le réseau sans `--network`. Aucune exécution réseau n'a lieu sans l'audit de RUGGER 02, l'ancrage des sha256 et le GO du propriétaire.

## Tests (hors ligne)

    cd <checkout aff97638>
    PYTHONPATH=<parent de w1aux> python -B -m pytest -q -p no:cacheprovider -W error <parent de w1aux>/w1aux/tests

## Étapes

1. **S0**, dès que les conditions d'utilisation sont archivées et que le GO est donné :

       RUGGER_NO_DOTENV=1 PYTHONPATH=... python -B -m w1aux.coverage s0 --lo 467270000 --network --log s0.jsonl

   - Sortie : `s0`, `s0_block_time`, `previous_produced_slot` et `previous_block_time` (preuve de minimalité).
   - Environ 45 requêtes, plafond 120.
   - RUGGER 02 ancre ensuite S0.

2. **Slots tirés**, hors ligne : `python -B -m w1aux.coverage slots --s0 S0` donne les 200 slots tirés. RUGGER 02 les ancre.

3. **fetch** : juste après `window_slot_max`, AVANT la collecte LaunchLab.

       RUGGER_NO_DOTENV=1 ... python -B -m w1aux.coverage fetch --s0 S0 --out coverage_summary.json \
           --details accounts --max-tx-version <0|1, décision ancrée> --network --log fetch.jsonl

   - L'outil refuse de s'exécuter si le slot finalisé courant est ≤ `window_slot_max`.
   - Un slot tiré qui a été sauté est remplacé par le slot produit suivant, ni tiré ni déjà retenu ; le remplacement est noté dans le résumé et dans le journal.
   - Une seule lecture getBlock par slot. Les blocs ne sont pas archivés : pour chaque slot, on garde `blockhash`, `parentSlot`, `blockTime`, le nombre de transactions, le sha256 de la réponse canonique et les signatures LaunchLab avec leur `err`.
   - STOP (code 5) si un bloc produit n'est pas disponible (-32004, -32007, -32009 ou null), ou si la version de transaction est refusée (-32015).
   - Environ 401 requêtes, plafond 600.
   - RUGGER 02 ancre ensuite le sha256 du fichier de résumé.

4. **compare** : APRÈS la collecte, hors ligne.

       python -B -m w1aux.coverage compare --summary coverage_summary.json --summary-sha256 <ancré> --run <run LaunchLab>

   - Le run doit être vérifié et complet.
   - Résultat PASS si aucune transaction ne manque et si la collecte ne contient aucune signature absente du bloc. Sinon FAIL (code 4).

## Journal

Chaque tentative est écrite en JSONL : méthode, paramètres, numéro de tentative, résultat et heure. Les remplacements de slots sautés y figurent aussi. L'URL n'y apparaît jamais ; elle est lue dans `RUGGER_COVERAGE_RPC_URL`.

## Registre BUY/SELL (`w1aux.ledger`, v2), hors ligne, après `evaluate`

    RUGGER_NO_DOTENV=1 PYTHONPATH=... python -B -m w1aux.ledger --pools <pools exportés> --bundles <out>/bundles \
        --report <out>/w1_report.json --series <série SOL/USD COLLECTED> --out <dossier>

L'outil RE-DÉRIVE indépendamment chaque cycle comportant une entrée, pour chaque essai et chaque bras :
- **causalité** :
  - ordre décision ≤ entrée ≤ sortie ;
  - atterrissage de l'achat après tous les événements de slot ≤ décision + latence ;
  - la vente applique exactement les événements réels jusqu'à son atterrissage : seconde pour une vente à l'horloge, slot pour une vente sur événement ;
- **montants** :
  - jetons achetés, par `buy_exact_in` ;
  - rejeu contrefactuel des échanges réels pendant la détention ;
  - montant reçu, par `sell_exact_in` ;
  - frais de transaction, frais d'échec, P&L et rendement net ;
- **taux de frais** de nos ordres, re-dérivé selon sa source déclarée : intervalle causal des événements à frais jusqu'à la décision, ou taux implicite de l'événement de décision (C-L1) ;
- **sortie re-dérivée** par une boucle de détention propre, dans l'ordre du rejeu gelé. Après chaque événement réel, la règle de sortie de l'essai est appliquée au montant net de vente exact :
  - L1 : plan tp/sl du scorer à l'entrée, plus les ExitOptions ;
  - V2 : ExitRule.
  Un déclencheur vend au slot du déclencheur + la latence : exit_index, exit_slot, ainsi que la raison, l'indice et la marque du déclencheur doivent concorder.
  Sans déclencheur, la vente à l'horloge atterrit à block_time d'entrée + horizon (L1 : ceil(exit_horizon_ms / 1000) ; V2 : max_hold_s) + ceil(latence × 215 ms) secondes. exit_block_time, l'estimation d'exit_slot et exit_index doivent concorder (C-L2, C-L3).
  Les block_time de décision et d'entrée sont contrôlés sur les événements.
- **décomposition exacte**, en arithmétique rationnelle : P&L = mouvement de marché − slippage aller-retour − frais LaunchLab (achat + vente) − frais de transaction − frais d'échec.

Le rapport comparatif donne, par essai et par bras : entrées, cycles clos, gains, P&L total en SOL et la décomposition. La valeur en USD est calculée avec le point de la série disponible à la sortie.

Les empreintes sont contrôlées avant tout calcul : SHA256SUMS des bundles, empreinte interne des bundles L1, MANIFEST des pools, et identité de la série SOL/USD rejouée.

La décision W1 est CITÉE depuis `w1_report.json` et n'est jamais recalculée. Verdict PASS si aucun écart ; sinon FAIL, code de sortie 4.

L'indépendance est PARTIELLE (champ `independence` du registre) :
- boucles propres : atterrissage, taux de frais, détention, déclencheurs, vente à l'horloge, P&L ;
- réutilisés du gel : l'arithmétique de courbe, le décodage des événements et la chronologie des pools ;
- le plan tp/sl L1 est lu dans la ligne, sans relancer le scorer ;
- les décisions d'entrée des politiques ne sont pas re-dérivées.

Le registre publie aussi `cycles_entry_only` (cycles non valorisés, entrée seule vérifiée) et `cycles_not_re_derived`.

Le dossier `--out` ne doit pas exister.

Ce registre relève de la recherche (HISTORICAL_REPLAY) : ce ne sont pas des trades opérationnels du Master, ils ne comptent pas dans les seuils protégés, et un cycle vérifié ne prouve aucune rentabilité.

## Répétition technique (`w1aux.rehearse`, v2.2), sans aucun rendement du pilote ni du holdout

    # pilote : export seul, comptes seulement (protocole data/pilot)
    RUGGER_NO_DOTENV=1 ... python -B -m w1aux.rehearse --run <run pilote> --export-only --out <dossier neuf>
    # rejeu et ledger : pack gelé de test seulement, chargement eager ou paresseux
    RUGGER_NO_DOTENV=1 ... python -B -m w1aux.rehearse --frozen-pack [--lazy] --out <dossier neuf>

- `--export-only` : refusé hors de la fenêtre PILOT_SLOTS exacte. L'outil publie les comptes, les durées, le RSS et le sha du MANIFEST, puis supprime le dossier des pools. Aucun rejeu.
- `--frozen-pack` : refusé si le MANIFEST n'est pas 3224686d. Le taux déclaré est REHEARSAL_DECLARED_NOT_FOR_ECONOMICS. Aucun autre dossier de pools n'est accepté.
- Garde : tout slot dans [466248337, 466442736] ou ≥ S0 est refusé ; un slot absent est aussi refusé.

## Chargement paresseux (`w1aux.lazy`, v5), pour la mémoire du jour J

La chaîne gelée charge toutes les archives, à environ 30 Ko par transaction. Le pic est d'environ ×1 (correction de R02), ce qui ne tient pas en mémoire pour W1.

À l'intérieur de `with lazy_archives():`, chaque appel gelé à `hrr.load_fixtures` reçoit des `LazyArchive` :
- les contrôles sont les mêmes, sur les mêmes octets ;
- un cache ne garde qu'UN pool, le dernier parsé (C-Z1) ;
- passer à un autre pool relit son fichier et revérifie son sha256.

Conséquences :
- la mémoire est bornée par le plus gros pool ;
- les parses restent en O(nombre de pools) : 1 par pool et par passe (testé), au lieu d'un par événement.

Le code gelé et les données ne changent pas. Sur le pack gelé, les bundles, SHA256SUMS, w1_report.json et les registres sont identiques À L'OCTET entre le chargement complet et le chargement paresseux (testé, pool migré compris). Le ledger traite lui aussi les pools UN À UN.

## Pack synthétique (`w1aux.synthetic`), pour la mesure de charge uniquement

`build(out, K)` copie le pack gelé K fois. Les pools sont renommés partout, y compris dans les données base58 des instructions, et le MANIFEST est recalculé avec un bloc `synthetic`.

Les signatures ne correspondent plus aux messages réécrits. Les copies ne sont donc pas « signées » : les politiques V2 s'abstiennent, et L1 attend tout en évaluant chaque décision.

Ce pack ne sert jamais à une lecture économique.

## Rejeux parallèles et reprenables (`w1aux.parallel`, v6), pour le temps du jour J (R02 T-1, options c et e)

Les fonctions gelées `hrr.run_replay` et `harness.run_policy` bouclent sur les pools du MANIFEST. Chaque pool passe par une fonction PURE (`hrr.replay_pool` ou `harness.run_policy_pool`), puis le code gelé assemble le bundle. À l'intérieur de `with parallel_replays(workers, checkpoint_dir):`, chaque appel de ces deux fonctions gelées se déroule en trois temps :

1. **Sonde.** La fonction gelée tourne, mais sa fonction par pool est remplacée par un enregistreur. Celui-ci note les arguments exacts de chaque appel et répond `PoolExcluded` ; le bundle de sonde est jeté. Les arguments par pool sont donc calculés par le code gelé, jamais réécrits.
2. **Calcul.** La fonction par pool ORIGINALE tourne sur chaque appel noté, dans `workers` processus (fork), en commençant par la plus grosse archive. Avec `checkpoint_dir`, chaque résultat est écrit dès qu'il arrive : fichier atomique, puis ligne d'index avec son sha256. Un résultat déjà présent pour la même clé d'appel est réutilisé après vérification de son sha256. La clé couvre l'empreinte du code gelé, le sha de `parallel.py`, le sha de l'archive et tous les arguments ; un type inconnu est refusé.
3. **Assemblage.** La fonction gelée tourne de nouveau. Sa fonction par pool est remplacée par une recherche qui vérifie, appel par appel et dans l'ordre, l'égalité des arguments avec la sonde. Tout écart arrête l'exécution (`per_pool_call_differs_from_probe`).

Bundles, registres et SHA256SUMS sont identiques À L'OCTET au séquentiel. C'est testé pour 1 à 4 processus, en chargement complet et paresseux, et pour toute la chaîne `run_trials` sur un pack synthétique ×2. Le point de reprise exige le chargement paresseux, qui fournit le sha de chaque archive. C'est un cache de reprise, pas une preuve : les bundles finaux restent vérifiés par `evaluate` et le ledger.

**v6.1 (R02 P-1).** La clé de reprise inclut le rang d'occurrence d'un appel identique dans l'exécution, c'est-à-dire dans un même bloc `with`. Les rejeux en double que `run_trials` exécute volontairement pour contrôler le déterminisme sont donc calculés et sauvegardés séparément. Leur comparaison reste un vrai contrôle, avec ou sans reprise. Testé :
- exécution fraîche : aucune réutilisation, soit 13 × nombre de pools calculs ;
- 2e session : aucun recalcul, sorties identiques à l'octet ;
- un non-déterminisme injecté sur la 2e occurrence fait échouer `run_trials` (`l1_replay_not_deterministic`), avec et sans reprise.

**Condition d'exécution (R02 P-2).** `pickle` peut exécuter du code si un fichier a été forgé. Toute copie du dossier de reprise hors de la session s'accompagne du sha256 de INDEX.jsonl, ancré par RUGGER 02 au moment de la copie. Aucune reprise n'est faite sans un INDEX dont le sha correspond à cet ancrage. L'emplacement des copies est une décision du propriétaire.

## Jour J (`w1aux.dayj`, v7) : la chaîne après la collecte, UNE étape par commande (exigences R02 E1 à E9)

L'arbre gelé ne contient aucune commande qui enchaîne les étapes W1 après la collecte. `dayj` se contente d'APPELER les fonctions gelées et les outils w1aux ancrés, dans l'ordre du protocole. Il n'implémente aucune règle et ne calcule ni n'affiche aucun chiffre économique. La décision W1 reste celle d'`evaluate_w1`.

    RUGGER_NO_DOTENV=1 PYTHONPATH=<parent de w1aux> python -B -m w1aux.dayj --step <étape> --out <dossier W1> --s0 467275745 --expect-sha <empreinte ancrée de l'étape précédente> [arguments]

| Étape | Rôle | Arguments |
|---|---|---|
| selfcheck | Contrôle de la machine AVANT toute donnée W1 : Python 3.11 ou 3.12 ; arbre aff97638 sans fichier suivi modifié ; code gelé et modules w1aux ancrés ; `run_trials` sur le pack gelé en lazy et parallèle, avec un SHA256SUMS qui doit valoir 4aee76a3. Les processus, les CPU et la mémoire disponible sont consignés | `--workers` |
| gate | Acceptation des données : `backfill.verify` ok et complet, donc sans arrêt par le plafond ; `coverage compare` lancé par dayj avec le sha du résumé fetch ancré, PASS exigé ; relevé APRÈS du propriétaire consigné sans être jugé. Sortie : GATE.json | `--window-dir`, `--coverage-summary`, `--summary-sha256`, `--after-reading` |
| export | `w1_collection.export`, puis les pools exclus comptés par motif (frozen summarize et usable_timeline). Au-delà de 5 % : STOP | `--window-dir`, `--pilot-dir`, `--other-run` |
| series | `pyth_entries` puis `sol_usd_series`, avec le rapport d'étude ancré | `--sol-usd-dir`, `--study-report` |
| trials | `run_trials` dans lazy et parallel. registered_at prend l'heure réelle du lancement. Les STATS et le sha de INDEX sont consignés. Aucun chiffre de P&L n'est affiché | `--workers`, `--checkpoint` |
| evaluate | `w1_run.evaluate` | `--registry` (autres registres), `--n-boot` |
| ledger | `w1aux.ledger` avec la série rejouée (R-1). PASS exigé | — |
| dossier | DOSSIER_W1.json : identités, étapes, empreintes, sha de tous les fichiers, `cycle_receipt: PENDING_R02` | — |

**Empreinte d'une étape** : sha256 de ses sorties (chemin relatif → sha256, JSON canonique). Elle est affichée à la fin de l'étape. RUGGER 02 l'ancre après lecture, et l'étape suivante l'exige avec `--expect-sha`.

**Avant chaque étape** :
- toutes les sorties antérieures sont rehachées ;
- S0 et les identités du code doivent être inchangés ;
- l'étape ne peut s'exécuter qu'une fois, et n'écrase jamais une sortie.

dayj n'importe aucun module réseau (testé). L'exécution se fait hors ligne (`unshare -rn`), sans aucun secret.

**Testé** sur le pack gelé :
- chaîne complète, étape par étape : empreintes, autocontrôle 4aee76a3, GATE, exclusions, 39 calculs, WAIT_INSUFFICIENT_DATA, ledger PASS, dossier PENDING_R02 ;
- bundles et registre identiques à l'octet à `run_trials` gelé lancé seul ;
- refus quand `--expect-sha` est absent ou faux, quand compare ou verify échoue, quand une étape est hors d'ordre ou déjà faite, quand une sortie a été modifiée, quand S0 change ;
- STOP quand un pool sur trois est exclu (transactions manquantes) ;
- autocontrôle refusé quand les bundles diffèrent, quand l'arbre, la version de Python, le code gelé ou un module w1aux ne correspond pas, sans NO_DOTENV, ou avec workers = 0 ;
- aucun P&L dans la sortie de trials.

Les fonctions de collecte (export, pyth, verify, compare) sont remplacées dans ces tests par des doublures qui enregistrent leurs arguments ; elles ont leurs propres tests gelés ou w1aux.

**Interpréteur : CPython 3.12 UNIQUEMENT (constat v7).** Python 3.12 calcule `sum()` sur les flottants avec une compensation de Neumaier ; 3.11 ne le fait pas. Sur le pack gelé, `top_holder_share` diffère donc au dernier chiffre (0.947628828591641 en 3.12 contre 0.9476288285916411 en 3.11). Les `features_sha256` des bundles L1 diffèrent alors, et l'autocontrôle donne 0408428f au lieu de 4aee76a3. Les décisions du pack sont identiques, mais sur W1 un seuil pourrait basculer. dayj refuse donc toute version autre que CPython 3.12. Le test dédié à 3.11 vérifie à la fois ce refus et cet écart.

**v7.1 : mémoire (T-1).** `run_trials` gelé conserve les documents d'essai L1 (M1, P1b, latence 10 et les 3 descriptifs), avec les journaux des bundles entiers, uniquement pour comparer leur `bundle_sha256` à ses propres rejeux. Dans l'étape trials (et selfcheck), `slim_l1_trial_documents()` laisse les fonctions gelées `w1_eval.run_l1_*` construire et valider ces documents, puis n'en garde que `bundle_sha256`.

Les bundles et les registres restent identiques à l'octet : vérifié par le test de chaîne complète contre `run_trials` seul, et mesuré sur les jeux synthétiques ×10 et ×20. Sur ces jeux, la pente de RSS du processus principal passe de 29,1 à 21,7 Ko par signature.

Avant les rejeux, trials projette le RSS : 150 Mo + 23 Ko × le nombre de signatures du MANIFEST exporté, un simple comptage. Si MemAvailable est inférieur à 1,5 × cette projection : STOP `memory_projection_exceeds_available_owner_decision_needed`, sans rien calculer. Ce refus ne se lève qu'avec `--memory-override-anchored <ancrage R02>`, après une décision du propriétaire sur une machine plus grande.

**v7.1 : corrections de l'audit R02 (d8df149a).**
- **D-2.** L'étape evaluate EXIGE `--registry` : le registre P0 (25 essais). Son sha doit figurer dans `OTHER_REGISTRIES_SHA256`, épinglé dans dayj après ancrage par RUGGER 02. Tant qu'il n'est pas épinglé, l'étape refuse (`p0_registry_not_pinned_yet`). Le nombre de préenregistrements distincts doit valoir N = 32 AVANT evaluate, et `n_trials` doit valoir 32 APRÈS, sinon STOP. N et les sha des registres sont consignés.
- **D-1.** `trials_started` = {registered_at, checkpoint, workers} est consigné AVANT `run_trials`. `--resume` réutilise le même registered_at et le même dossier de reprise. Les sorties partielles sont déplacées vers `quarantine/<horodatage>/`, avec leurs sha consignés ; rien n'est effacé. Chaque registre partiel doit être un préfixe octet du registre final. Une nouvelle exécution sans `--resume` est refusée après un démarrage. Testé : interruption simulée, puis reprise avec 3 processus ; sorties identiques à l'octet à `run_trials` lancé d'un seul tenant.
- **D-3.** DOSSIER : `profitability_demonstrated: false` et `profitability_source: "absent_from_frozen_report"`, puisque le rapport gelé ne contient pas cette clé.

**v7.2 : exécution W1.**
- **Registre P0 épinglé** (D-2) : `OTHER_REGISTRIES_SHA256 = ('f1f26e36…',)`. Il contient 25 essais, a été ancré par RUGGER 02 (96865df7), et donne N = 32 avec les 7 essais W1.
- **M-2a, mémoire mesurée par étape** sur les packs synthétiques ×20 et ×40 :
  - trials (baisse de MemAvailable, parent et 4 processus) : 24,6 Ko par signature ;
  - evaluate gelé (pic du processus) : 54 Ko par signature, sans dépendance au nombre de tirages bootstrap (mesuré pour 200, 2 000 et 10 000) ;
  - ledger : 25,7 Ko par signature.
- dayj projette chaque étape (150 Mo + 26, 56 ou 27 Ko par signature) et s'arrête AVANT trials, evaluate ou ledger si MemAvailable < 1,5 × la projection. **C'est evaluate, gelé, qui limite** : environ 180 000 signatures pour 15,2 Go.
- **parallel.py** : `gc.freeze()` avant la création des processus et `gc.unfreeze()` ensuite. Le ramasse-miettes des enfants ne recopie plus les pages du parent (27,5 → 24,6 Ko par signature). Les résultats sont inchangés.
- **ledger.py** : les bundles sont lus et vérifiés UN À LA FOIS. Seules les lignes avec une entrée et le nombre de pools par bras sont conservés. Le pic passe de 63 à 25,7 Ko par signature. ledger.json et ledger.md sont identiques à l'octet à la v7.1, vérifié sur le pack synthétique ×20.

## Métriques descriptives (`w1aux.metrics`, v7.3), après dayj

    RUGGER_NO_DOTENV=1 PYTHONPATH=<parent de w1aux> python -B -m w1aux.metrics --w1-dir <dossier dayj> --s0 467275745

**Ce que fait l'outil**
- Il applique les définitions de la note J_METRIQUES_DESCRIPTIVES_W1, ancrée par RUGGER 02 AVANT les données.
- Il lit seulement des fichiers ancrés :
  - les bundles, vérifiés contre SHA256SUMS ;
  - w1_report.json ;
  - ledger.json, dont le verdict doit être PASS.
- Il écrit `metrics/metrics.json`, sans jamais l'écraser.

**Métriques publiées, par bras**
- Population : celle de la décision (w1_split ; all, A et B).
- P&L net et brut, espérance nette.
- Mesure pessimiste gelée.
- Taux de réussite, gain moyen, perte moyenne.
- Quantiles, pertes extrêmes, CVaR 5 %.
- Drawdown à taille fixe : ce n'est pas un drawdown de portefeuille.
- Concentration par pool.
- IC 95 % bootstrap par créateur, avec la méthode et la seed gelées.

S'y ajoutent les sensibilités et les comparaisons de M1 avec S2, S1, P1b, P1, P2, S3 et la référence L1.

**Statut DESCRIPTIF.** La décision W1 reste celle d'evaluate_w1 :
- WAIT_* signifie NON CONCLUANT ;
- NO_GO signifie NÉGATIF ;
- CHALLENGER_FOR_W2 signifie POSITIF À CONFIRMER, jamais une autorisation LIVE.

**Tests.** Sur le pack gelé, les entrées, les cycles clos, les créateurs, `mean_return` et `pessimistic_mean` sont égaux à ceux de w1_report pour les 7 bras. Les définitions sont aussi vérifiées sur un échantillon construit à la main. Un bundle modifié ou un ledger FAIL est refusé.

**v7.3 (R02 G-1).** La mémoire disponible lue par dayj vaut min(MemAvailable, limite du cgroup mémoire du processus − usage), en cgroup v1 comme en v2. Dans les sessions cloud, la limite du cgroup claude-code-bash est de 13,35 Gio, contre 15,2 Gio pour MemAvailable. Le seuil d'evaluate avec la marge ×1,5 devient donc ~160 000 à 170 000 signatures.

**Mesure du swap** (pack synthétique ×60, 10 380 signatures, evaluate en cgroup limité avec 4 Go de swap) :
- empreinte de w1_report **identique** (5d6c4533) à chaque exécution menée à terme ;
- durée : 20,7 s sans limite, 33,6 s à pic ÷ 1,5, 55,7 s à pic ÷ 2 ;
- **mais 2 exécutions sur 3 à pic ÷ 1,5 ont été tuées par l'OOM du cgroup** malgré le swap libre (récupération trop lente). Le swap n'est **pas fiable** pour W1.

**Disque** : fichiers de reprise ~5 Ko, bundles ~1,5 Ko et pools exportés ~1,2 Ko, par signature.

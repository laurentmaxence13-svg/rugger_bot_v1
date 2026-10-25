# P1.6e — Export complet des créations LaunchLab mises en cache

## Référence, périmètre et fichiers

Avant travail : branche active main, HEAD et main exactement
`4745d2dcfa284c0865d85a3fece039e492071e41`, statut Git complet propre.
AGENTS.md et CODEX_PLAN_TECHNIQUE_20261022.md relus. La branche créée est
uniquement `fix/p16c-complete-launch-export`.

Le correctif reste local, sans commit, push ni fusion. Fichiers concernés :

- `bot/analyser/research_pipeline.py` : verified_launches, export_dataset et
  l'index des rendements dans backtest, avec les imports nécessaires.
- `tests/test_complete_launch_export.py` : 23 nouveaux tests spécifiques P1.6e.
- `P1_6E_COMPLETE_LAUNCH_EXPORT.md` : ce rapport et le rollback.

Aucun autre module ou test existant n'a été modifié. L'analyse AST confirme que
seules les trois fonctions ci-dessus ont changé dans le module de production.
P1.6a, P1.6b et P1.6d restent intacts, ainsi que capital initial 10 SOL,
allocation, plafonds, TP/SL, scores, modèles, prix et frais.

Les 23 nouveaux tests P1.6e sont distincts des 23 tests temporaires de P1.6c :
ces derniers n'ont pas été copiés ou intégrés implicitement au dépôt.

## Cause et démonstration avant correction

Dans la référence, research_pipeline.py:95 appelle find_raydium_launch, qui
conserve volontairement son contrat singulier de compatibilité. verified_launches
ne reçoit donc qu'une création par payload, même si le cache contient douze
instructions de création et si le scanner a persisté douze candidats.

Le test `test_twelve_creations_match_independent_oracle` a été écrit puis exécuté
sur la copie du module original avant modification : **1 failed, 22 deselected**,
0,26 s. L'export renvoie une ligne ; l'oracle indépendant en attend douze,
avec onze identités manquantes. Les tuples attendus sont construits depuis la
liste explicite de mints/creators/pools de la fixture, pas depuis le parseur.

Le module original est conservé dans la copie sous research_pipeline.before.py.

## Correction de l'extraction et contrat conservé

verified_launches, maintenant research_pipeline.py:86-113, appelle
find_raydium_launches de P1.6b et traite chaque identité retournée séparément.
Chaque événement conserve le contrat :

```text
(block_time, signature_transactionnelle_brute, creator, mint, pool_state)
```

Les creator et pool viennent du même enregistrement de création que le mint.
Les métadonnées de research_launches ne servent jamais à les reconstruire ou
à les répartir sur plusieurs mints. Une ligne research_launches par création
n'est pas nécessaire : l'intégration avec TransactionRecovery vérifie douze
candidats, zéro ligne research_launches, et douze événements exportés.

La signature provient toujours de research_tx_cache.signature, pas de
launch_candidates.signature. Les clés de candidat signature:mint ne sont pas
exportées comme signatures transactionnelles.

Le parseur P1.6b n'est pas modifié : discriminators et filtres existants
s'appliquent toujours. Transactions en erreur, swaps, initializeMint SPL isolée,
instructions fictives ou incomplètes ne deviennent pas des créations.

## Dates et sélection historique par mint

La sélection de l'événement par mint est conservée :

1. Garder l'événement au timestamp le plus ancien.
2. En cas d'égalité pour ce mint, garder la signature lexicographiquement minimale.
3. Ne pas fusionner creator ou pool avec ceux d'un autre événement.
4. Trier les événements retenus selon le tuple historique complet, donc d'abord
   par timestamp puis signature, avec départage stable par les autres champs.

Cela conserve une seule création représentative par mint, pas une ligne pour
chaque répétition d'instruction ou chaque transaction mentionnant le même mint.

La priorité des dates reste celle auditée dans le code original : blockTime du
payload, puis le repli historique déjà persistant research_launches.block_time
lorsque le premier est absent/faux selon la logique existante. Ce repli est une
date enregistrée pour la même signature, pas une date inventée à partir de la
réception, de l'export ou du prix. Sans aucune date exploitable, l'événement est
exclu. La date choisie doit être un entier strictement positif ; le booléen True,
accepté auparavant comme un int Python, est désormais exclu comme date invalide.
Les chaînes, flottants, valeurs non finies et dates négatives ne sont pas convertis.

La jointure LEFT JOIN existante est conservée pour ce repli. Une date présente
dans le payload prime même si les lignes jointes proposent d'autres dates.
La déduplication finale par mint supprime toute multiplication d'événements
due à des lignes jointes répétées. Le test correspondant utilise volontairement
un schéma synthétique de jointure à plusieurs lignes par signature, plus large
que le schéma actif où cette signature est normalement une clé primaire.

Si plusieurs dates de repli jointes sont disponibles et que le payload ne porte
pas de date, la règle historique de sélection de la plus ancienne s'applique.
Ce correctif ne réconcilie pas des historiques contradictoires de dates et
n'apporte aucune nouvelle preuve de leur vérité terrain.

## Doublons et contradictions de métadonnées

- Répétition identique d'une création dans une transaction : le parseur pluriel
  la déduplique, conformément à P1.6b.
- Même mint, métadonnées contradictoires dans une transaction : le parseur lève
  ConflictingLaunchMetadata avant de retourner la liste. verified_launches exclut
  explicitement toute cette transaction et émet un RuntimeWarning portant sa
  signature. Aucun sous-ensemble de ses créations n'est retenu et aucune identité
  n'est assemblée à partir de champs incompatibles.
- Même mint dans plusieurs transactions : sélection historique de la date puis
  de la signature ; les champs restent ceux de l'événement choisi.
- Relecture du cache, rejeu de la même signature et réouverture de base : calcul
  sans état d'export persistant, mêmes résultats et aucun doublon supplémentaire.

Le cache et les reçus ne sont pas modifiés. Le warning ne répare pas la transaction
contradictoire. Avec une configuration Python transformant les warnings en erreurs,
l'export peut s'arrêter explicitement plutôt que poursuivre avec ce rejet.

## CSV et causalité de prior_launches

Le schéma CSV reste exactement :

```text
block_time,signature,creator,mint,pool_state,prior_launches
```

La modification de export_dataset:123-128 est nécessaire lorsque plusieurs
créations du même creator ont le même timestamp. L'ancien compteur incrémentait
à chaque ligne, donnant arbitrairement des antécédents aux suivantes alors
qu'aucune antériorité temporelle n'était prouvée.

Le nouveau compteur inclut seulement les créations retenues de ce creator à un
timestamp strictement inférieur. Toutes les lignes d'un même timestamp lisent
le même état antérieur ; le compteur est mis à jour après le lot temporel.
Ce traitement est cohérent avec la comparaison stricte déjà utilisée pour le
nombre de lancements antérieurs par behavior_backtest. Aucun score ou seuil de
stratégie n'est modifié.

Oracle exécuté : deux créations à t=100, douze à t=200, une à t=300, toutes du
même creator. Le CSV contient quinze lignes et prior_launches vaut
`[0, 0] + [2]*12 + [14]`. Les événements contemporains ne se comptent pas entre eux.

Un second oracle vérifie les douze lignes complètes d'un CSV à trois creators,
avec tous les prior_launches à zéro : date, signature brute, mint, creator et
pool sont comparés champ par champ. Un exemple et son oracle JSON sont conservés
dans la copie isolée sous example_multi_12.csv et example_multi_12_oracle.json.

## Impact sur les consommateurs et adaptation nécessaire du backtest

| Consommateur | Audit / résultat |
|---|---|
| export_dataset et commande dataset | Tuple à cinq champs inchangé ; toutes les créations distinctes retenues sont exportées |
| backtest et backtest_grid | Index des rendements adapté par mint, sans changement des seuils ni du fractionnement |
| momentum_backtest et momentum_grid | Utilisaient déjà des observations par mint ; aucun changement de leur code |
| behavior_backtest et behavior_grid | Utilisaient déjà des observations par mint ; aucun changement de leur code |
| backfill_historical_prices | Déstructure déjà le tuple à cinq champs ; recevra davantage de mints si appelé ultérieurement. Fonction réseau non exécutée dans cette mission |
| export_prices | Ne dépend pas de verified_launches ; inchangé |

Avant ce correctif, backtest indexait `outcomes` par e[1], la signature. Plusieurs
mints exportés pour la même signature auraient écrasé leurs rendements respectifs,
y compris les absences de prix. La correction du seul export aurait donc rendu
ce consommateur incorrect. L'index utilise désormais e[3], le mint, dont l'unicité
est garantie par le contrat audité de verified_launches.

Cette modification strictement liée aux créations multiples reste dans le fichier
autorisé. Le lissage, les scores, seuils, coûts, horizons, critères d'éligibilité,
minima d'entraînement/test et découpage par nombre d'événements sont inchangés.
Les tests utilisent leurs valeurs par défaut, pas des minima réduits pour passer.

Preuve isolant la collision : les deux backtests reçoivent le même oracle de
50 événements, deux mints par signature. Les rendements nets synthétiques sont
alternativement 0,18 et 0,38. L'ancien résultat moyen de test vaut 0,38, celui du
dernier mint écrasant chaque signature. Le résultat corrigé est
`(7*0,18 + 8*0,38)/15 = 0,286666...`, conforme à l'oracle. L'entraînement garde
35 événements et le test 15. Avec 52 événements et le prix d'un seul mint absent,
le résultat garde 36 entraînement, 15 test et une exclusion ; son voisin n'est
pas supprimé. Ces pourcentages sont des rendements de positions synthétiques,
pas une performance démontrée du portefeuille PAPER ou du marché.

## Validation exacte sur copie isolée

Copie : `C:/Users/maxen/AppData/Local/Temp/rugger_p16e_tahwwx3d`.
Python 3.13.15 et pytest 9.1.1 existants ; aucune installation.
Sources/tests actifs copiés sans .env, bases réelles, data, bot/bot ou tests/tests.
Le lanceur de test neutralise load_dotenv, connexions et DNS, désactive les plugins
externes automatiques et les pyc. Seule la paire de sockets locale interne
d'asyncio Windows est autorisée. Aucun RPC, WS, API, téléchargement de prix,
scanner ou bot réel utilisé. Les CSV de prix sont entièrement générés par fixtures.

Commande dans la copie :

```text
<python de la .venv> -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
```

| Exécution | Résultat exact | Durée pytest |
|---|---|---:|
| Baseline avant modification | 274 passed, 1 skipped, 224 subtests passed | 12,98 s |
| Test douze créations contre le module original | 1 failed, 22 deselected, échec attendu | 0,26 s |
| Nouveaux tests après correction | 23 passed, 18 subtests passed | 0,85 s |
| Suite finale | **297 passed, 1 skipped, 242 subtests passed** | **13,93 s** |

Un premier essai des nouveaux tests avait 22 réussites et un échec de nettoyage
de fixture Windows : la connexion SQLite rouverte n'était pas celle capturée
par addCleanup. La fixture ferme désormais sa connexion courante. Aucun code
de production n'a été changé pour contourner cet échec de test.

Le test ignoré reste tests/test_research_pipeline.py:17, « base utilisateur
absente », conformément à l'isolement. Les sous-tests sont contenus dans les
tests parents et ne sont pas à additionner. Les 224 sous-tests de référence sont
conservés ; 18 supplémentaires couvrent contradictions, non-lancements, dates
et payloads invalides.

Couverture synthétique :

- Une/deux/trois/douze créations ; creators et pools indépendants ; creator récurrent.
- Instructions identiques, externes/internes, create+swap ; swaps seuls,
  initializeMint seule et transactions en erreur exclus.
- Contradictions de creator, pool et payer, avec exclusion du lot et warning.
- Jointures SQL multiples, plusieurs transactions pour un mint, ordre de dates
  et départage reproductible malgré inversion de l'ordre d'insertion du cache.
- Dates absentes/invalides, priorité du blockTime et repli historique connu.
- Réouverture, rejeu, intégration TransactionRecovery sans ligne research_launches.
- CSV intégral et prior_launches strictement causal.
- Backtest, prix absent par mint, momentum et comportement avec 52 observations
  complètes, 36 entraînement et 16 test dans les deux derniers consommateurs.
- Exports et backtest sans aucune écriture dans les quatre tables financières
  PAPER d'une fixture déjà clôturée : capital 10,18 SOL inchangé.
- Tous les tests existants, dont P1.6a, P1.6b et P1.6d, sans modification.

## Comparaisons de non-régression

Sept comparaisons avant/après avec créations uniques par transaction : externe,
interne, répétition identique, date de repli connue, plusieurs transactions pour
le même mint, creator récurrent à des dates distinctes, égalités temporelles avec
creators différents. Dans les sept cas, les événements, compteurs de retour et
CSV sont identiques octet pour octet ; empreintes dans comparison.json.

Un huitième cas compare tous les champs de backtest sur 50 événements à signatures
uniques : résultats identiques, 35 entraînement et 15 test. Les différences
intentionnelles sont les créations auparavant absentes, leurs rendements propres,
le compteur prior_launches des événements contemporains et l'exclusion des booléens
comme date. Les comparaisons ne masquent pas ces nouvelles sémantiques.

git diff --check passe ; syntaxe vérifiée sans pyc. Les deux fichiers Python
livrés correspondent octet pour octet à la copie testée. paper_trader.py,
paper_engine.py, transaction_parser.py et tx_recovery.py sont inchangés.

## Limites restantes

- Seuls les payloads présents dans research_tx_cache, fetched_ok=1 et non NULL,
  peuvent être exploités. Une ligne research_launches sans payload ne crée aucun
  événement. Les créations réellement absentes du cache ne sont pas récupérées.
- Le parseur pluriel conserve ses formats et validations P1.6b. Ce correctif
  n'étend pas les IDL/formats RPC ni ne démontre la validité de tous les cas réels.
- La déduplication par mint reste la règle historique : cet export n'est pas
  un journal de toutes les instructions répétées ou tentatives de création.
- La date historique de repli n'est pas réconciliée avec une source externe.
  La signature brute ne fournit pas à elle seule un ordre causal entre événements
  au même timestamp ; prior_launches ne les considère donc pas antérieurs.
- Le découpage train/test par nombre reste inchangé et peut séparer des événements
  contemporains ou d'une même transaction. Ce correctif ne valide pas à lui seul
  le protocole hors échantillon ou l'absence générale de fuite future des analyses.
- Les autres anomalies P1.6c ne sont pas corrigées. Les datasets existants ne sont
  pas réécrits automatiquement ; une régénération autorisée est nécessaire pour
  bénéficier des nouvelles lignes et du compteur causal.
- Aucune couverture réelle exhaustive de marché, exécutabilité des prix ou
  rentabilité n'est démontrée par ces fixtures et exports.

## Rollback précis

Après vérification qu'aucune modification ultérieure de ces fichiers n'est à
préserver, annuler uniquement P1.6e :

```powershell
git restore --source=4745d2dcfa284c0865d85a3fece039e492071e41 -- bot/analyser/research_pipeline.py
Remove-Item -LiteralPath '.\tests\test_complete_launch_export.py', '.\P1_6E_COMPLETE_LAUNCH_EXPORT.md'
```

Commandes documentées, non exécutées. Aucun rollback de base ou de portefeuille
n'est nécessaire : aucune base réelle ni donnée financière n'a été modifiée.
Les CSV déjà produits sont des artefacts à versionner selon le module utilisé ;
ne pas les mélanger silencieusement avec les anciens exports. Le rollback
réintroduit la perte des créations suivantes et les collisions du backtest.

Preuves dans la copie : baseline.txt, regression-before.txt, targeted-after.txt,
validation-complete.txt, comparison.py, comparison.json, source-verification.json,
research_pipeline.before.py, example_multi_12.csv, example_multi_12_oracle.json,
audit_runner.py et sitecustomize.py.

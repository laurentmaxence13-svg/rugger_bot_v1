# P1.6b — Toutes les créations LaunchLab d'une transaction

## Référence et périmètre

Contrôles avant création de branche : branche active `main`, HEAD et main égaux
à `c2d104d52579574e2d016bccf2ffd39a9491ab1e`, état Git propre. Le premier statut
avertissait de caches inaccessibles au bac à sable ; le statut complet a été
refait avec les droits nécessaires et n'a signalé aucun changement local.
Les contrôles imposés ont donc passé avant la création de branche.

Branche : `fix/p16-multiple-launches-per-transaction`. Aucun commit, push ou
fusion effectué. Le HEAD reste au commit de référence.

AGENTS.md et CODEX_PLAN_TECHNIQUE_20261022.md relus. Les sources actives et leurs
usages ont été examinés avant modification. Les anciens résultats du 22 octobre
sont du contexte historique ; les résultats ci-dessous sont reproduits ici.

Fichiers concernés :

- `bot/scanner/transaction_parser.py` : extraction plurielle et validation des identités.
- `bot/scanner/launch_detector.py` : ajout de la liste `launches`, sans retrait des anciens champs.
- `bot/scanner/tx_recovery.py` : persistance atomique des métadonnées propres à chaque création.
- `tests/test_multiple_launches.py` : 29 tests synthétiques supplémentaires.
- `P1_6B_MULTIPLE_LAUNCHES.md` : ce rapport.

Aucun changement de P1.6a, de paper_engine.py, de paper_trader.py, du schéma
SQLite, des cotations P1.4/P1.5, des critères d'entrée, scores, modèles, TP/SL,
allocation, capital initial 10 SOL ou limites de risque. Les autres anomalies
P1.6 sont laissées intactes. Les dix tests de l'audit initial P1.6, présents
uniquement dans une ancienne copie temporaire, ne sont pas présentés comme
des tests du dépôt et n'ont pas été intégrés.

## Diagnostic prouvé

Dans la référence :

| Source | Cause | Conséquence |
|---|---|---|
| transaction_parser.py:90-105 | find_raydium_launch retourne dès la première instruction acceptée | Les créations suivantes sont ignorées |
| launch_detector.py:38-45 | Construction d'un seul mint avec creator/pool scalaires | Impossible d'exprimer plusieurs identités indépendantes |
| tx_recovery.py:132-143 | Boucle sur mints mais utilisation des mêmes champs scalaires ; done après cette boucle | Un élargissement de mints seul mélangerait les créateurs/pools ; les créations perdues ne sont pas rejouées automatiquement |

Les deux nouveaux tests de récupération de deux et trois créations ont été
exécutés contre les trois modules originaux sauvegardés : **2 failed,
26 deselected**, échecs attendus. Les logs montrent `DONE ... candidates=1`
dans les deux cas. Après correction, ces tests passent avec tous les candidats.

## Audit des consommateurs et compatibilité

La recherche des usages dans les sources actives, complétée par une analyse
AST, identifie :

- Un appel de production à `parse_launch_candidate` : le worker de récupération
  de tx_recovery.py. Les usages de test sont notamment test_launchlab_parser.py
  et test_scanner_tx_recovery.py, ce dernier simulant un échec du parseur.
- 39 appels de production à `find_raydium_launch` : launch_detector.py et 38
  analyses/recherches dans bot/analyser. Parmi elles : research_pipeline,
  multi_creator_research_engine, creator_history, token_performance et les
  variantes de backtest. Ces fichiers n'ont pas été modifiés.

Les sept fonctions déjà présentes dans transaction_parser.py sont inchangées,
vérification AST à l'appui. `find_raydium_launch` conserve donc son retour
dict-ou-None et sa sélection historique : instructions externes d'abord, puis
instructions internes. Aucun ancien consommateur n'est forcé à accepter une
liste à la place d'un dictionnaire.

`parse_launch_candidate` conserve ses champs antérieurs et leur projection
singulière : `mints` reste la liste vide ou le singleton historique ; `creator`,
`deployer_candidate`, `pool_state`, `fee_payer`, `signers`, dates, latence et
statut gardent leur sens. La liste nouvelle `launches` est l'interface à utiliser
pour traiter toutes les créations. Ne pas associer tous les mints de cette
liste aux métadonnées scalaires historiques.

Une contradiction entre deux créations du même mint provoque désormais une
exception explicite dans parse_launch_candidate. C'est le comportement de
sécurité choisi pour ce nouveau cas ; la fonction singulière historique reste
inchangée, y compris sur ce type de transaction.

Les anciennes analyses utilisant find_raydium_launch restent volontairement
singulières. Leur migration pour produire des jeux de recherche exhaustifs
n'est pas incluse dans ce correctif du collecteur. Les usages extérieurs au
dépôt ne peuvent pas être vérifiés ici.

## Représentation et ordre par création

Le nouveau champ a cette forme :

```python
"launches": [
    {"mint": "mint-a", "creator": "creator-a",
     "payer": "payer-a", "pool_state": "pool-a"},
    {"mint": "mint-b", "creator": "creator-b",
     "payer": "payer-b", "pool_state": "pool-b"},
]
```

Les dates de bloc, heure de réception et latence appartiennent à la transaction
et restent dans l'enveloppe. Le fee payer de transaction reste distinct du
compte payer propre à l'instruction de création.

`find_raydium_launches`, transaction_parser.py:128-159, visite chaque instruction
externe puis ses instructions internes, rattachées par l'index de leur parent.
L'ordre interne fourni est conservé ; l'ordre d'arrivée des groupes ne remplace
pas l'index parent. Les groupes sans parent exploitable sont ajoutés à la fin,
dans l'ordre fourni, pour conserver la compatibilité avec les fixtures
historiques ne contenant que des instructions internes. Dans ce dernier cas,
un ordre réel d'exécution complet ne peut pas être déduit.

Les règles d'acceptation sont celles déjà présentes : programme LaunchLab,
discriminators existants, au moins les sept comptes nécessaires sous forme de
chaînes non vides ; le repli sur un type explicitement décodé par le fournisseur
est conservé lorsque les données encodées sont absentes. Aucun discriminator
n'a été ajouté ou modifié. Un swap, une initializeMint SPL isolée, un programme
différent, un discriminator inconnu ou une transaction en erreur ne deviennent
pas une création. Ces règles sont vérifiées avec des fixtures synthétiques,
sans nouvelle vérification externe de l'IDL.

## Doublons et contradictions

`unique_launches`, transaction_parser.py:112-125, impose les quatre champs
mint/creator/payer/pool_state non vides et garde l'ordre de première apparition.

- Même mint avec les quatre champs identiques : une seule création est retenue.
- Même mint avec creator, payer ou pool_state différent : exception
  `ConflictingLaunchMetadata`, aucune fusion et rejet de l'ensemble du lot.
- La récupération applique son budget de tentatives existant. La contradiction
  reste visible dans last_error ; si elle persiste, le reçu devient exhausted,
  jamais done. Les tests le vérifient avec un budget de deux tentatives.

La récupération valide aussi la liste reçue avant de la persister. Si un ancien
résultat de parse_launch_candidate sans clé launches lui est fourni, elle
réextrait les identités depuis la transaction avec la fonction plurielle ; elle
ne répartit pas les scalaires sur plusieurs mints.

## Identifiants persistants et historique

Chaque nouveau candidat utilise `signature_transaction:mint`, même dans le cas
d'une création unique. Cette clé dépend du couple, pas du nombre de créations
ni de leur ordre. Le séparateur ne fait pas partie des identifiants Solana en
base58. Il s'agit d'une clé de candidat, pas d'une signature transactionnelle à
transmettre telle quelle à un fournisseur. Les reçus de récupération et le
cache gardent la signature brute de la transaction.

C'est une différence intentionnelle avec les nouveaux singletons de l'ancien
code, qui étaient enregistrés sous la signature brute. Les tests de comparaison
la signalent et la normalisent explicitement ; ils ne revendiquent pas une
identité brute de toutes les lignes avant/après.

Si un singleton historique sous signature brute existe déjà pour le même mint,
il est reconnu et réutilisé sans création d'alias. Les clés qualifiées déjà
présentes sont également reconnues. Le protocole, mint, creator, pool, slot,
block_time et statut doivent correspondre. Une identité contradictoire ou deux
alias préexistants pour le même couple font échouer le lot ; ils ne sont pas
réparés ou fusionnés silencieusement.

Aucune migration de schéma n'est nécessaire. Le payer de chaque création reste
disponible dans launches et récupérable depuis le payload complet du cache
persistant ; aucun nouveau champ payer n'est ajouté à launch_candidates. Cette
reconstruction après persistance est testée avec deux payers distincts.

## Atomicité

`TransactionRecovery.complete`, tx_recovery.py:121-171, conserve la transaction
SQLite `BEGIN IMMEDIATE` et la vérification du reçu pending/numéro de tentative.
Dans cette même transaction :

1. Écriture du cache complet de la transaction.
2. Validation/déduplication des identités par création.
3. Écriture de chaque candidat avec son propre creator et pool_state, ou
   vérification d'un candidat historique compatible.
4. Vérification de la ligne effectivement persistée après insertion.
5. Passage du reçu à done, une fois toutes les créations traitées.

Une erreur au deuxième insert annule aussi le premier insert et l'écriture du
cache. Un cache antérieur est restauré par rollback. Le reçu garde exactement
son état d'avant complete, donc la réservation de tentative déjà effectuée
reste consommée ; le worker peut ensuite journaliser l'échec et programmer
une reprise avec le mécanisme existant. Un insert ignoré par trigger ne suffit
pas à déclarer le lot terminé. Un job périmé ou déjà terminé ne réécrit rien.

Les checks de lignes ne constituent pas un audit de triggers arbitraires
malveillants ; les garanties portent sur le schéma actif et les erreurs
SQLite/trigger injectées dans les tests.

## Tests exécutés et résultats exacts

Copie isolée :
`C:/Users/maxen/AppData/Local/Temp/rugger_p16b_xg21dfw5`.
Sauvegardes des trois modules initiaux dans son dossier before, version testée
dans after. Les sources actives et tests ont été copiés sans .env, bases réelles,
données historiques de marché ni copies bot/bot ou tests/tests.

Python 3.13.15 et pytest 9.1.1 de la .venv existante. Aucune installation.
Le lanceur externe au dépôt bloque connexions et DNS, neutralise load_dotenv,
désactive les plugins externes automatiques et l'écriture de pyc. Seule la paire
de sockets interne locale nécessaire à asyncio Windows est autorisée.
Les appels prix sont simulés ; les accès SQLite concernent uniquement des
bases synthétiques temporaires. Aucun bot/scanner connecté à des services réels
n'a été lancé.

Commande baseline et suite finale, exécutée dans la copie :

```text
<python de la .venv> -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
```

| Exécution | Résultat | Durée pytest |
|---|---|---:|
| Baseline main avant modification | 224 passed, 1 skipped, 190 subtests passed | 11,32 s |
| Première validation des nouveaux scénarios | 26 passed, 9 subtests passed | 1,26 s |
| Deux tests de perte contre les modules originaux | 2 failed, 26 deselected, échecs attendus | 0,42 s |
| Suite finale, 29 nouveaux tests inclus | 253 passed, 1 skipped, 202 subtests passed | 12,51 s |

Le test ignoré est `tests/test_research_pipeline.py:17`, « base utilisateur
absente ». Les sous-tests sont contenus dans les tests parents et ne doivent
pas être additionnés comme des tests indépendants. Les 190 sous-tests de
référence restent inclus ; douze sous-tests supplémentaires couvrent les champs
contradictoires, discriminators, instructions invalides et contextes persistés.

| Scénario obligatoire | Preuve synthétique |
|---|---|
| Création unique | Tous les champs historiques du parseur vérifiés ; comparaison financière avant/après |
| Deux / trois créations | Toutes les lignes présentes, reçus done et cache unique |
| Externes et internes combinées | Ordre d'invocation vérifié dans le parseur et les lignes SQLite |
| Create + swap | Seules les créations sont extraites |
| InitializeMint seul | Aucune fausse création ; find_initialized_mints continue de fonctionner |
| Même mint répété | Déduplication d'instructions externes/internes identiques ; une ligne persistée |
| Creators / pools / payers distincts | Quatre champs propres à chaque création ; payers reconstruits du cache |
| Métadonnées contradictoires | Chacun de creator/payer/pool testé ; aucun cache/candidat/done en sortie du worker |
| Ordre des instructions | Trois créations, imbrication et groupes fournis hors ordre des parents |
| Erreur sur deuxième insertion | Premier candidat et cache annulés ; reçu inchangé ; nouvelle tentative réussie après retrait du trigger |
| Rollback du cache antérieur | Ancien payload intact après erreur |
| Insert ignoré | Aucun done sans ligne ; rollback des écritures précédentes |
| Rejeu après redémarrage | Aucun nouveau fetch et aucune nouvelle insertion |
| Interruption/reprise | Annulation avec tentative pending persistée ; reprise des deux créations à la tentative suivante |
| Pas de doublon financier | Trois clôtures TP, +2,94 SOL, capital 12,94 SOL conservé au rejeu |
| Anciens consommateurs | Sept fonctions du parseur inchangées ; anciens champs conservés ; ancien résultat sans launches accepté par réextraction |
| Rotation P1.6a | Douze créations d'une transaction sélectionnées en deux cycles ; suite de rotation existante toujours verte |
| Identifiants et historique | Clé stable malgré ordre/nombre modifiés dans une fixture artificielle ; singleton historique réutilisé ; contexte incompatible rejeté |
| Tous les tests existants | Inclus dans la suite finale, sans modification de ces tests |

## Comparaison de non-régression

Six scénarios ont été rejoués avec les trois modules sauvegardés puis les
modules corrigés, dans des bases synthétiques neuves : création externe,
création interne, swap, initializeMint seul, transaction en erreur et répétition
identique d'une création.

Les anciens champs du résultat du parseur, le cache, le reçu de récupération,
les données candidates hors identifiant technique, les quatre tables PAPER et
paper_report sont identiques. La seule différence candidate normalisée est la
clé du nouveau singleton : synthetic-tx devient synthetic-tx:a. Le champ
launches additionnel est exclu de la comparaison des anciens champs.

Les trois scénarios avec une création ouvrent 1 SOL au prix 1 et clôturent au
prix 2 avec 2 % de coûts : P&L +0,98 SOL, capital 10,98 SOL avant comme après.
Les trois scénarios sans création n'ouvrent aucune position. Dans ces tests
directs de collect_once sans initialisation de portefeuille, le capital reste
absent avant comme après ; aucune valeur initiale n'est inventée.

Résultats et empreintes normalisées dans comparison.json ; script conservé
dans comparison.py de la copie. Autres preuves : baseline.txt, after.txt,
regression-before.txt, consumer-audit.json et source-verification.json.
Les quatre fichiers Python livrés sont identiques octet pour octet à la copie
de la suite finale ; leur syntaxe a été vérifiée sans pyc. git diff --check passe.

## Limites restantes

- Les reçus historiques déjà done ne sont ni réinitialisés ni reparsés
  automatiquement. Ce correctif n'invente pas les créations autrefois perdues
  et ne répare aucune base réelle. Une reconstruction historique demanderait
  une mission séparée sur données autorisées.
- Les analyses historiques restées sur l'API singulière ne deviennent pas
  exhaustives. Le chemin de récupération du scanner utilise désormais l'API
  plurielle ; ses données sont intégrées à la rotation sans modifier P1.6a.
- Une contradiction persistante conduit à exhausted et à l'absence de tous les
  candidats de cette transaction. C'est explicite et mesurable, pas une preuve
  d'absence de lancement réel.
- Les formats d'instructions encodées, programmes et comptes acceptés restent
  ceux du parseur existant. Aucune prise en charge générale de nouveaux formats
  RPC, d'index de comptes compilés ou de variantes IDL n'est ajoutée.
- Les ordres de groupes internes sans parent valide sont des replis de
  compatibilité ; ils ne démontrent pas l'ordre réel d'exécution.
- Le cache conserve le payer par instruction dans le payload ; les requêtes
  SQL sur launch_candidates seules ne disposent pas d'une colonne payer.
- Les performances sous transactions anormalement volumineuses, pannes système
  ou contention prolongée ne sont pas démontrées par ces fixtures.
- Aucune couverture de marché réelle, exécutabilité des prix ou rentabilité
  n'est démontrée. Ce correctif ne vaut pas validation globale de P2.

## Rollback précis

Avant toute annulation, vérifier qu'aucune modification ultérieure à préserver
n'a été apportée aux cinq fichiers. Pour retirer uniquement P1.6b :

```powershell
git restore --source=c2d104d52579574e2d016bccf2ffd39a9491ab1e -- bot/scanner/transaction_parser.py bot/scanner/launch_detector.py bot/scanner/tx_recovery.py
Remove-Item -LiteralPath '.\tests\test_multiple_launches.py', '.\P1_6B_MULTIPLE_LAUNCHES.md'
```

Commandes documentées, non exécutées. Ne pas restaurer une ancienne base,
supprimer des candidats ou effacer des reçus done. Il n'y a aucune migration
de schéma à annuler et aucune base réelle n'a été modifiée pendant la mission.
Les candidats multiples déjà enregistrés restent des données valides ; revenir
au module précédent réintroduit la perte des créations suivantes pour les
transactions récupérées ensuite. P1.6a reste inclus dans le commit de rollback.

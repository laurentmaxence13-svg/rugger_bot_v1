# P1.6a — Rotation équitable des candidats

## Référence et périmètre

Référence vérifiée avant modification : `main` et HEAD au commit
`9aa20802a89f4e75761c7eeed7671a9bc288aa9b`, sans modification suivie.
Correctif non commité sur `fix/p16-fair-candidate-scheduling`.

Fichiers modifiés/créés :

- `bot/analyser/paper_engine.py` : sélection et état de planification seulement.
- `tests/test_candidate_scheduling.py` : 19 tests synthétiques, dont trois sous-tests.
- `P1_6A_CANDIDATE_SCHEDULING.md` : ce rapport et le rollback.

AGENTS.md et le plan technique ont été relus ; les instructions et constats
historiques de l'audit restent distincts des résultats reproduits ici.
Les dix tests de la copie temporaire P1.6 n'ont pas été supposés présents ni
ajoutés au dépôt. Les tests de rotation ont été recréés.

## Cause prouvée

Dans la référence, `paper_engine.py:116-125` sélectionne les lancements par
`block_time DESC LIMIT max_candidates`. `collect_once`, anciennement aux lignes
638-648, ajoute les positions ouvertes puis tronque encore à cette limite.
Aucun état ne distingue un candidat déjà tenté d'un candidat encore en attente.
Deux cycles avec 12 candidats et une limite de 10 reprennent les mêmes dix.

Avant correction, les trois nouveaux tests « 12 candidats », « 25 candidats » et
« arrivées continues » ont été exécutés avec le module original sauvegardé :
**3 échecs, 15 tests désélectionnés** à cette étape de la suite. Pour 12 candidats,
`m000` et `m001` n'étaient jamais sélectionnés ; pour 25, quinze mints manquaient.
Ils passent après correction. Il s'agit de preuves synthétiques, pas de mesures
de pertes réelles sur Solana.

## Politique choisie

La collecte appelle désormais `_scheduled_candidates` avant les accès prix,
puis `_mark_collection_attempt` juste avant le traitement de chaque mint.
`recent_candidates` conserve sa limite de 10 par défaut pour ses autres
appelants ; le planificateur demande explicitement tous les signaux éligibles.

Une seule table supplémentaire, `paper_collection_schedule`, contient :

- `mint`, clé primaire : déduplication de la planification ;
- `turn`, entier ordinal : place dans la file ;
- `last_lane`, dernier groupe tenté (`position` ou `candidate`, NULL avant la
  première tentative) : permet l'alternance persistante avec un budget de un.

Un index sur `turn` accompagne cette table. Elle est créée à la demande sans
réinitialiser d'état existant et sans toucher aux tables financières. Aucune
migration n'a été exécutée sur une base réelle pendant cette mission.

Au premier passage, les positions ouvertes sont inscrites dans l'ordre
`entry_time,mint`, puis les signaux par date décroissante et départage
`mint,deployer_candidate`. Les nouveaux mints rejoignent la fin de file.
Un mint dupliqué ne consomme qu'une place. La fusion des métadonnées conserve
le principe antérieur des lignes de signaux écrasant celles déjà présentes ;
les doublons de signaux sont maintenant départagés déterministement.

À chaque cycle, pour `B = max(1, int(max_candidates))` :

- les positions ouvertes sont prioritaires, dans leur ordre de file ;
- si des candidats hors positions attendent et B >= 2, au moins une place leur
  est réservée ; les places restantes leur reviennent aussi si les positions
  n'utilisent pas tout leur quota ;
- si B = 1 et les deux groupes existent, ils alternent selon le dernier groupe
  effectivement tenté, enregistré en base ; le premier groupe est celui des
  positions si aucun historique de tentative n'existe ;
- si un seul groupe existe, il peut utiliser tout le budget ;
- au plus B mints distincts sont traités dans un cycle.

Le mint tenté passe à la fin de file **avant** les accès prix. Une absence de
prix, un cooldown, une exception ou une annulation après cette réservation ne
le maintient donc pas en tête. Les autres mints d'un lot interrompu, non encore
tentés, restent à leur place. Les inscriptions et avancements utilisent des
transactions SQLite courtes ; aucune transaction du planificateur ne reste
ouverte pendant un await lorsqu'il possède sa transaction.

En présence d'une transaction appartenant à l'appelant, les savepoints
respectent son autorité : son rollback annule aussi l'état de planification.
La reprise durable est vérifiée sur les connexions en autocommit utilisées par
le moteur de production. Aucun état global en mémoire ne commande la rotation.

Les signaux restent filtrés sur le statut, le mint et la fenêtre de block_time
existants, avec les mêmes bornes inclusives. La planification n'invente aucune
date et ne prolonge aucune éligibilité. Les positions ouvertes restent suivies
même si leur signal est sorti de cette fenêtre, comme auparavant.

## Démonstration de progression

Dans un groupe, après son inscription, un mint a un nombre fini de mints devant
lui. Les nouveaux inscrits ne le dépassent pas ; les mints tentés passent
derrière lui. À chaque cycle complet qui sert ce groupe, le nombre devant lui
diminue jusqu'à sa sélection. Les deux groupes reçoivent une capacité positive
lorsqu'ils coexistent : au moins une tentative par cycle pour B >= 2 ; un cycle
sur deux pour B = 1. Cette propriété suppose que les cycles continuent, que la
base accepte les écritures et que le mint reste éligible dans son groupe.

| Scénario exécuté | Résultat après correction |
|---|---|
| 12 candidats, budget 10 | 12 mints distincts sélectionnés en deux cycles ; les deux oubliés arrivent en tête du deuxième |
| 25 candidats, budget 10 | 25 mints distincts sélectionnés en trois cycles ; dix traitements au maximum par cycle |
| 3 positions + 12 candidats, budget 10 | Les trois positions passent en premier à chaque cycle ; les douze autres mints sont couverts en deux cycles |
| 4 positions + 3 candidats, budget 2 | Une position puis un candidat par cycle ; toutes les positions et tous les candidats passent en quatre cycles |
| 2 positions + 2 candidats, budget 1 | Alternance et rotation correctes sur quatre cycles, avec fermeture/réouverture SQLite après chaque cycle |
| Arrivées entre cycles | Les deux mints non encore tentés passent avant les nouveaux arrivants ; les nouveaux progressent ensuite |
| Trois arrivées supplémentaires par cycle, budget 1 | Les six mints initialement en attente passent dans les six premiers cycles |
| Expiration avant le tour | Le mint expiré est exclu, sans prolongation ; les signaux futurs et non-launch restent exclus |
| Mint dupliqué | Une tentative et une ligne de planification par mint |
| Redémarrage | Les deux mints non tentés conservent la tête de file |
| Aucun signal éligible | Zéro appel au fournisseur de prix |
| Prix absent | Les tentatives tournent malgré zéro cotation enregistrée |
| Exception temporaire / annulation | Seul le mint dont le traitement a commencé avance ; les autres restent prioritaires après reprise |
| Positions prioritaires et TP | Trois positions ferment au TP en premier ; les 25 candidats en attente progressent ; capital 12,94 SOL |
| TP, SL et rejeux | Deux positions, une fermeture TP et une fermeture SL ; capital 10,46 SOL conservé aux rejeux |
| 1, 5 ou 10 candidats | Ordre récent conservé à chaque cycle dans les cas sans égalité ; six comparaisons financières identiques avant/après |
| Dates identiques | Ordre reproductible par mint, sans doublon de traitement |
| Rollback de l'appelant | Les changements de planification sont annulés avec sa transaction |

La sélection n'est pas une garantie d'obtenir un prix ni d'autoriser une entrée.

## Validation exacte

Tous les tests ont été exécutés dans la copie isolée :
`C:/Users/maxen/AppData/Local/Temp/rugger_p16a_9ukn5w76`.
Seules les sources Python actives, les tests actifs et une fixture JSON suivie
ont été copiés. Ni `.env`, ni base réelle, ni données historiques de marché
n'ont été copiés ou lus. Le module original est sauvegardé dans cette copie
sous `paper_engine.before.py` ; le commit de référence reste disponible.

Python 3.13.15 et pytest 9.1.1 de l'environnement existant, sans installation.
Un lanceur de test externe au dépôt désactive le chargement automatique des
plugins, les lectures dotenv et les connexions/DNS réseau. Seule la création
locale de la paire de sockets interne asyncio Windows est autorisée.
Les fonctions de prix sont simulées et les bases SQLite sont synthétiques.
Aucun scanner ou moteur connecté à des services réels n'a été lancé.

Commande baseline et suite finale, dans cette copie :

```text
<python .venv> -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
```

| Exécution | Résultat exact | Durée pytest |
|---|---|---:|
| Baseline main, avant changement | 205 passed, 1 skipped, 187 subtests passed | 6,23 s |
| Première suite ciblée de rotation | 18 passed, 3 subtests passed | 5,21 s |
| Trois tests de rotation contre le module original | 3 failed, 15 deselected, échecs attendus démontrant la régression | 1,02 s |
| Suite finale, 19 tests supplémentaires inclus | 224 passed, 1 skipped, 190 subtests passed | 12,70 s |

Le test ignoré est `tests/test_research_pipeline.py:17`, « base utilisateur
absente », conformément à l'isolement requis. Les sous-tests ne sont pas des
tests parents supplémentaires à additionner. Les 187 sous-tests de référence
restent inclus ; trois sous-tests supplémentaires vérifient les tailles 1/5/10.

Six comparaisons supplémentaires ont chargé le module sauvegardé et le module
corrigé sur les mêmes bases synthétiques, avec 1/5/10 candidats et une sortie
au prix 2 ou 0,5 après une entrée au prix 1. Les listes de tentatives, les quatre
tables `paper_prices`, `paper_decisions`, `paper_trades`, `paper_portfolio` et
les rapports `paper_report` sont identiques avant/après pour ces six cas.
Capitaux finaux respectifs :

| Candidats | Sortie à 2 | Sortie à 0,5 |
|---:|---:|---:|
| 1 | 10,98 SOL | 9,48 SOL |
| 5 | 14,90 SOL | 7,40 SOL |
| 10 | 19,80 SOL | 4,80 SOL |

Ces cas relâchent uniquement le nombre de positions dans leur fixture pour
comparer jusqu'à dix entrées, sans modifier les valeurs par défaut du code.
Les valeurs sont des résultats arithmétiques synthétiques, pas des rendements
attendus. Les empreintes et détails sont dans `comparison.json` de la copie.
Les logs sont `baseline.txt`, `regression-before.txt` et `after.txt`.

`git diff --check` passe. Aucun changement de `paper_trader.py`, du parseur,
des prix, de leur règle de cohérence P1.5, des scores, modèles, TP/SL, allocation,
capital initial 10 SOL ou limites de risque. L'anomalie distincte des créations
multiples dans une transaction est laissée intacte pour P1.6b.

## Limites et risques de régression

- Une file équitable n'augmente pas le débit. Si l'attente dépasse la fenêtre
  d'éligibilité, des candidats peuvent expirer avant leur tour. Aucune couverture
  globale ni couverture de marché réelle n'est revendiquée.
- Lorsque les positions saturent B, leur réserver B-1 places (ou alterner pour
  B=1) espace certaines observations de positions. Des TP/SL peuvent être
  observés plus tard ; leurs règles restent inchangées. Il est impossible de
  traiter toutes les positions à chaque cycle et d'autres candidats avec un
  budget inférieur au nombre de positions. Le cas usuel de trois positions et
  B=10 conserve le suivi de toutes les positions à chaque cycle.
- La borne B porte sur les mints traités, pas sur le nombre total d'appels HTTP
  ou sur le coût SQL de construction du plan. L'inscription parcourt les
  éligibles et la lecture des rangs parcourt la table de planification. Les
  métadonnées historiques sont conservées sans purge automatique.
- Le plan est un instantané de début de cycle, comme la sélection antérieure.
  Aucun TTL supplémentaire n'est ajouté pendant les awaits. Les changements
  d'éligibilité et nouvelles arrivées sont repris au cycle suivant.
- Une interruption répétée avant l'exécution du groupe candidat peut empêcher
  sa progression malgré la réservation de capacité. Le résultat en nombre de
  cycles suppose des cycles complets ; des appels bloqués, erreurs disque ou
  verrouillages SQLite peuvent empêcher toute progression.
- Le marqueur est une réservation de tentative, pas une preuve de réponse de
  prix. Une panne entre sa validation et l'appel prix retarde ce mint d'un tour,
  sans le supprimer ni consommer une entrée financière.
- La file persistante vise un collecteur par base, comme l'orchestration
  existante. Ce correctif n'est pas une attribution exclusive de tâches entre
  plusieurs moteurs concurrents. Les garanties financières existantes restent
  testées séparément par les tests P1.5.
- Lors d'un déploiement sur une base sans cette table, la première file est
  initialisée déterministement ; elle ne peut reconstituer des tentatives
  historiques inconnues. Conserver la table permet la reprise future.

## Rollback précis

Aucun commit, push ou fusion effectué. La branche main reste à la référence.
Aucune base réelle n'a été ouverte ou migrée : aucun rollback de base n'est
nécessaire pour cette intervention.

Pour annuler uniquement ce correctif, après vérification qu'aucune modification
ultérieure de ces trois fichiers n'est à préserver :

```powershell
git restore --source=9aa20802a89f4e75761c7eeed7671a9bc288aa9b -- bot/analyser/paper_engine.py
Remove-Item -LiteralPath '.\tests\test_candidate_scheduling.py', '.\P1_6A_CANDIDATE_SCHEDULING.md'
```

Ces commandes sont documentées, non exécutées. La branche peut être conservée.
Si une base est utilisée ultérieurement avec le correctif, conserver
`paper_collection_schedule` et son index : l'ancien module les ignore. Ne pas
restaurer une ancienne base ni réinitialiser le portefeuille. Revenir à l'ancien
module réintroduit la famine démontrée ; les observations déjà faites restent.

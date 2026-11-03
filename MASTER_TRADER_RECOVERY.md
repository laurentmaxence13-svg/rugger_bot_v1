# Master Trader récupéré et intégré

28 octobre 2026, Europe/Paris. Base locale `59233af`, base distante
`9139dbe30e2871a0dc927c3312d54a88416e94f7`, même arbre
`2b608119c45238e8915b0cb6cae44c852acdfe36`. PR22 ouverte, aucune fusion.
Les fichiers non commités présents après interruption sont conservés; aucun
ancien contrôle réseau ni récupération de session n'a été recommencé.

## Capacités vérifiées

- `bot/master_decision.py` : orchestrateur déterministe shadow, trois stratégies
  existantes, WAIT/NO_TRADE, 12 questions, quatre tailles au plus, historique
  borné/causal et contrôles capital/santé. Une entrée positive nécessite des
  preuves passées déclarées; aucune preuve de rentabilité n'est inventée.
- `bot/master_positions.py` : propositions HOLD, REDUCE, TAKE_PROFIT, EXIT,
  EMERGENCY_EXIT, WAIT_FOR_DATA; quantités atomiques, allocation exacte de basis,
  frais et quote propre au lot. Protections indépendantes du veto d'entrée.
- `bot/policy_research.py` : 24 candidats de recherche utilisant les adaptateurs
  et le ledger P4, paramètres score/liquidité, TP/SL, confirmation, trailing,
  durée et taille. Candidats figés en développement puis holdout créateur séparé;
  registre contre réutilisation, suivi drift et rollback de pointeur shadow.
- `bot/master_audit.py`, `paper_engine.py` : activation explicite shadow, journal
  dans la même base, aucune seconde comptabilité. Propositions et résultats de
  référence séparés. Évaluation, écriture et lecture post-clôture isolées par
  savepoint : panne optionnelle sans annuler une clôture ni désactiver un stop.
  Une panne d'évaluation bloque une nouvelle entrée. Annulation système propagée.
- `bot/__main__.py` : commande hors réseau `policy-research`; aide PAPER expose
  `--master-shadow`. Aucun scanner ou serveur permanent lancé.

## Validation reproduite

111 tests ciblés/intégration, puis suite complète : **1787 passed, 1 skipped,
242 subtests passed**,8,90s; warnings en erreur, stderr0. Le test ignoré exige
une base utilisateur absente et n'est pas remplacé par une base réelle.

```sh
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Isolation jetable : aucun réseau, `.env`, historique Git ou fichier DB utilisateur
copié. Les scénarios de panne de journal, résultat et lecture après règlement
conservent la clôture native et son P&L synthétique exact0,099985SOL.

Recherche reproduite :24 candidats développement,3 comparaisons holdout; égalités
et références conservées, aucun gagnant. Test de tailles à devis distincts :
1SOL→1000 unités et0,10SOL→100 unités; coûts fixes15000lamports chacun, résultats
nets synthétiques0,199985/0,019985SOL. Ce sont des tests de plomberie économique.
L'horizon de replay30s ne permet pas de départager durées900/1800s.

## Limites et reprise

Mode shadow uniquement : aucune proposition ne pilote la stratégie active ni
ne crédite le portefeuille. La promotion reste interdite. Le journal ne remplace
pas une preuve indépendante ou une source authentifiée. Le registre de recherche
doit être conservé par l'appelant pour interdire la réutilisation entre processus.
P3 :0 cycle de marché strictement qualifié; preuves temporelles/source, coûts
propres, sorties liées aux entrées et corpus indépendant restent nécessaires.
Les preuves historiques/P3 et le portefeuille existants sont conservés.

Prochaine étape hors réseau : endurance avec reprises et doublons du journal
shadow, exposition lecture seule, scénarios plus longs qui distinguent réellement
trailing et durée. Toute acquisition future conserve son protocole et ses budgets.

## Deuxième checkpoint : corrections et extension vérifiées

Suite finale : **1831 passed,1 skipped,242 subtests passed**,10,33s, stderr0.
Le premier checkpoint distant est `2c5e18cd17dd15e77deda7e796886c921cff0b46`;
la branche de PR22 contient la suite publiée après ce checkpoint. Le reçu
`validation/MASTER_FIRST_REMOTE_READBACK.json` vérifie les trois composants et
le fichier de validation à cette référence, indépendamment du workspace.

| Cas démontré | Avant correction | Résultat conservé |
| --- | --- | --- |
| Panne audit/lecture après règlement | Risque de rollback de clôture | Clôture et P&L PAPER préservés, journal pending explicite |
| Doublon après32événements | Son propre frame évince un préfixe | Préfixe strict, replay stable y compris après reprise |
| Holdout décalé1ms | Mêmes données réévaluables | Refus de tout recouvrement; adjacence autorisée |
| Durées900/1800s sous horizon30s | Comparaison non informative | Horizon recherche préenregistré jusqu'à1h, sorties distinctes |
| Backup réutilisé en writer | Hash historique devenu invalide | Snapshot immuable et book de reprise distinct |
| Journal corrompu | Rapport optionnel pouvait échouer | UNKNOWN explicite, nouvelles entrées refusées, finances conservées |

Aucune modification de paramètres actifs. Les TP/SL et stops restent évalués
sous l'horizon étendu; ce dernier n'annule pas les protections. Les tests longs
sont disponibles dans `tests/test_policy_research.py`.

| Expérience synthétique | Référence | Variante | Coûts additionnels par position |
| --- | --- | --- | --- |
| Durée |1800s :0,019985SOL net |900s :0,029985SOL net |15000lamports |
| Trailing |5% :0,019985SOL net |3,5% :0,039985SOL net |15000lamports |
| Taille, devis distincts |1SOL :0,199985SOL net/1000atomiques |0,1SOL :0,019985SOL net/100atomiques |15000lamports |

Les trajectoires sont construites pour vérifier les mécanismes, pas pour choisir
un gagnant. Elles ne sont ni des observations de marché, ni une preuve d'avantage.

`validation/MASTER_SHADOW_ENDURANCE.json` conserve le résultat complet1000events,
1000replays,1000conflits,1000rollbacks,10reprises,10snapshots immuables,20opérations
backup,7054invariants. Hash logique financier avant/après identique;0jambe shadow.
Les SQLite synthétiques restent locaux et ne sont pas publiés sur GitHub.

Fichiers créés pendant la récupération et sa suite :

- Modules : `bot/master_decision.py`, `bot/master_positions.py`,
  `bot/policy_research.py`, `bot/master_audit.py`, `bot/master_endurance.py`.
- Tests : `tests/test_master_decision.py`, `tests/test_master_positions.py`,
  `tests/test_policy_research.py`, `tests/test_master_audit.py`,
  `tests/test_master_endurance.py`; le CLI existant reçoit des tests d'intégration.
- Méthodes : `MASTER_DECISION_METHOD.md`, `POLICY_RESEARCH_METHOD.md`,
  `MASTER_ENDURANCE_METHOD.md` et ce rapport.
- Preuves : `validation/MASTER_RECOVERY_VALIDATION.json`,
  `validation/MASTER_FIRST_REMOTE_READBACK.json`,
  `validation/MASTER_SHADOW_INTEGRATION_VALIDATION.json`,
  `validation/MASTER_SHADOW_ENDURANCE.json`,
  `validation/POLICY_RESEARCH_VALIDATION.json`, le journal de tests et les JSON
  reproductibles sous `validation/policy_research_fixture/`.

Commandes réalisables sans source de marché, avec destinations neuves :

```sh
python -B -m bot master-endurance --output /tmp/rugger-new-master-endurance
python -B -m bot policy-research --input validation/policy_research_fixture/input.json --output /tmp/rugger-new-policy-report.json
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

`paper --master-shadow` est un branchement disponible mais aucune collecte n'a
été lancée ici. Il journalise la proposition; le moteur de référence conserve
son autonomie de décision PAPER. Un WAIT shadow ne devient pas un fill, une
entrée ou une autorisation de promotion.

P3 reste bloqué par les preuves de fraîcheur/provenance/identité/création selon
le cas, les coûts propres et les sorties cohérentes avec le lot acheté. Il faut
ensuite des cycles complets et un corpus indépendant suffisamment large pour
comparer les stratégies. Nombre de nouvelles observations de marché :0.
Nombre de cycles économiques de marché strictement qualifiés :0.

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

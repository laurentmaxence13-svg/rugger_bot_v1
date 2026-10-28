# Endurance locale du journal Master shadow

```sh
python -B -m bot.master_endurance --output /tmp/master-endurance-new
python -B -m bot.master_endurance --output /tmp/master-endurance-paced-new --events 1000 --restarts 10 --wall-seconds 30
```

Le répertoire doit être nouveau. Les budgets par défaut sont 1 000 événements,
10 reprises, une seconde virtuelle par événement, sans attente murale. Le
programme installe la garde hors réseau et l'interdiction de lire `.env` avant
les imports moteur. Aucun scanner, service distant, ordre ou signature n'est
utilisé. Les SQLite synthétiques produits restent locaux.

Le test crée une fois une position native de 1 SOL, 1 000 unités atomiques et
5 000 lamports de frais d'entrée synthétiques, par le `record_quote` existant.
Il n'y a pas de seconde comptabilité. Le journal Master propose ensuite
`WAIT_FOR_DATA` : aucune donnée de marché n'est inventée pour obtenir une action.
Ces propositions ne sont jamais appliquées au ledger.

Pour chaque événement, le protocole vérifie le rollback d'un événement
interrompu, l'enregistrement durable, le replay idempotent de la même décision,
le refus d'une identité réutilisée avec des preuves différentes et l'invariance
des tables financières, de l'inventaire et du cash partagé. Les reprises passent
par la sauvegarde SQLite existante, alors qu'un événement non commité est présent
dans le writer. Ce dernier doit être absent du backup. La continuation du backup
doit préserver les décisions commitées, leurs résultats de référence, le refus
de doublons et la position ouverte de quantité inchangée.

`report.json` contient les comptes, les invariants, les hashes des sources
énumérées et de la fixture, une chaîne logique des événements et les empreintes
financières avant/après. Chaque snapshot de preuve reste immuable. Une deuxième
copie SQLite distincte devient le book actif de reprise : les écritures suivantes
ne changent jamais le fichier correspondant au hash de preuve. Dix reprises
produisent ainsi dix snapshots et vingt opérations SQLite de backup. Les
empreintes logiques, contrairement aux octets SQLite physiques, doivent être
reproductibles.

La durée est **virtuelle**. Cette endurance prouve des propriétés logicielles
bornées du journal et des sauvegardes, pas une disponibilité réelle 24 h/24,
une liquidité revendable ni une rentabilité. Zéro jambe réglée par le shadow,
zéro cycle économique de marché qualifié, zéro promotion de politique active.

L'option `--wall-seconds` ajoute désormais un protocole local cadencé de0 à60s.
Elle ne lance aucun scanner : les timestamps d'observation restent ceux de la
fixture synthétique. Les événements sont répartis sur la durée murale demandée,
avec attentes d'au plus100ms; les calculs et backups peuvent allonger cette durée.
Le rapport indique séparément cible, durée murale réellement mesurée, durée
virtuelle et horloge synthétique. Trente secondes locales ne constituent pas
une validation24h/24 ni une mesure de fraîcheur du marché.

Ce mode ajoute une intention de référence de fixture explicitement indisponible
en données de marché, puis le snapshot comparatif de douze champs avant le
résultat de référence. Il mesure par horloge monotone deux étapes locales :
lecture de l'historique/évaluation Master et écriture de la décision/journal.
Pour chaque événement et étape, seul le premier échantillon est conservé; un
replay ne réécrit pas la preuve. Les p50/p95/p99 sont des échantillons locaux,
pas des latences réseau, de transaction ou de source.

Le même audit accepte une intention structurée fournie par le vrai moteur de
référence. Les snapshots et leurs empreintes sont immuables; le premier snapshot
après connaissance du résultat est refusé. Les observations, score, risques,
stratégies, action, montant, frais et inconnues, conditions de sortie, décisions
A/B et statut du résultat futur sont séparés. Les désaccords d'action, de
stratégie ou de montant ne constituent jamais des preuves de meilleure décision.

Tests ciblés sur copie sans réseau ni données utilisateur :

```sh
python -B tools/offline_check.py -q tests/test_master_endurance.py -p no:cacheprovider -W error
```

## Optimisation après mesure murale

Le rapport complet est construit une fois en fin de test, au lieu de N+3R+1
fois. Les contrôles intermédiaires utilisent de vrais compteurs SQL dans les
mêmes transactions. Aucun contrôle financier, d'inventaire ou de reprise n'est
supprimé. Un test impose un seul appel au rapport détaillé.

Paire 1000 événements/10 reprises/cible30s :120,246s→30,279s,7054invariants
identiques. Voir `MASTER_V2_COMPARISON_RESULTS.md` et
`tools/benchmark_master_endurance.py`.

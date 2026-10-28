# Endurance locale du journal Master shadow

```sh
python -B -m bot.master_endurance --output /tmp/master-endurance-new
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

Tests ciblés sur copie sans réseau ni données utilisateur :

```sh
python -B tools/offline_check.py -q tests/test_master_endurance.py -p no:cacheprovider -W error
```

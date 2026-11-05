# P5 — supervision locale PAPER et sauvegarde cohérente

État du 28 octobre 2026 : **PARTIELLEMENT VALIDÉ**. Les fonctions ci-dessous
sont exécutables et testées hors réseau ; aucun serveur permanent n'a été déployé,
aucun RPC/WebSocket réel n'a été ouvert par ce travail, aucun capital exposé.

`bot/operations.py` réutilise le portefeuille et le rapprochement existants.
Il n'initialise, ne migre ni ne répare la base inspectée. Les quantités et frais
natifs restent ceux des tables `paper_token_*`, sans deuxième inventaire.

## Fonctions disponibles

- `build_operational_health` produit capital rapproché, cash disponible, quantités
  restantes par mint/version, P&L natif et frais persistés, état des trois sources,
  motifs de blocage et consigne de reprise sans réentrée ni remise à zéro.
- `OperationalEntryGuard` se branche sur le paramètre `entry_guard` du vrai
  `collect_once`. Il compose les permissions du scanner existant avec état
  d'urgence, fraîcheur et intégrité comptable. Le contrôleur doit fournir la même
  connexion SQLite que celle du cycle ; les décisions se font alors sous son
  verrou existant. Les règles actives de risque et de stratégie restent exigées.
- Les observations RPC, WebSocket et scanner sont des **attestations du
  superviseur appelant**, avec état explicite et `observed_at_ms`. La présence
  d'un token récent ne remplace jamais un heartbeat. Source absente, périmée,
  déconnectée ou future, frais/basis inconnus, capital non rapproché et quantité
  ancienne inconnue bloquent les nouvelles entrées. Un état d'urgence ne bloque
  pas le suivi ni la clôture d'une position déjà ouverte.
- L'API HTTP n'a que trois routes GET : `/health`, `/portfolio`, `/positions`.
  Elle recharge le fichier d'observations et ouvre une connexion SQLite en
  lecture seule à chaque demande ; aucune route d'ordre ni d'écriture. Les
  requêtes de mutation retournent 405. Les erreurs de snapshot retournent 503
  et `allow_new_entries=false`. Le serveur manuel est limité à `127.0.0.1`.
- `backup_paper_database` utilise l'API SQLite online backup, conserve les
  écritures WAL **commitées**, exclut celles encore non commitées et produit un
  fichier neuf local (mode 0600), une empreinte SHA-256 et un contrôle
  `quick_check`. Délai borné par défaut à 10 s, fichier incomplet retiré en cas
  d'échec. Aucune restauration automatique, remplacement ou transmission.

La surveillance ne valide ni la disponibilité réelle d'une sortie, ni les frais
de notre transaction hypothétique, ni la rentabilité. `economic_pnl_verified`
reste faux. Un feu vert n'autorise que les contrôles d'admission PAPER ordinaires.
Le garde opérationnel est une interface intégrable explicitement ; il ne prétend
pas être automatiquement activé dans chaque ancien appel à `collect_once`.

## Commandes manuelles

Utiliser une base PAPER explicitement choisie et des chemins de sortie neufs.
Le JSON d'observations doit provenir du superviseur réel ; ne pas dater
artificiellement une ancienne connexion pour obtenir une permission.

```sh
python -B -m bot.operations health --db work/paper.sqlite --observations work/heartbeats.json --output work/health-next.json
python -B -m bot.operations backup --db work/paper.sqlite --output work/paper-backup-next.sqlite
python -B -m bot.operations serve --db work/paper.sqlite --observations work/heartbeats.json --port 8765
```

Le format des observations est un objet contenant `scanner`, `rpc`, `websocket`,
chacun avec `state` et `observed_at_ms` entier. Les états sains attendus sont
respectivement `ready`, `healthy`, `subscribed`. Le plafond opérationnel de
fraîcheur est 30 000 ms par défaut ; ce n'est pas un seuil de trading.
`--emergency-stop` maintient les nouvelles admissions interdites dans le rapport.

Pour la reprise, arrêter proprement le processus, comparer le reçu de sauvegarde,
inspecter la copie avec `health`, puis choisir manuellement une base de reprise.
Ne pas recopier une base au-dessus d'un processus actif. La sauvegarde conserve
les versions et identifiants des jambes nécessaires à la déduplication existante.
Aucune base utilisateur n'a été ouverte ni sauvegardée pendant cette validation.

## Preuves de cohérence logicielle

Commande :

```sh
python -B tools/offline_check.py -q tests/test_operations.py -p no:cacheprovider -W error
```

Résultat ciblé : **31 passed**, 0,22 s. Les tests démontrent notamment :

- rapport sans INSERT/UPDATE/DELETE/CREATE et sans remise à zéro ; snapshot cohérent malgré un commit concurrent WAL, transaction appelante préservée ;
- refus sur données manquantes, périmées, futures ou état d'urgence ;
- vrai cycle `collect_once` : nouvelle entrée refusée, TP existant traité une
  fois, capital synthétique 10 → 10,18 SOL, répétition sans second crédit ;
- sauvegarde WAL puis reconnexion conservant le lot partiel de 60 unités et une
  unique jambe, capital et frais identiques ;
- exclusion des écritures non commitées, refus des destinations existantes et
  liens symboliques, suppression d'une copie invalide ou interrompue ;
- routes HTTP en lecture seule, reload des observations, écoute limitée au
  loopback vérifiée avec un serveur factice, sans ouvrir de socket.

Restent ouverts : raccordement des heartbeats du superviseur de production à
cette interface, déploiement serveur explicite, surveillance des ressources,
rotation/rétention des sauvegardes et endurance sur une machine dédiée. La
présente livraison ne déclare pas un fonctionnement 24 h/24 démontré.

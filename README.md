# Rugger Bot V1 — moteur Solana en simulation

## Terminal visuel PAPER (Windows, navigateur)

**Livré et testé :** lancer **LANCER_TERMINAL_PAPER.bat**, puis ouvrir **http://localhost:8501**. L'interface affiche les décisions, les positions PAPER locales, leurs cotations USD enregistrées, le P&L des cycles clos, et accepte les JSON/ZIP des expériences Helius depuis GitHub Actions. Le bouton Démo présente exclusivement des opérations inventées et marquées fictives.

Les cycles PAPER Master/référence sont séparés des scénarios contrefactuels et de l'ancien moteur PAPER. Le terminal est en lecture seule, ne lance aucun ordre réel et ne prouve aucune rentabilité. Voir **[TERMINAL_PAPER.md](TERMINAL_PAPER.md)**.


Entrées, suivi, sorties et portefeuille sont intégrés en **PAPER ONLY**. Aucun
ordre réel ni code de signature de transaction. La rentabilité n'est pas démontrée.

L'inventaire atomique et les sorties complètes/partielles/refusées sont maintenant
reliés au portefeuille. Démonstration économique synthétique sans réseau :

```sh
python -B -m bot economic-demo --output work/atomic-demo-next
```

Voir [l'intégration économique P3](P3_ATOMIC_INVENTORY_RELEASE.md) pour les
quantités, frais, résultats, reprise et conditions encore manquantes sur marché.

Lancer une démonstration complète sans réseau ni `.env` (dossier neuf) :

```sh
python -B -m bot demo --output work/demo-001
```

Le rapport contient le cycle exécuté et un tableau de bord avec provenance des
métriques. Voir [la livraison fonctionnelle](RUGGER_V1_FUNCTIONAL_RELEASE.md)
pour les commandes, résultats, reprise et limites du modèle.

## Préparation des données P3

Le journal et les composants de préparation sont séparés dans `bot/p3/`.
La collecte publique est bornée et exige `--network` ; importer le module ou
lancer les tests ne démarre aucun accès marché. Un ledger historique passé
comme base de capture est refusé. Les cotations à taille donnée restent des
estimations, avec coûts et fraîcheur inconnus explicitement conservés.
Voir [le protocole](P3_CAPTURE_PROTOCOL.md), [le rapport de disponibilité](P3_DATA_READINESS_REPORT.md)
et [les accès/droits des sources](P3_DATA_SOURCES.md). Le GO économique P3 n'est
pas acquis par ces vérifications logicielles.

## Portée des validations

Le développement cloud et les vérifications P1 utilisent des copies de sources et des données synthétiques, sans réseau de marché. Les garanties et exclusions courantes sont décrites dans `P1_FINAL_GATE_RECHECK.md`. Le protocole expérimental séparé est décrit dans `P2_SYNTHETIC_PROTOCOL.md` ; il n'active aucun modèle du bot.

Les montants du ledger restent exprimés en SOL, mais le calcul existant applique des rendements de prix USD sans cours SOL/USD à chaque entrée/sortie. Il suppose donc implicitement un change constant. Ce sont des unités de simulation, pas un P&L économique en SOL vérifié ; voir `ECONOMIC_VIABILITY_AUDIT.md`.

La voie `paper_trader` autonome ne partage pas la garde mémoire du scanner intégré. Elle reste hors du périmètre P2 supervisé, même lorsque sa fermeture de ressources est testée. Les variantes historiques de recherche ne deviennent pas des évaluateurs validés par leur seule présence dans le dépôt.

## Ce qu'elle fait
- se connecte à Solana via Helius ;
- écoute en WebSocket les transactions qui mentionnent le programme Raydium Launchpad ;
- récupère la transaction confirmée via `getTransaction` ;
- reconnaît une instruction de création LaunchLab et ses comptes mint/créateur/pool ;
- enregistre le mint, la signature, le slot, l'heure et un `deployer_candidate` dans SQLite.

`deployer_candidate` provient du compte créateur de l'instruction LaunchLab.
Ce n'est pas une preuve d'identité de la personne ni de son comportement futur.

## Installation Windows
1. Décompresser le ZIP.
2. Ouvrir le dossier `rugger_bot_v1` dans VS Code.
3. Ouvrir Terminal > New Terminal.
4. Créer l'environnement :
   `py -m venv .venv`
5. Installer :
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`
6. Copier `.env.example` en `.env`.
7. Dans `.env`, remplacer `COLLE_TA_CLE_ICI` par ta clé Helius.
8. Lancer :
   `.venv\Scripts\python.exe -m bot.main`

## Base de données
Les détections sont enregistrées dans `data/rugger_bot.db`.

## Limite volontaire
Cette V1 ne prétend pas détecter tous les memecoins Solana. Elle commence par un protocole documenté, puis on ajoutera les autres protocoles après validation.

## Recherche et simulation (aucun ordre réel)

Depuis la racine du projet, avec l'environnement Python activé :

1. Lancer le scanner `python -m bot.main` pour recueillir de nouveaux lancements.
2. Dans un autre terminal, enrichir l'historique : `python -m bot.analyser.multi_creator_research_engine --max-creators 10 --max-tx 100 --rpc-interval 2.5`. La limitation RPC est partagée par ce processus, respecte `Retry-After`, ralentit après un 429 et reprend grâce au cache SQLite. Un 429 reste possible selon le forfait Helius ou d'autres processus qui utilisent la même clé. Les erreurs épuisées arrêtent la page concernée au lieu de la marquer comme une liste vide.
3. Exporter le corpus : `python -m bot.analyser.research_pipeline dataset`. Seules les transactions dont le mint est initialisé dans la même transaction LaunchLab sont qualifiées de lancements. `deployer_candidate` historique n'est pas automatiquement un créateur confirmé.
4. Recueillir les prix sans entrer en position : `python -m bot.analyser.paper_trader`. Le processus lit les nouveaux lancements de la base et consulte les paires Solana DexScreener. Sans modèle validé, il enregistre les prix mais n'ouvre aucun trade simulé. Le scanner doit tourner en parallèle pour alimenter la base.
5. Exporter les prix : `python -m bot.analyser.research_pipeline prices --output data/paper_prices.csv`.
6. Pour compléter les anciennes observations avec Birdeye : `python -m bot.analyser.research_pipeline historical-prices --output data/prices_historical.csv`. La commande utilise uniquement `BIRDEYE_API_KEY` dans `.env`, ne signe aucune transaction et conserve les points réellement disponibles.
7. Après suffisamment de lancements **et** de prix horodatés d'entrée/sortie, lancer `python -m bot.analyser.research_pipeline backtest --prices data/prices_historical.csv --output data/model.json`. Le découpage est chronologique (70 % entraînement, 30 % test), la règle de score utilise seulement l'entraînement, les prix manquants provoquent un refus, et un coût hypothétique de 200 points de base est déduit. Le modèle exige au moins 30 événements d'entraînement et 15 de test ; une taille minimale ne garantit pas qu'il soit fiable.
7. Si le test hors échantillon produit un modèle positif avec au moins cinq signaux, lancer `python -m bot.analyser.paper_trader --model data/model.json` pour simuler les entrées et sorties. L'entrée est observée 60 à 180 secondes après le signal, la sortie après 3 600 secondes. Les prix indicatifs DexScreener ne garantissent pas des exécutions au même prix ; commissions, slippage et impact réels peuvent différer.

Le paper trader conserve maintenant le dernier prix et le pic observé d'une position. Un modèle validé peut aussi fournir `tp_pct`, `sl_pct`, `hold_seconds` et `cost_bps` dans son JSON : la sortie simulée est alors déclenchée par TP, SL ou expiration du délai, avec la raison enregistrée dans `paper_trades.exit_reason`. Ces paramètres restent uniquement simulés.

Les garde-fous sont configurables avec `--max-open 3 --max-entries-day 20 --max-daily-loss 10 --max-candidates 10`. Le mode `--poll 1` est disponible pour le paper, mais il peut provoquer un ralentissement/429 chez le fournisseur de prix ; le code respecte alors le délai de refroidissement retourné par l'API.

Les moteurs `bot/analyser/creator_backtest_v25.py` et `creator_backtest_v26.py` conservent des diagnostics historiques sur les relais/wallets, ventes et règles TP/SL. Leurs partitions et la disponibilité historique des données ne sont pas certifiées causales : leurs sorties sont explicitement exclues de la validation P2 et de l'éligibilité des modèles, même si un rendement simulé est positif. Ils ne fournissent pas une preuve hors échantillon.

Un diagnostic complémentaire teste un signal de momentum pré-entrée : la variation
entre +60 s et +300 s est observée avant une entrée simulée à +300 s, puis évaluée
sur une sortie à +15 min et +1 h. La sélection du seuil utilise uniquement les
données d'entraînement et le test est hors échantillon à plusieurs coûts :
`python -m bot.analyser.research_pipeline momentum-grid --prices data/prices_historical.csv --output data/momentum_grid.json`.
Ce diagnostic reste exploratoire et ne peut pas activer le paper trader automatiquement.

Le diagnostic comportemental ajoute ensuite des variables observables avant
l'entrée : nombre de lancements antérieurs du créateur, vente du développeur,
transfert vers un wallet relais et couverture du cache Helius. Les transactions
postérieures à l'entrée simulée sont exclues pour éviter la fuite d'information.
La commande est :
`python -m bot.analyser.research_pipeline behavior-grid --prices data/prices_historical.csv --output data/behavior_grid.json`.
La règle retenue sur l'entraînement est testée chronologiquement à +15 min et
+1 h, avec 200/500/1000 points de base de coûts. Un résultat négatif laisse le
paper trader sans modèle ; aucun seuil n'est forcé.

Pour générer uniquement son rapport de recherche JSON (sans activer de modèle) :
`python -m bot.analyser.creator_backtest_v26 --output data/behavior_v26_results.json`.
Le rapport peut être limité à un créateur avec `--creator ADRESSE`. Il faut disposer d'au moins 8 launches exploitables ; le programme peut être long et respecte le mode PAPER uniquement.

Les résultats sont dans `paper_prices` et `paper_trades` dans SQLite. Aucun module de ce parcours n'utilise de clé privée, ne signe ni n'envoie de transaction. Les cotations actuelles ne remplacent pas l'historique ; la commande Birdeye ci-dessus doit être utilisée quand un backtest historique est nécessaire.

## Programme unique PAPER

Le programme final regroupe le scanner LaunchLab, les prix/liquidité, le suivi
des positions simulées et l'observation comportementale Helius dans un seul
processus. Le scanner et l'enrichissement Helius partagent une porte RPC
adaptative : la cadence ralentit automatiquement après un 429 au lieu de
répéter des appels en rafale. Utiliser :

`python -m bot.analyser.paper_engine --poll 15 --report data/paper_engine_report.json`

Le processus enregistre les cotations dans `paper_prices`, suit les positions
simulées existantes, observe le cache Helius jusqu'à l'instant courant et écrit
un rapport marqué `paper_only: true`. Il n'ouvre aucune position sans modèle
chronologique validé. `--no-scanner` permet de ne lancer que la collecte si un
scanner est déjà actif. `--poll 1` reste déconseillé avec une API publique : la
fréquence réelle doit respecter les limites du fournisseur.

Pour voir immédiatement le cycle complet `ENTRY`/`EXIT` sans attendre un
modèle validé, utiliser uniquement le mode diagnostic :

`python -m bot.analyser.paper_engine --shadow-baseline --poll 15 --report data/shadow_paper_report.json`

Ce mode simule toutes les entrées observables avec TP +10 %, SL -10 %, horizon
1 h et coût 200 points de base. Il est explicitement marqué
`strategy_mode: shadow_baseline` dans SQLite et dans le rapport. Il ne mesure
pas une stratégie rentable et ne peut jamais activer d'ordre réel ; il sert à
vérifier que les cotations, entrées, sorties, frais et limites fonctionnent.
Sous Windows, `START_SHADOW_PAPER.bat` lance ce mode. Le mode normal reste
`START_PAPER_ENGINE.bat` et attend un modèle hors échantillon validé.

Le moteur suit maintenant chaque lancement pendant 7 200 secondes (2 heures,
ce qui couvre la sortie à 1 heure). Pour éviter de perdre les premières
cotations, il accepte par défaut une liquidité observée d'au moins 1 000 USD,
enregistre cette liquidité dans `paper_prices` et laisse le backtest décider
ensuite si la série est exploitable. Le collecteur essaie les deux formats
DexScreener (`token-pairs` puis `latest/dex/tokens`) : un token trop récent
répondant 400/404 est simplement réessayé au cycle suivant et ne bloque plus
la boucle. `--min-liquidity` permet d'augmenter le seuil sans modifier le code.

Le scanner copie aussi chaque transaction Helius confirmée dans le cache de
recherche. Ainsi les nouveaux lancements observés en direct pourront être
rejoints par les prix paper lors des exports futurs. Cette copie est une
lecture seule : aucune clé privée, signature ou transaction sortante n'est
présente dans le projet.

Sous Windows, `START_PAPER_ENGINE.bat` lance exactement cette commande avec le
Python de `.venv` quand il existe. Les étapes dataset, prix historiques et
backtests restent des commandes de recherche reproductibles du même projet ;
elles ne sont jamais exécutées automatiquement par la boucle live et ne
peuvent pas activer un modèle négatif ou incomplet.

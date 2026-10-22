# Rugger Bot V1 — scanner Solana en simulation

Cette V1 ne peut ni acheter ni vendre. Elle ne contient aucun code de signature de transaction.

## Ce qu'elle fait
- se connecte à Solana via Helius ;
- écoute en WebSocket les transactions qui mentionnent le programme Raydium Launchpad ;
- récupère la transaction confirmée via `getTransaction` ;
- cherche une instruction SPL `initializeMint` / `initializeMint2` ;
- enregistre le mint, la signature, le slot, l'heure et un `deployer_candidate` dans SQLite.

`deployer_candidate` = premier signataire / fee payer observé. Ce n'est pas une preuve d'identité du créateur.

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

Le moteur `bot/analyser/creator_backtest_v26.py` est un parcours de recherche séparé et plus riche : relais/wallets, ventes observées, séries de prix avant la vente, règles TP/SL et sélection chronologique anti-fuite. Il n'est pas activé automatiquement par le paper trader tant qu'un modèle multi-créateur validé n'est pas exporté. Cette séparation évite de transformer une exploration prometteuse en signal réel par erreur.

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

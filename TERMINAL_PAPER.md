# Rugger Bot — terminal de simulation PAPER dans le navigateur

**Livrable :** interface Streamlit locale, utilisable sous Windows. Mode strictement **lecture seule**, sans wallet, sans clé API et sans transaction réelle. Les décisions Master et référence, cycles PAPER du ledger et projections économiques sont volontairement séparés.

## Démarrage Windows (le plus simple)

1. Depuis GitHub, ouvrir la branche **main**, puis télécharger le ZIP du code. Décompresser le projet dans un dossier accessible sur le PC.
2. Double-cliquer sur **LANCER_TERMINAL_PAPER.bat**. Le lanceur vérifie Python, crée un environnement séparé pour le terminal et installe Streamlit si nécessaire. Il ouvre automatiquement le navigateur seulement après avoir vérifié que le serveur répond.
3. Vérifier le message vert **[OK] TERMINAL OPERATIONNEL** dans la fenêtre noire. Le navigateur ouvre **http://127.0.0.1:8501**. Garder la fenêtre noire ouverte.
4. Activer **Démo entièrement fictive** pour vérifier immédiatement l'interface avec deux transactions fabriquées, clairement étiquetées. **Désactiver** pour revenir aux preuves réelles.

Ou, depuis le terminal de VS Code :

    py -m pip install -r requirements-dashboard.txt
    py -m streamlit run bot/dashboard/app.py

## Afficher les fichiers réellement produits par Helius / Rugger

Dans le volet gauche :
- Le dossier **paper_artifacts** est lu automatiquement lorsqu'il contient les JSON du bot ; les fichiers nouveaux peuvent être rechargés toutes les 10 secondes. Il n'y a pas de scanner ou de trading démarré par l'interface.
- Les captures exécutées sur GitHub restent sur GitHub jusqu'à ce qu'elles soient téléchargées. Dans [GitHub Actions](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions), ouvrir une exécution Helius réussie et la section **Artifacts** pour récupérer le ZIP, puis importer ce ZIP directement depuis le volet gauche du terminal. Aucune extraction manuelle nécessaire.
- Formats pris en charge : rapports de modèle S1/S2 réels, acquisitions signées et observations S1/S2, résumé d'intégration signé, **portefeuille dual-arm PAPER** et fichiers ZIP qui contiennent ces JSON.
- Le lien GitHub Actions s'ouvre dans l'interface. Le terminal ne promet pas de télécharger automatiquement les archives privées : l'import explicite respecte les permissions GitHub.

## Comment interpréter les chiffres

La valeur initiale de **10 SOL** est le capital PAPER de référence : ce n'est pas un solde de Phantom, ni un solde recalculé à travers plusieurs exécutions différentes. Un P&L Master apparaît **uniquement** si une source de type ledger PAPER contient des cycles clôturés par la branche Master. Sans ces cycles, il reste indisponible.

Les achats et sorties S1/S2 **hypothétiques** sont affichés dans l'onglet **Scénarios memecoins**, jamais dans les trades clôturés Master. La variation brute n'inclut pas nécessairement les frais externes et ne prouve aucune rentabilité. Les graphes décrivent la valeur d'un lot hypothétique, **pas des chandeliers de marché**. Le cours en chandeliers exigera un flux de prix horodatés supplémentaire.

Le tableau de bord n'allume pas LIVE. Il n'achète ni ne vend aucun token. Il ne lance aucune collecte Helius : la collecte du bot est distincte et nécessite toujours ses autorisations et son budget API. L'actualisation à 10 secondes ne relit que les fichiers locaux.

## Vérifications

    py -m unittest discover -s tests -p test_dashboard_evidence.py -v
    py -m compileall -q bot/dashboard

Un fichier GitHub Actions dédié effectue ces vérifications et importe Streamlit en environnement isolé. Les preuves restent des JSON locaux et ne sont pas téléchargées vers le serveur du développeur.


## Connexion directe au moteur PAPER déjà présent

Le terminal lit automatiquement **data/rugger_bot.db en lecture seule** : les tokens, les cours USD réellement enregistrés dans paper_prices, les décisions dans paper_decisions, les positions simulées ouvertes et les clôtures dans paper_trades. Il lit aussi le rapport **data/paper_engine_report.json**.

Pour actualiser l'écran à mesure que le moteur enregistre de nouvelles données : laisser tourner le scanner et **START_PAPER_ENGINE.bat** dans leurs propres fenêtres, ouvrir le terminal dans une autre fenêtre, puis activer **Recharger les preuves toutes les 10 s**. Le terminal ne démarre lui-même aucun appel Helius, aucun trading réel, aucune transaction et ne modifie jamais la base.

Les positions de ce moteur ancien sont marquées **PAPER_ENGINE** ou **SHADOW_BASELINE** ; elles ne sont **pas des trades Master**, et leur P&L issu de prix USD n'est pas une preuve de rentabilité réelle en SOL. L'onglet **Prix USD observés** montre les points de prix stockés (courbe horodatée, sans fabriquer de bougies ou un prix exécutable).

Si les fichiers ne sont pas encore présents, le terminal reste vide et explicite. Le mode démonstration n'affiche que des exemples entièrement fictifs.


## Dépannage Windows : ERR_CONNECTION_REFUSED

L'adresse localhost:8501 ne fonctionne **que si Streamlit est réellement lancé sur ton PC** ; ce n'est pas un service hébergé sur GitHub.

1. Télécharger de nouveau le projet depuis GitHub, branche **main**, option **Code > Download ZIP**, puis **extraire complètement** l'archive.
2. Double-cliquer sur **LANCER_TERMINAL_PAPER.bat** dans le dossier extrait. Le navigateur ne s'ouvre que lorsque le serveur est disponible. Ne pas exécuter le BAT à l'intérieur d'un ZIP non extrait.
3. Si le lanceur échoue, **la fenêtre noire reste ouverte** avec la cause. Envoie une capture de cette fenêtre et, si demandé, les dernières lignes du fichier **terminal_paper_serveur_stderr.log** (et éventuellement **terminal_paper_serveur_stdout.log**) dans le même dossier.

Le terminal dispose désormais d'un Python virtuel **.venv-dashboard** distinct du Python **.venv** déjà utilisé par le bot. Cela évite de perturber les bibliothèques du bot existant. Aucune clé Helius ni portefeuille Phantom n'est nécessaire pour ouvrir cette interface.

Si Python n'est pas installé, récupérer Python 3.12 sur https://www.python.org/downloads/ puis relancer le BAT.

Pour valider seulement le démarrage et refermer automatiquement le serveur sur Windows :

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\LANCER_TERMINAL_PAPER.ps1 -SmokeTest

Cette commande diagnostique n'est pas nécessaire pour l'usage normal.

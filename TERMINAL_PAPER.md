# Rugger Bot — terminal de simulation PAPER dans le navigateur

**Livrable :** interface Streamlit locale, utilisable sous Windows. Mode strictement **lecture seule**, sans wallet, sans clé API et sans transaction réelle. Les décisions Master et référence, cycles PAPER du ledger et projections économiques sont volontairement séparés.

## Démarrage Windows (le plus simple)

1. Depuis GitHub, ouvrir la branche **feat/paper-terminal-20261101** ou sa pull request, puis télécharger le ZIP du code. Décompresser le projet dans un dossier accessible sur le PC.
2. Double-cliquer sur **LANCER_TERMINAL_PAPER.bat**. La première fois, le script crée un environnement Python local et installe Streamlit. Python 3.11 ou supérieur doit être installé.
3. Ouvrir **http://localhost:8501** dans le navigateur si la page ne s'ouvre pas seule.
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

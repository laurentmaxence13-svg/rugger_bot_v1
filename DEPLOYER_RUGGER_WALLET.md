# Rugger Wallet — ouvrir dans un navigateur, sans Python local

Le dépôt contient un point d'entrée `streamlit_app.py` pour Streamlit Community Cloud.

## Déploiement initial (action du propriétaire du dépôt)
1. Ouvrir https://share.streamlit.io/ et se connecter avec GitHub.
2. Créer une application à partir du dépôt `laurentmaxence13-svg/rugger_bot_v1`, branche `main`.
3. Choisir `streamlit_app.py` comme fichier d'entrée, Python 3.12 si proposé.
4. Dans les paramètres avancés, choisir `requirements-cloud.txt` si la plateforme permet un chemin personnalisé. Sinon le déploiement racine utilise automatiquement `requirements.txt` du bot : pour éviter les dépendances inutiles, utiliser le point d'entrée `cloud/streamlit_app.py` et le `cloud/requirements.txt` placés dans le même dossier.
5. Choisir un nom et lancer le déploiement. La plateforme fournit l'URL réelle après succès.

## Ce qui est disponible
- Interface de lecture seule, aucun ordre, aucune connexion wallet.
- Démonstration entièrement fictive pour vérifier l'apparence.
- Import manuel de JSON/ZIP de preuves GitHub Actions.
- La base locale Windows `data/rugger_bot.db` n'est PAS accessible au serveur cloud.
- Le rafraîchissement de l'interface ne déclenche pas de collecte Solana.
- Aucune transaction Master réelle/PAPER n'est fabriquée pour remplir les écrans.

## Limites de sécurité
Le dépôt contient des fichiers et recherches qui ne doivent pas être exposés publiquement sans audit. Garder l'application et les preuves privées si nécessaire. Ne jamais saisir de clé Helius, clé privée Phantom ou seed phrase dans l'interface. L'hébergement et l'automatisation des preuves restent des étapes distinctes.

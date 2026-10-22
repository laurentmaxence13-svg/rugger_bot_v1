# Installer les consignes Codex dans VS Code — Windows

## Ce que contient ce pack

Ce ZIP contient uniquement des **documents d'instruction et d'audit**. Il **ne modifie pas le programme automatiquement**, n'inclut pas la base SQLite ni les clés API et ne remplace aucun fichier Python. L'archive source `RUGGER_BOT_CODEX_COMPLET_20261022_190551.zip` a déjà été examinée séparément.

## Étapes

1. Dans VS Code, ouvre **le dossier racine interne** `rugger_bot_v1`, celui où existent directement `bot`, `tests`, `data` et `README.md`. Si ton explorateur montre un dossier externe `rugger_bot_v1_paper (1)`, ouvre bien son sous-dossier `rugger_bot_v1`.
2. Télécharge le pack ZIP dans ton dossier `Téléchargements`, puis extrais-le dans **le dossier racine du projet**, sans remplacer de fichiers existants. Les documents importants à déposer à la racine sont `AGENTS.md`, `CODEX_AUDIT_FACTUEL_20261022.md`, `CODEX_PLAN_TECHNIQUE_20261022.md`, `PROMPT_DEMARRAGE_CODEX.txt`. Si un `AGENTS.md` existe déjà, **ne l'écrase pas** : compare/merge les instructions.
3. Installe l'**extension officielle Codex** de l'éditeur VS Code si nécessaire (recherche « Codex » publié par OpenAI dans Extensions). Connecte-toi avec ton compte ChatGPT. Vérifie que Codex voit l'espace de travail local ouvert.
4. Dans le chat Codex, copie le texte complet de `PROMPT_DEMARRAGE_CODEX.txt`, puis envoie-le. `AGENTS.md` est un fichier de consignes reconnu automatiquement dans les workflows Codex; le prompt demande aussi explicitement de le lire.
5. Examine son premier **rapport sans modifications**. Ne lui autorise pas encore l'exécution en réseau ni la modification de fichiers; demande-lui d'expliquer ce qu'il souhaite changer.
6. Une fois la correction P0 envisagée clairement définie, tu pourras autoriser **uniquement ce changement ciblé**, puis les tests sur une copie ou dans un environnement de test préservant ta base historique.

## Sécurité de la base et des secrets

- Ne place aucune clé API, seed phrase, secret ou `.env` dans le chat Codex. Le ZIP d'export précédent excluait les noms connus, mais le projet réel peut avoir des secrets dans d'autres fichiers.
- Ne transmets pas la base `rugger_bot.db` si Codex peut travailler sur le code et sur une base de test en mémoire. Toute analyse de l'ancienne DB doit être explicite, avec une ouverture strictement en lecture seule et sans affichage de wallets.
- N'extrais pas un ZIP antérieur de correctifs en écrasant ton dossier actuel. Conserve une sauvegarde de `rugger_bot_v1`.

## Premières commandes utiles (à n'exécuter qu'après consentement)

Depuis le dossier `rugger_bot_v1`, pour lire les noms de fichiers :

```powershell
Get-ChildItem .\bot\analyser\paper*.py
Get-ChildItem .\tests\test_research_pipeline.py
```

Pour les tests après autorisation et sauvegarde :

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/tests
```

Cette commande exécute des tests locaux et peut écrire des caches sur le disque. Ne lancer aucun `.bat` de simulation marché durant l'audit.

## Suite

La prochaine première correction n'est pas le scoring. C'est la fiabilité comptable du moteur PAPER et le test incohérent `test_paper_entry_limits`, avec un protocole de test déterministe. La qualité des données, puis la stratégie, viennent ensuite.

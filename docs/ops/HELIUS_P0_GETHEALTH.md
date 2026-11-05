# Helius P0 : test minimal de la clé renouvelée (`getHealth`, une requête)

Workflow : `.github/workflows/helius-p0-gethealth-once.yml`. Tests hors réseau : `tests/test_helius_p0_gethealth_workflow.py`. Registre : T-REG T-0036, audit de RUGGER 02.

**Ce test ne s'exécute qu'après l'audit PASS de RUGGER 02 et l'autorisation explicite du propriétaire.** Préparer ce test n'autorise aucun autre appel Helius.

## 1. Ce que fait le workflow

- **Déclenchement** : manuel seulement (`workflow_dispatch`). Il faut saisir la phrase `HELIUS-P0-GETHEALTH-ONCE`, sinon le job est ignoré.
- **Requête** : une seule requête JSON-RPC `POST` vers `https://mainnet.helius-rpc.com/` :
  - corps : `{"jsonrpc":"2.0","id":1,"method":"getHealth"}` ;
  - délai maximal de 10 s, sans nouvel essai, sans suivre de redirection, sans proxy ;
  - certificat TLS vérifié (comportement par défaut de Python).
- **Résultat** :
  - **PASS** seulement si la réponse est HTTP 200 avec le JSON `{"jsonrpc":"2.0","id":1,"result":"ok"}` ;
  - sinon **FAIL**, avec un motif court : `key_missing_or_malformed`, `http_status`, `transport_error`, `response_too_large`, `not_json`, `bad_envelope`, `rpc_error` ou `unexpected_result`.
- **Sortie** :
  - une ligne `HELIUS_P0_GETHEALTH=PASS|FAIL …` dans le journal et dans le résumé du job ;
  - job vert pour PASS, rouge pour FAIL.

## 2. Garanties vérifiées hors ligne

| Garantie | Comment |
|---|---|
| Une seule requête, et seulement `getHealth` | le code n'a ni boucle, ni nouvel essai, ni autre méthode ; un test compte les appels |
| Aucune transaction ni signature | aucune clé de wallet, aucun `sendTransaction`, aucune signature |
| Pas de collecte prolongée | job limité à 2 min, étape à 1 min, requête à 10 s ; concurrence limitée à une exécution |
| Pas de dépense volontaire | une seule requête RPC standard par exécution, aucun achat |
| Règles du Master intactes | aucun code du dépôt n'est exécuté (pas de checkout), aucun fichier n'est écrit dans le dépôt |
| Clé jamais affichée | elle n'est lue que depuis l'environnement de l'étape. Ni la clé, ni l'URL qui la contient, ni les messages d'exception ne sont imprimés : seuls le type d'erreur ou le code HTTP le sont. GitHub masque aussi le secret dans les journaux |
| Clé mal formée refusée sans requête | la clé doit avoir 20 à 64 caractères `[A-Za-z0-9-]`, ce qui empêche toute injection dans l'URL |
| Permissions nulles | `permissions: {}` : le jeton GitHub n'a aucun droit |
| Aucune action tierce, aucun artifact | aucun `uses:`, aucun envoi de fichiers |

Les tests extraient le script du fichier du workflow : ils vérifient exactement les lignes que GitHub exécutera. 10 mutations ciblées sont détectées.

## 3. Autoriser le test, après le PASS de RUGGER 02

GitHub ne permet de lancer un workflow manuel que si son fichier existe sur la **branche par défaut** (`main`). Or aujourd'hui, `main` (`d9b950e`) ne contient que `paper-terminal-ci.yml`. Deux voies existent.

**Voie A, recommandée et documentée par GitHub :**
1. Le propriétaire autorise explicitement l'ajout d'**un seul fichier** sur `main` : `.github/workflows/helius-p0-gethealth-once.yml`, identique à celui de la PR. Rien d'autre n'est fusionné.
   - Le workflow est autonome : sans checkout, il n'a besoin d'aucun autre fichier.
   - Effet de bord : le commit sur `main` lance la CI hors ligne `paper-terminal-ci.yml` (déclencheur `push` sur `main`), sans secret ni appel fournisseur.
2. Dans l'onglet **Actions**, choisir « Helius P0 getHealth (one read-only request, manual) », puis **Run workflow** :
   - branche `main` ;
   - champ `confirm` = `HELIUS-P0-GETHEALTH-ONCE`.
3. Lire le résultat dans le résumé du job, puis le transmettre à RUGGER 01 (§4).
4. Désactiver le workflow aussitôt après (Actions, workflow, menu « ⋯ », **Disable workflow**) ou retirer le fichier de `main` (§5).

**Voie B, sans toucher `main`, non garantie :**

```bash
gh workflow run helius-p0-gethealth-once.yml --ref claude/r01-helius-p0-gethealth -f confirm=HELIUS-P0-GETHEALTH-ONCE
```

GitHub refuse en général cette commande tant que le fichier n'existe pas sur la branche par défaut. Elle n'a pas été essayée, car l'essayer reviendrait à lancer le test.

## 4. Lire le résultat

| Sortie | Interprétation |
|---|---|
| `PASS result=ok http=200` | la clé est acceptée par Helius pour une requête RPC standard |
| `FAIL reason=key_missing_or_malformed requests=0` | le secret est absent ou n'a pas le format attendu ; **aucune requête envoyée** |
| `FAIL reason=http_status status=401` ou `403` | la clé est refusée par Helius |
| `FAIL reason=http_status status=429` | limite de débit atteinte ; ne pas relancer en boucle |
| `FAIL reason=transport_error type=…` | réseau ou délai dépassé ; aucune conclusion sur la clé |
| `FAIL reason=rpc_error code=…` | Helius répond, mais le nœud signale une erreur (par exemple en retard) ; la clé est probablement acceptée, à confirmer |

## 5. Retour arrière

- **Avant toute exécution** : fermer la PR et supprimer la branche. Rien n'a été envoyé.
- **Après l'ajout sur `main`** : désactiver le workflow dans l'onglet Actions, ou annuler le commit qui ajoute le fichier. Aucun autre fichier n'est concerné.
- **En cas de doute sur la clé** : la renouveler dans le tableau de bord Helius, puis mettre à jour le secret `HELIUS_API_KEY`. Le journal d'exécution peut être supprimé dans l'onglet Actions. Le dépôt étant public, ce journal est public : il ne contient que la ligne PASS/FAIL.

## 6. Risques résiduels

1. **Exposition du secret** : le secret est fourni à l'étape. Tout code de cette étape pourrait le lire. La réduction du risque : script court et audité, sans checkout, sans action tierce, sur un runner hébergé par GitHub.
2. **Portée du PASS** : un PASS prouve que la clé est acceptée **si Helius refuse les clés invalides** (réponse 401 attendue). Cela n'a pas pu être vérifié hors ligne. Un PASS ne prouve rien sur les quotas, les méthodes plus lourdes ou les WebSockets.
3. **Phrase de confirmation** : elle évite un lancement accidentel, mais ce n'est pas un secret. Toute personne qui a le droit d'écriture sur le dépôt peut lancer le workflow. Chaque exécution envoie au plus une requête.
4. **Constat sur l'existant** : 19 des 23 workflows qui utilisent `HELIUS_API_KEY` dans la consolidation lancent réellement leur job lors d'un déclenchement manuel. Leur condition `if:` accepte `workflow_dispatch`, et la plupart font plusieurs requêtes. Aujourd'hui, ils ne sont pas déclenchables, car aucun n'est sur `main`. **Une future fusion de la consolidation (#101) dans `main` les rendrait déclenchables** : il faut les restreindre avant une telle fusion.
5. **Journaux publics** : le dépôt est public, donc le journal d'exécution est public. Il ne contient que la ligne de résultat.

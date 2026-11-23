# cpmmpilot 0.2 — transport réel `LiveRpc`, VERROUILLÉ (R03)

Ce transport est écrit et audité sous la note R02 fb28705b8b28acaec91678210d81c90bf4d0bfb3dbbafd852fd2b066bcabdd59, qui lève l'ordre pour l'écriture et l'audit seulement. Aucune exécution réelle n'aura lieu avant que les textes A, B et C du propriétaire (v1.3, 443bbfb9) soient écrits dans la session R03 et vérifiés à la source par R02.

Le reste de la chaîne est INCHANGÉ par rapport à 0.1.6 (PASS R02 3b28ff5e) : `step1.py`, `u2.py`, `step0.py`, `budget.py`, `layout.py`, `store.py`, `fixtures.py` et `rehearse.py`. Seuls `rpc.py`, les tests et le runner de mutants changent.

## Conditions de R02 et leur mise en œuvre (`rpc.py`)

1. **Refus d'ouverture sans autorisation ancrée.** `LiveRpc(endpoint, *, authorization_file, timeout_s=60)` calcule le sha256 du FICHIER d'autorisation et refuse de s'ouvrir s'il n'appartient pas à `AUTHORIZED_TEXT_SHA256`.
   - Cet ensemble est VIDE en 0.2. Aucun appel réseau n'est donc possible avec cette version, quel que soit l'appelant. Un test vérifie que l'ensemble est vide, et un mutant aussi.
   - Seule une version ultérieure, auditée par R02, y ajoutera le sha qu'il aura ancré après les textes du propriétaire. L'ensemble n'est jamais modifié pendant l'exécution.
2. **Aucun hôte ni aucune clé n'est lu par le code** : ni variable d'environnement, ni fichier, ni `.env`. Un test l'établit sur l'AST de `rpc.py` (`environ`, `getenv`, `dotenv`, `.env`, `helius`, `api-key`, `api_key`, `os` absents du code).
   - L'adresse du serveur est un argument explicite. Elle est refusée si elle n'est pas en https ou si elle contient des identifiants, une chaîne de requête, un fragment, ou un chemin avec `key`, `token` ou `secret`.
   - La clé est injectée par le proxy de l'environnement. `repr()` n'affiche jamais l'adresse.
3. **Pas de nouvelle tentative dans le transport.** Chaque tentative est débitée par `Client` AVANT l'envoi. Une erreur arrête, puis la reprise passe par `STATE.json`.
4. **Erreurs typées, qui ne reprennent jamais l'adresse ni le message du fournisseur.** Le message est seulement haché (12 caractères), et la chaîne `__cause__` est coupée.

   | Situation | Erreur levée |
   |---|---|
   | HTTP 429 | `rate_limited_429` |
   | HTTP 401 / 403 | `unauthorized_*` |
   | Autre code HTTP | `http_<code>` |
   | Réseau | `network_error` |
   | JSON illisible | `response_truncated` |
   | Mauvais id | `response_id_mismatch` |
   | Pas de `result` | `response_without_result` |
   | −32601, ou message « plan / upgrade / not available / not supported / paid » | `MethodRefused` (GTFA refusée = STOP sans repli, texte B(b)) |
   | Autre erreur RPC | `rpc_error` |

5. **Méthodes et taille bornées.** Seules les 6 méthodes tarifées (`PILOT_METHODS` = `budget.COSTS`, testé) sont acceptées. La réponse est bornée à 256 Mio.
6. **Tests hors ligne** (`unshare -rn`). La connexion est remplacée par une fausse connexion injectée : aucun socket n'est ouvert. Un test fait tourner U-2 de bout en bout à travers `LiveRpc` et la fausse chaîne, avec un refus GTFA : on obtient un STOP sans repli.

## Vérifications (avec g1ind 0.6.1 f31269e)

- 34 tests sur 34 passent.
- 49 mutants sur 49 sont tués (`MUTATIONS_cpmmpilot_v0_2.json`), dont 15 nouveaux mutants du transport.
- La répétition synthétique est inchangée (FakeChain).

## Liste V-1′

Aucune nouvelle liste n'est préparée. D'après la note R02 fb28705b, la liste existe déjà :
- protocole v1.2 (a3a285a1) § 7 ;
- collecte du 10/11, MANIFEST 8895cbee ancré ;
- a12 : 80 sur 80.

La décision de réputer l'étape 0 satisfaite revient au propriétaire.

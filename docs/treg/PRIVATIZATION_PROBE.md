# PROBE-PRIV — préparation à la privatisation de `laurentmaxence13-svg/rugger_bot_v1`

Préparé le 2026-11-04 par RUGGER 01, coordinateur PROBE-PRIV (mandat du
propriétaire). **Aucune modification de visibilité. Aucun dépôt créé.**
Privatisation **non prête** : les accès de tous les agents, RUGGER 04 compris,
ne sont pas validés.

## 1. Faits vérifiés

| Fait | Preuve |
|---|---|
| Le dépôt est **public** | API GitHub `repos/laurentmaxence13-svg/rugger_bot_v1` : `private: false`, `visibility: public` (2026-11-04). Les anciennes notes T-REG disant « privé » étaient fausses ; elles sont corrigées |
| Les conteneurs Claude Code Cloud ajoutent un jeton GitHub aux requêtes sortantes | un `curl` sans en-tête vers `api.github.com` reçoit `X-Oauth-Client-Id` et une limite de débit de 15000 : la requête est **authentifiée par le proxy**. Un test de lecture anonyme y est donc impossible : il faut un navigateur non connecté ou une autre machine |
| Aucun code exécuté ne lit GitHub anonymement | recherche sur `main` @ `d9b950e`, #101 @ `16f1f22` et Census @ `25a9f59`. On trouve des liens de documentation, des URL `raw.githubusercontent.com` de dépôts **tiers** publics (solana-program, raydium-io), et un workflow qui télécharge des artefacts avec `GITHUB_TOKEN` en en-tête |
| Aucun fichier de déploiement dans le dépôt | ni `render.yaml`, ni `vercel.json`, ni `Dockerfile` : Render et Vercel sont configurés dans leurs propres tableaux de bord |

## 2. Dépendances à la visibilité publique (inventaire)

| Dépendance | Effet d'une privatisation | Vérification |
|---|---|---|
| Sessions Claude Code R01, R02, R03 | lecture et écriture via l'application GitHub Claude, si son installation couvre le dépôt privé | **à tester** sur un dépôt privé de test (§3) |
| RUGGER 04 (claude.ai) | fonctionne s'il lit via un connecteur GitHub authentifié ; **cesse** s'il lit les pages publiques de façon anonyme | **à tester** : mode de lecture inconnu |
| Render (service « Master » et état) | le déploiement depuis GitHub demande que l'application GitHub de Render ait accès au dépôt privé | à vérifier par le propriétaire dans Render |
| Vercel (`rugger-wallet-master.vercel.app`) | idem avec l'application GitHub de Vercel | à vérifier par le propriétaire dans Vercel |
| Codex ou autres outils (historique) | doivent avoir un accès authentifié | à vérifier si encore utilisés |
| GitHub Actions (3 workflows automatiques et environ 49 manuels) | sur un dépôt **privé**, les minutes Actions sont décomptées du quota du compte (offre gratuite limitée). Au-delà, les tâches sont bloquées, ou facturées si une limite de dépense est fixée | le propriétaire doit vérifier son offre et sa consommation. **Risque de coût : décision du propriétaire** |
| Fonctions de sécurité gratuites des dépôts publics | sur l'offre gratuite, un dépôt privé perd notamment l'analyse de secrets avec blocage des pushes et les règles de protection de branche (fonctions payantes en privé) | le propriétaire doit vérifier son offre |
| Liens publics (PR, exécutions, artefacts) cités dans les documents et le tableau de bord | deviennent inaccessibles aux visiteurs non connectés | sans effet sur les agents authentifiés |
| 114 artefacts Helius publics (#113) | la privatisation coupe leur lecture publique, mais n'efface ni ce qui a déjà été téléchargé ni l'historique | la rotation de la clé reste la mesure de fond (#113) |

## 3. Protocole du dépôt privé de test (préparé, **non créé**)

Le propriétaire seul crée le dépôt : RUGGER 01 ne crée aucun dépôt.

1. **Création par le propriétaire** d'un dépôt **privé** `rugger_priv_probe`,
   contenant :
   - un fichier `NONCE.txt` avec une valeur aléatoire choisie par lui ;
   - une issue n° 1 avec un commentaire contenant une deuxième valeur.

   Aucune donnée réelle ni aucun secret.
2. **Accès accordés par le propriétaire.** L'application GitHub Claude doit
   avoir accès à ce dépôt, ainsi que le connecteur GitHub de claude.ai pour
   RUGGER 04. Render et Vercel ne sont pas concernés à ce stade.
3. **Ajout du dépôt aux sessions** R01, R02 et R03 (`add_repo`, accès en lecture).
4. **Sonde PROBE-PRIV-T, une par agent, chacun dans sa session.** Chaque agent
   lit les deux valeurs (fichier par git et par l'API, commentaire de l'issue).
   Il rapporte `PASS` / `FAIL` / `INSUFFICIENT EVIDENCE` avec les valeurs lues
   et l'heure UTC. RUGGER 04 fait de même par son connecteur, au niveau A ou B
   de `R04_PROCEDURE.md`.
5. **Contrôle négatif par le propriétaire.** Dans une fenêtre de navigation
   privée, `https://github.com/laurentmaxence13-svg/rugger_priv_probe` doit
   renvoyer une erreur 404. Cela prouve que le dépôt est réellement privé.
   Les conteneurs Claude ne peuvent pas faire ce test (§1).
6. **Contrôle indépendant** des réponses par RUGGER 02 : les valeurs lues
   doivent être identiques aux valeurs réelles.
7. **Critères de « privatisation prête »** :
   - toutes les sondes `PASS`, **RUGGER 04 compris** ;
   - accès de Render et de Vercel confirmés par le propriétaire ;
   - consommation Actions et perte des fonctions de sécurité gratuites acceptées
     par le propriétaire ;
   - plan de retour arrière prêt : le propriétaire peut remettre le dépôt en
     public.
8. **Nettoyage** : le propriétaire supprime ou archive `rugger_priv_probe` après
   la décision.

## 4. Paquet de supervision pour RUGGER 04 (conception, non construit)

Objectif : RUGGER 04 vérifie tout depuis le dépôt, public ou privé, avec un
minimum de lectures et sans relais humain.

| Élément | Contenu | Rôle |
|---|---|---|
| Point d'entrée | corps de l'issue #103 : tableau de bord courant et bloc `treg-heads` | état résumé, vérifiable |
| Procédures | `docs/treg/R04_PROCEDURE.md`, `R04_SUPERVISION.md`, `PRIVATIZATION_PROBE.md` | quoi lire, comment conclure |
| Outil | `tools/treg.py` sur `claude/r01-treg`, un seul fichier, bibliothèque standard ; SHA-256 publié dans chaque rapport | `r04-verify`, `supervise` |
| Politique de rejeu | `docs/treg/runs/<dernière exécution>.policy.json` | règles identiques à la base, sans la pause |
| Instantané (à ajouter) | `docs/treg/state/registry.json` (tous les événements) et son SHA-256 cité dans le bloc `treg-heads` | vérification **rapide** : rejeu complet à partir d'un seul fichier, au lieu de dizaines d'issues |
| Journal des notifications | blocs `treg-notify` dans #103 | ce qui a déjà été signalé au propriétaire |

Deux niveaux de vérification :
- **Rapide** : rejeu de l'instantané, en recalculant chaque digest, chaque
  chaîne et chaque règle. Puis comparaison avec le bloc `treg-heads` de #103 et
  le SHA-256 de l'instantané. Un instantané falsifié de façon cohérente avec
  #103 resterait possible : d'où le contrôle complet.
- **Complet** : `r04-verify` sur toutes les issues `[T-REG]`. Il faut le faire
  au moins une fois par rapport final, et chaque fois que le niveau rapide
  diverge.

Le paquet reste en lecture seule. R04-cloud (voir `R04_SUPERVISION.md`) écrirait
seulement ses blocs `treg-notify`.

# PROBE-PRIV — préparation à la privatisation de `laurentmaxence13-svg/rugger_bot_v1`

Préparé le 2026-11-04 par RUGGER 01, coordinateur PROBE-PRIV (mandat du
propriétaire). **Aucune modification de visibilité. Aucun dépôt créé.** Les sondes de R01,
R02 (T-0010, #114) et R03 (T-0011, #115) sont intégrées ; RUGGER 04 n'a pas
été sondé (voir #103).
Privatisation **non prête** : les accès de tous les agents, RUGGER 04 compris,
ne sont pas validés.

## 1. Faits vérifiés

| Fait | Preuve |
|---|---|
| Le dépôt est **public** | API GitHub `repos/laurentmaxence13-svg/rugger_bot_v1` : `private: false`, `visibility: public` (2026-11-04). Les anciennes notes T-REG disant « privé » étaient fausses ; elles sont corrigées |
| Les conteneurs Claude Code Cloud ajoutent un jeton GitHub aux requêtes sortantes | un `curl` sans en-tête vers `api.github.com` reçoit `X-Oauth-Client-Id` et une limite de débit de 15000 : la requête est **authentifiée par le proxy**. Un test de lecture anonyme y est donc impossible : il faut un navigateur non connecté ou une autre machine |
| Aucun code exécuté ne lit GitHub anonymement | recherche sur `main` @ `d9b950e`, #101 @ `16f1f22` et Census @ `25a9f59`. On trouve des liens de documentation, des URL `raw.githubusercontent.com` de dépôts **tiers** publics (solana-program, raydium-io), et un workflow qui télécharge des artefacts avec `GITHUB_TOKEN` en en-tête |
| Aucun fichier de déploiement dans le dépôt | ni `render.yaml`, ni `vercel.json`, ni `Dockerfile` : Render et Vercel sont configurés dans leurs propres tableaux de bord. **Ajout de R02** : `streamlit_app.py` et `.streamlit/config.toml` (sur `main`, #101, Census et `claude/r01-treg`) indiquent un déploiement **Streamlit Community Cloud** |
| Forks, étoiles, Pages (R02) | `forks_count` = 0, aucun fork public ne survivrait à une privatisation ; 0 étoile, 0 observateur, pas de GitHub Pages |
| Protections actives aujourd'hui (R02) | analyse de secrets, blocage des pushes, motifs non liés à un fournisseur, contrôles de validité et mises à jour de sécurité Dependabot : **toutes désactivées**. `main` n'est pas protégé et il y a 0 ruleset |
| Droits des agents (R02) | le jeton des sessions d'agents dispose des droits **administrateur** sur le dépôt. Seules la politique et les filtres du proxy retiennent les agents : un agent pourrait techniquement changer la visibilité ou les réglages. La règle « aucune modification de visibilité » est donc déclarative |
| Données déjà publiques (R02) | une privatisation ne retire pas ce qui a déjà été publié : environ 916 journaux d'exécution, 114 artefacts, les issues T-REG et l'historique git restent potentiellement copiés |

## 2. Dépendances à la visibilité publique (inventaire)

| Dépendance | Effet d'une privatisation | Vérification |
|---|---|---|
| Sessions Claude Code R01, R02, R03 | lecture et écriture via l'application GitHub Claude, si son installation couvre le dépôt privé | **à tester** sur un dépôt privé de test (§3) |
| RUGGER 04 (session Claude Code Cloud depuis le 2026-11-04) | même canal authentifié que R01, R02 et R03 | **validé selon le propriétaire** : lecture du dépôt privé de test et du registre |
| Streamlit Community Cloud (ajout de R02) | l'application déployée doit avoir accès au dépôt privé | à vérifier par le propriétaire dans Streamlit |
| Render (service « Master » et état) | le déploiement depuis GitHub demande que l'application GitHub de Render ait accès au dépôt privé | à vérifier par le propriétaire dans Render |
| Vercel (`rugger-wallet-master.vercel.app`) | idem avec l'application GitHub de Vercel | à vérifier par le propriétaire dans Vercel |
| Codex ou autres outils (historique) | doivent avoir un accès authentifié | à vérifier si encore utilisés |
| GitHub Actions (3 workflows automatiques et environ 49 manuels ; selon R03, 23 sur 52 téléversent ou téléchargent des artefacts) | sur un dépôt **privé**, les minutes Actions sont décomptées du quota du compte (offre gratuite limitée). Au-delà, les tâches sont bloquées, ou facturées si une limite de dépense est fixée | le propriétaire doit vérifier son offre et sa consommation. **Risque de coût : décision du propriétaire** |
| Fonctions de sécurité (correction de R02) | **aucune n'est activée aujourd'hui**, donc une privatisation ne ferait rien perdre de ce qui fonctionne. La mesure utile est d'**activer dès maintenant**, tant que le dépôt est public et que c'est gratuit, l'analyse de secrets et le blocage des pushes. En privé, sur l'offre gratuite, ces fonctions seraient payantes | décision et action du propriétaire : c'est une modification des protections du dépôt |
| Preuves conservées seulement dans des artefacts Actions (R03) | 12 fichiers de validation citent 26 exécutions Actions comme provenance. Elles deviendraient non publiques, et leurs artefacts expirent de toute façon à la fin de la rétention | archiver dans le dépôt, avec SHA-256, toute preuve dont on dépend |
| Liens publics (PR, exécutions, artefacts) cités dans les documents et le tableau de bord | deviennent inaccessibles aux visiteurs non connectés | sans effet sur les agents authentifiés |
| Outil T-REG, recensement (« census ») et certifications | ne lisent que le git local : **non affectés** (R03) | — |
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
   lit les deux valeurs (fichier par git et par l'API, commentaire de l'issue),
   et donne aussi le SHA-256 de `NONCE.txt` lu depuis le blob git et depuis
   l'API (suggestion de R03).
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

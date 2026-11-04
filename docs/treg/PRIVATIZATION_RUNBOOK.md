# Procédure de privatisation de `laurentmaxence13-svg/rugger_bot_v1` (préparée, NON exécutée)

Préparée le 2026-11-04 par RUGGER 01 (mission P-PRIV). **Seul le propriétaire
change la visibilité du dépôt.** Aucun agent ne le fait, aucun déploiement n'est
déclenché, aucun réglage ni aucune permission n'est modifié par cette procédure.

**Verdict à la date de rédaction : NOT READY TO PRIVATIZE** (voir §1 et §2).

## 1. Préconditions et état vérifié

| Précondition | Statut | Preuve | Action restante |
|---|---|---|---|
| Accès authentifié de R01, R02 et R03 à un dépôt privé | **PASS** | lecture indépendante de `rugger_priv_probe` (privé), empreintes identiques (T-0013 à T-0015, #117 à #119) | aucune |
| Accès de R04 | **PASS selon le propriétaire** | session Claude Code Cloud `session_016VkauFz4mBdySC1PoMsRCf` ; lecture du dépôt privé et du registre validée par le propriétaire | R04 confirme le tableau de bord après mise à jour (avis unique, `PROTOCOL.md` §9) |
| Registre T-REG à jour | **PASS (R01)** | relu en direct sur GitHub : 101 événements, 15 tâches, `registry_digest` `7cb26be74263661d75dca1887b1b62e60c41240db96e08922e11c000da37a67c` ; corps de #103 régénéré ; `r04-verify` = `CURRENT` | contrôle indépendant par R02 (T-0016) et par R04 |
| Render `rugger-master-readonly` | **INSUFFICIENT EVIDENCE** | branche `feat/render-readonly-master-service-20261101` (tête `5b0f4cc`), déploiement automatique désactivé, offre Free. Côté GitHub, aucune trace d'intégration Render : 0 déploiement, 0 statut | propriétaire : Render → service → Settings → *Repository*. Il doit voir « connecté via GitHub » (application GitHub de Render avec accès au dépôt), et non une « Public Git repository » |
| Vercel `rugger-wallet-master` | **INSUFFICIENT EVIDENCE** | aucun statut, check-run ni déploiement GitHub de Vercel sur `1f8035c`. D'après la note de passation du 2026-11-02, la production contient des fichiers absents du dépôt : elle n'est pas construite depuis GitHub | propriétaire : Vercel → projet → Settings → *Git*. Repérer le dépôt connecté ; s'il l'est, l'application GitHub de Vercel doit avoir accès au dépôt privé |
| Streamlit Community Cloud | **INSUFFICIENT EVIDENCE** | `streamlit_app.py` et `DEPLOYER_RUGGER_WALLET.md` décrivent un déploiement *à faire par le propriétaire* depuis `main`. Le dépôt ne contient aucune URL `*.streamlit.app` | propriétaire : share.streamlit.io → existe-t-il une application liée à ce dépôt ? Si oui, réautoriser Streamlit avec l'accès aux dépôts privés |
| Coûts GitHub Actions | **FAIL (risque)** | 55 workflows actifs. Entre le 29 octobre et le 3 novembre (6 jours d'activité) : 3560 exécutions, dont 3410 sur `pull_request`, soit environ **2960 minutes facturables estimées** (jobs Linux, échantillon de 240 exécutions). Facturation **inaccessible** aux agents (le proxy limite les sessions au dépôt) | propriétaire : Settings → Billing → offre, minutes incluses, limite de dépense Actions à 0 $. Puis réduire les déclencheurs (§5) |
| Permissions | **FAIL** | le jeton des agents a les droits **administrateur** sur `rugger_bot_v1` et `rugger_priv_probe`. Aucune restriction par session n'est disponible : tous les agents passent par l'application GitHub Claude, avec les droits du propriétaire | décision du propriétaire sur l'accès réellement limité à la lecture (§6) ; ne rien révoquer avant |
| Sécurité du dépôt | **PASS partiel** | historique scanné sans révéler de valeur (106 branches, 1138 commits, 10 motifs) : **0** occurrence, aucun fichier `.env` versionné, `.gitignore` couvre `.env`, `*.key` et `*keypair*.json`. Seul secret utilisé par les workflows : `HELIUS_API_KEY` | rotation de `HELIUS_API_KEY` (#113), puis activation de l'analyse de secrets et du blocage des pushes, gratuits tant que le dépôt est public |

## 2. Risques encore ouverts

1. **Coût et blocage d'Actions.** Sur un dépôt privé, le rythme observé épuiserait
   en quelques jours d'activité un quota mensuel modeste (sur l'offre gratuite,
   2000 minutes par mois selon la grille publique de GitHub, à confirmer pour ce
   compte). Ensuite, soit les jobs sont bloqués (limite de dépense à 0 $), soit
   ils sont facturés (limite plus élevée).
2. **Fournisseur.** 22 fichiers de workflows, présents sur environ 30 à 35 branches,
   se déclenchent sur `pull_request` avec `HELIUS_API_KEY`. Sur cette période,
   1116 exécutions portent un nom de workflow fournisseur, dont 359 réussies.
   Combien ont réellement appelé Helius n'est pas établi sans les journaux.
3. **Déploiements.** Render, Vercel et Streamlit peuvent perdre la capacité de
   reconstruire depuis GitHub. Rien ne prouve, de ce côté, qu'ils y soient
   connectés par une application GitHub autorisée.
4. **Droits élevés.** Les droits administrateur de tous les agents rendent la
   règle « R04 n'écrit jamais » purement déclarative.
5. **Données déjà publiques.** Environ 916 journaux, 114 artefacts, les issues et
   l'historique git ont pu être copiés. Une privatisation ne les retire pas. La
   rotation de `HELIUS_API_KEY` reste la mesure de fond.

## 3. Ordre exact des opérations (propriétaire)

1. **Sécurité, avant tout :**
   - faire tourner `HELIUS_API_KEY` chez Helius ;
   - mettre à jour le secret Actions, sans jamais coller la valeur dans une conversation ;
   - activer l'analyse de secrets et le blocage des pushes.
2. **Facturation :**
   - relever l'offre et les minutes incluses ;
   - vérifier que la limite de dépense Actions est **0 $**, sans aucun achat ni hausse de plafond.
3. **Déclencheurs Actions (§5)** :
   - désactiver dans l'onglet Actions les workflows fournisseur déclenchés sur PR ;
   - fermer les PR obsolètes (65 ouvertes).
4. **Render** : confirmer la connexion GitHub du service, ou la créer, **sans déployer**.
5. **Vercel** : confirmer le dépôt connecté et l'accès de l'application GitHub ; ou noter que la production est déployée hors Git.
6. **Streamlit** : confirmer l'existence ou l'absence d'une application ; si elle existe, accorder l'accès aux dépôts privés.
7. **Gel annoncé** : R01 publie un avis dans #103. Aucune tâche T-REG en cours ; les agents n'écrivent plus.
8. **Bascule** : Settings → General → Danger Zone → *Change visibility* → *Private*.
9. **Contrôles immédiats (§4)**, puis levée du gel.

## 4. Vérifications après la bascule

| Contrôle | Qui | Comment | Attendu |
|---|---|---|---|
| Accès anonyme | propriétaire | fenêtre de navigation privée : page du dépôt, une URL `raw.githubusercontent.com` et l'issue #103 | 404 partout. Les conteneurs Claude ne peuvent pas le tester : leur proxy authentifie toute requête |
| R01, R02, R03 | chaque agent, dans sa session | `git ls-remote`, lecture de `docs/treg/PROTOCOL.md` sur `claude/r01-treg`, lecture de #103 | PASS, journalisé dans une tâche T-REG |
| R04 | R04 | les mêmes lectures, puis `r04-verify` ; réponse `RUGGER04-VERIFY | …` par `send_message` | `CURRENT` (ou `STALE` sans anomalie d'intégrité) |
| Registre | R01, puis R02 | `r04-verify` sur toutes les issues `[T-REG]` relues | même `registry_digest` qu'avant la bascule |
| Render, Vercel, Streamlit | propriétaire | dans chaque tableau de bord : dépôt toujours connecté ; aucun déploiement déclenché | connexion intacte |
| Actions | propriétaire | page d'utilisation : décompte des minutes ; workflows fournisseur désactivés | aucune exécution inattendue |

## 5. Contrôle des coûts GitHub Actions (préparé)

- **Principal consommateur** : « Rugger isolated LIVE / P3 regression », environ
  1249 minutes-exécution en 6 jours, 754 exécutions sur `pull_request` et `push`.
- **Déclencheurs à couper avant la bascule** (le propriétaire désactive le
  workflow dans l'onglet Actions ; c'est valable pour toutes les branches) :
  - `helius-launchlab-sampled-creations.yml`, `helius-active-launchlab-scan.yml`, `helius-active-launchlab-cohort.yml` ;
  - `helius-unsigned-cpmm-sell.yml`, `helius-s1-capacity-s2.yml`, `helius-ws-forward-paper.yml` ;
  - `cpmm-prospective-markout-readonly.yml`, `cross-provider-migrations-readonly.yml`, `public-holder-readonly.yml` ;
  - `sample-public-trade-receipts-readonly.yml`, `sample-Wsol-independent-legs-readonly.yml`, `solana-v1-pinned-mainnet.yml` ;
  - `master-prospective-evidence.yml`, `helius-prospective-campaign.yml`, `helius-pinned-root-diagnostic.yml` ;
  - `helius-pinned-index-creators.yml`, `helius-legacy-hints-crypto.yml`, `helius-historical-ed25519-replay.yml` ;
  - `helius-sol-forward-paper-cycle.yml`, `helius-signed-master-paper.yml`, `helius-rolling-signed-paper.yml`, `helius-recent-signed-sol-trades.yml`.
- **CI hors ligne à conserver** : `offline-tests.yml`, `rugger-isolated-ci.yml`
  et `paper-terminal-ci.yml`. Pour la suite : `concurrency` avec annulation, une
  seule version de Python par PR, `timeout-minutes` court.
- **Garde-fou financier** : limite de dépense à 0 $. Les jobs s'arrêtent à
  l'épuisement du quota, sans jamais rien facturer.

## 6. Accès réellement limité à la lecture (préparé, aucune révocation)

| Option | Lecture seule réelle | Coût | Limites |
|---|---|---|---|
| A. Statu quo : application GitHub Claude, avec règles déclaratives et audit | non (administrateur) | 0 | déjà fonctionnel ; toutes les écritures portent l'identité du propriétaire et ne sont pas attribuables |
| B. Jeton *fine-grained* en lecture seule (Contents, Issues et Metadata en lecture), créé par le propriétaire et stocké **uniquement** dans un environnement réservé à R04 | oui, pour les lectures faites avec ce jeton | 0 | R04 garde l'application GitHub Claude tant que son environnement donne accès au dépôt. Il faudrait un environnement R04 sans dépôt attaché ; à tester avant toute révocation |
| C. Organisation GitHub (gratuite) et compte machine R04 avec le rôle *Read* | oui | 0 | demande de transférer le dépôt et de revoir Render, Vercel et Streamlit. Un dépôt personnel ne permet pas de donner un rôle de lecture seule à un collaborateur |

Recommandation : garder A jusqu'à ce que B ait été **démontré** dans un
environnement R04 dédié, avec un test d'écriture qui doit échouer, fait par le
propriétaire. Aucun secret ne doit transiter par une conversation.

## 7. Retour arrière et limites

- Le propriétaire peut repasser le dépôt en public à tout moment : Settings →
  *Change visibility* → *Public*.
- **Limites :**
  - GitHub efface étoiles et observateurs lors d'une privatisation (0 aujourd'hui) ;
  - les minutes Actions consommées ne sont pas restituées ;
  - un retour en public réexpose tout le contenu, issues T-REG comprises ;
  - les données déjà copiées pendant la période publique restent dehors.

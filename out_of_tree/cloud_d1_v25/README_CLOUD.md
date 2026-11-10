# W1 — option cloud D1 : procédure (préparée, NON exécutée)

**Statut.** Texte et scripts seulement. Les étapes suivantes demandent chacune le GO explicite du propriétaire : création de la VM, transfert, URL signées, ouverture réseau, téléchargement des wheels. Calcul hors ligne (HISTORICAL_REPLAY). Aucun ordre, aucune signature, aucune clé de wallet.

## 1. Quand
- **Règle D1-a de R02.**
  - Si le nombre de signatures exportées (étape `export`) dépasse le seuil d'une étape, la suite passe sur le cloud.
  - Le seuil est la projection `memory_guard` avec la marge ×1,5 sur la marge mémoire du cgroup de R03 (environ 13,5 Go).
  - Pour evaluate, ce seuil est d'environ 160 000 signatures. Pour trials, il est d'environ 365 000.
  - Si le swap a été tenté, au plus 2 essais, puis on passe au cloud.
- **`start_step` vaut `evaluate`** si trials a réussi dans la session de R03, et **`trials`** sinon.
- **`start_step=none`** est la répétition à blanc : contrôle d'équivalence seulement, sans aucune donnée W1. À faire avant le 14/11 si le propriétaire donne son GO.

## 2. Ce que R03 dépose dans `inbound/`

**Transport (v2.1, B-3 de R02, question de R04)**

**(a) Qui génère l'accès, et avec quelle commande.** Le propriétaire, seul, dans Cloud Shell, au moment de chaque transfert.
- **VOIE UNIQUE (A), décision de R02 (95ef4e34, conditions K-1 à K-7)** : un jeton réduit (Credential Access Boundary).
  - `bash create_vm.sh token inbound` avant le dépôt, et `bash create_vm.sh token outbound` avant la récupération.
  - Le jeton vient du compte `w1-url-signer`, obtenu par impersonation et sans fichier de clé. Il est ensuite **réduit par CAB à un seul préfixe**.
  - Le propriétaire le saisit **dans le formulaire sécurisé de la session de R03**, avec l'hôte `storage.googleapis.com` et l'en-tête `Authorization: Bearer`.
  - Le proxy de R03 l'injecte dans chaque requête. Ni le propriétaire ni R03 ne le colle dans une conversation, et `r03_transfer.sh put|get` ne contient aucun secret.
- **Repli (B), seulement après une NOUVELLE décision de R02**, par exemple si la répétition à blanc prouve que la voie A échoue : des URL signées V4, une par objet.
  - Commandes : `bash create_vm.sh sign-inbound NAMES.txt` ou `sign-outbound`, puis `r03_transfer.sh upload|download`.
  - ⚠ Ces URL **passent en clair** jusqu'à R03, collées par le propriétaire dans sa conversation (point soulevé par R04). C'est acceptable seulement avec son accord explicite.

**Conditions K-1 à K-7 de R02 (décision 95ef4e34), texte exact**
- K-1 : un jeton par phase et par préfixe, jamais un jeton combinant inbound et outbound. Le jeton inbound n'est plus enregistré quand le jeton outbound est saisi.
- K-2 : jeton généré juste avant la phase. Le propriétaire le copie depuis Cloud Shell directement dans le formulaire sécurisé de R03, jamais dans une conversation, un fichier, GitHub ou une capture d'écran, puis efface le terminal (`clear`).
- K-3 : dès la fin de chaque phase, le propriétaire supprime le secret storage.googleapis.com des réglages de l'environnement, ce qui retire aussi l'accès réseau à cet hôte. R03 le confirme avec `get_environment` : aucun secret pour storage.googleapis.com (des noms, jamais des valeurs).
- K-4 : seul ce jeton réduit par CAB est admis dans le formulaire. Tout jeton non réduit (jeton OAuth du propriétaire, jeton brut d'un compte de service) est interdit.
- K-5 : R03 n'affiche jamais les en-têtes HTTP : ni `curl -v`, ni `--trace`, ni journal des en-têtes.
- K-6 : la répétition à blanc doit prouver PUT inbound/x avec le jeton inbound = 200 ; PUT hors de inbound/ = 403 ; GET inbound/x avec le jeton outbound = 403 ; liste du bucket = 403 ; GET outbound/x avec le jeton outbound = 200.
- K-7 : R01, R02 et R04 s'abstiennent de toute requête vers storage.googleapis.com tant qu'un secret est enregistré.

**(b) Durée et portée.**

| Accès | Durée | Portée |
|---|---|---|
| A inbound | ≤ 1 h (jeton d'impersonation) | rôle `objectCreator` (N-10), uniquement sur les objets `inbound/` de CE bucket : création seule, sans lecture ni liste |
| A outbound | ≤ 1 h | rôle `objectViewer`, uniquement sur `outbound/`. Un jeton CAB ne peut pas lister : `get` télécharge donc 6 noms fixes |
| B | 1 h | un seul objet, une seule méthode (PUT ou GET) |

- Dans tous les cas : aucun droit projet, aucun autre bucket, aucune clé permanente.
- **Après CHAQUE phase**, `inbound` puis `outbound`, sous les conditions K-1 à K-7 de R02 (95ef4e34) :
  - le propriétaire supprime le secret storage.googleapis.com des réglages de l'environnement de R03 ;
  - R03 confirme ensuite, avec `get_environment`, que ce secret ne figure plus dans l'environnement.
  - La phase suivante exige un nouveau jeton.

**Préparation.** `r03_transfer.sh prepare` construit ce répertoire ; il vérifie l'arbre aff97638, le registre f1f26e36 et le manifeste 63eb3412. Le téléchargement des wheels depuis PyPI se fait dans la session de R03, **au moment du GO**. La commande écrit aussi :
- `INBOUND_SHA256SUMS`, que R02 ancre ;
- `NAMES.txt`, la liste des objets à signer ;
- le `CODE_COMMIT` à passer en métadonnée.

| Fichier | Contenu | Contrôle |
|---|---|---|
| `w1code.bundle` | bundle git autonome du commit dont l'arbre est **aff97638** (R03 c0199a3) | la VM vérifie que `HEAD^{tree}` = aff97638 |
| `w1aux_v73.tar` | arbre **complet** w1aux v7.3 | sha du manifeste = **63eb3412** |
| `wheels/*.whl` | `requirements-dayj.txt`, versions exactes | sha256 dans les SUMS |
| `identity_check.py`, `IDENTITY_REFERENCE.json` | l'échantillon d'équivalence (§3) | sha256 dans les SUMS |
| `dayj_out.tar` | le répertoire dayj de R03 jusqu'à la dernière étape faite en session : `DAYJ_STATE.json`, `pools/`, la série, et le reste | dayj re-hache lui-même toutes les sorties antérieures |
| `p0_trials.jsonl` | registre P0 **f1f26e36** (N = 32) | sha256 dans les SUMS |
| `INBOUND_SHA256SUMS` | sha256 de tous les fichiers ci-dessus | **son propre sha est ancré par R02 et passé en métadonnée** |

Jamais déposés : `.env`, clés, URL d'endpoint, venv, P0 (holdout), checkpoints `.pkl`. Le tar exclut `checkpoint/` et `*.pkl`, et la VM s'arrête si elle en trouve.

**Contrôles de la VM avant toute exécution** (B-4)
- L'ensemble des fichiers présents doit être **exactement** celui listé dans les SUMS, plus les SUMS elles-mêmes. Aucun lien symbolique.
- `w1aux_v73.tar` ne contient que `w1aux/`.
- Aucun wheel ne fournit de module de premier niveau homonyme de `bot`, `w1aux`, `tests`, `sitecustomize`, `usercustomize` ou d'un module de la bibliothèque standard. Aucun `.pth`.
- Les listes de tar sont d'abord écrites dans un fichier : avec pipefail, `tar | grep -q` peut masquer un résultat positif (mesuré).

**Tests locaux, sans réseau ni GCP**
- `prepare`, avec un pip simulé et un commit de test à l'arbre aff97638 jamais poussé, alimente les contrôles de la VM : PASS. Le bundle importé redonne l'arbre aff97638, et le manifeste w1aux vaut 63eb3412.
- Cas refusés : fichier en trop, fichier altéré, `.pkl` dans le tar, tar w1aux hors de `w1aux/`, wheel qui masque `json`, wheel avec un `.pth`, lien symbolique.

## 3. Équivalence session ↔ cloud, avant toute donnée W1
1. **Identités dayj.** `identities()` doit être identique à celle de la session, sinon `code_identities_changed_between_steps`. Cela couvre :
   - CPython **3.12.3**, x86_64, Linux ;
   - l'arbre aff97638 sans modification ;
   - les empreintes gelées et les modules w1aux ;
   - le sha de dayj.py.

   Ubuntu 24.04 fournit CPython 3.12.3. ⚠ R03 doit confirmer que sa machine est bien en **x86_64**.
2. **`dayj selfcheck`**, lancé dans un répertoire séparé. Le SHA256SUMS attendu est **4aee76a3**.
3. **Échantillon `identity_check.py`** : pack gelé ×40, soit 6 920 signatures synthétiques. Il suit le même chemin que le jour J : trials lazy avec 4 processus et slim, puis evaluate (n_boot = 200), puis ledger. Référence mesurée chez R01, deux exécutions identiques :
   - `w1_report.json` : **44aaa9e3a6895c91a7e6630479120aa87f673c06fdfbabe05a17eeef0d8340dd**
   - `ledger.json` : **fd68eea7e1f8123994fda9644acde9a5fbf12dd410523ace17ab758fe8da6890**
   - SUMS des bundles : **ba14a5db7a66b277f59b9ddf2222bb9364b33e75496483300707aadef5044b72**

   **R03 doit retrouver les trois mêmes empreintes dans sa session** avant toute exécution cloud. La VM s'arrête au premier écart.
   - Durée : environ 3 min ici, avec 4 processus.
   - Ce n'est **pas** le 0e5cd4f0 de R03 (×40, autre script de mesure), et ce n'est pas non plus le 5d6c4533 (×60).

## 4. Enchaînement des étapes sur la VM — décision de R02 : **`chained` ACCEPTÉ** (C1 à C5, rapport 69584f45)
- **`anchored`** (variante, conforme à dayj) :
  - Après chaque étape, la VM dépose `DAYJ_STATE.json` dans `outbound/`.
  - Elle attend ensuite `anchors/expect_<étape>.txt`, que R03 dépose après l'ancrage par R02. L'attente maximale est de 3 h par étape.
  - Coût : du temps de VM inactive, plus une URL signée PUT pour chaque ancre (C5).
- **`chained`** (le mode retenu, par défaut dans `create_vm.sh`) : la VM passe le digest calculé de l'étape précédente comme `--expect-sha`.
  - Conditions de R02 :
    - C1 : INBOUND_SUMS_SHA et EXPECT_SHA sont ancrés avant la VM ;
    - C2 : une seule exécution par GO ; le journal et la console série sont conservés ;
    - C3 : vérification complète a posteriori ;
    - C4 : aucun `.pkl` ;
    - C5 : en mode anchored, ancres par URL signée PUT.
  - Si trials a déjà démarré en session (`trials_started` dans `DAYJ_STATE`), la VM ajoute `--resume` (B-2). dayj met alors en quarantaine la sortie partielle et reprend avec le même `registered_at`.
  - dayj continue de tout re-hacher, et vérifie à chaque étape les identités et S0.
  - R02 ancre **a posteriori** tous les digests avant toute utilisation. Aucune étape n'est irréversible et aucune ne décide hors evaluate_w1.
  - C'est un écart à « une étape = un ancrage préalable », **seulement si R02 l'accepte par écrit**.

## 5. Sorties (`outbound/`), puis retour
- **Fichiers déposés** :
  - `RUN_LOG.txt` ;
  - `DAYJ_STATE.json`, après chaque étape ;
  - `dayj_cloud_out.tar` : le répertoire dayj complet, checkpoint exclu, avec `metrics/metrics.json` ;
  - `RESULT.json` : les digests des étapes, l'identité, le sha du tar, `operational_trade=false`.
- **Retour** :
  - R03 télécharge le tout.
  - R02 vérifie les digests et l'égalité de `inputs_sha256` de metrics, puis fait le reçu à la main du premier cycle M1 clos.
- **Nettoyage.** La VM s'éteint à la fin du script et se supprime d'elle-même à 12 h. Le bucket se nettoie après 7 jours. Le §6 de `create_vm.sh` supprime le tout dès la vérification faite.

## 5 bis. (c) Fin de journée : suppression de la VM et du disque (O-1)
- **Commande unique**, dans Cloud Shell, une fois que R03 a téléchargé les sorties et que R02 a vérifié les empreintes : `bash create_vm.sh teardown`. Elle enchaîne :
  - `gcloud compute instances delete w1-eval --zone=us-central1-a --quiet` : la VM. Le disque de démarrage de 100 Go est supprimé avec elle, auto-delete étant actif par défaut.
  - `gcloud compute disks delete w1-eval --zone=us-central1-a --quiet` : le disque, s'il restait.
  - `gcloud storage rm -r gs://<bucket>/inbound gs://<bucket>/outbound gs://<bucket>/anchors` : les objets.
  - `gcloud iam service-accounts delete w1-eval-sa@<projet>.iam.gserviceaccount.com --quiet`, puis la même commande pour `w1-url-signer` : les deux comptes de service.
  - **Contrôle final** : `instances list` et `disks list` filtrés sur `w1-eval` doivent revenir vides, sinon STOP.
- **Rappel.** Une VM éteinte (TERMINATED) ne coûte plus de CPU, mais son disque reste facturé tant qu'il n'est pas supprimé. Le 12 h de `max-run-duration` ne compte que le temps de marche.

## 6. Sécurité (v2)
- **`create_vm.sh setup` vérifie** (O-2, O-4) :
  - le bucket : PAP `enforced`, accès uniforme, us-central1 ;
  - les deux comptes de service : **aucun** rôle projet et **aucune** clé utilisateur ;
  - **aucun Cloud NAT** dans la région.
- **Durée de vie.** Après `shutdown`, la VM est TERMINATED. Son disque de 100 Go est facturé jusqu'à `teardown`, puisque `max-run-duration` ne compte que le temps en marche (O-1).
- **Coût.** La sortie GCS est facturée environ 0,12 $/Go et entre dans le plafond de 20 $ (O-5).
- **Valeurs contrôlées.** `start_step`, `chain_mode` et `workers` passent par des `case` stricts (V-1).
- **Réseau** : pas d'IP publique. Accès privé aux API Google seulement, sans NAT ni Internet : pas de PyPI, pas d'apt, pas de RPC Solana.
- **Accès** : pas de clé SSH (`block-project-ssh-keys`, OS Login). VM protégée (Shielded VM).
- **Compte de service** : dédié, avec `storage.objectAdmin` sur **ce bucket seulement**. Aucun fichier de clé.
- **Données** : bucket privé, accès uniforme, `public-access-prevention`. Aucune donnée P0, aucun holdout.
- **Coût**, selon R04 :
  - environ 0,524 $/h HT ;
  - estimation : moins de 3 h de calcul, plus l'attente des ancres ;
  - plafond 20 $ TTC ; arrêt d'office à 12 h.

## 7. Points à vérifier pendant la répétition à blanc (`start_step=none`)
- `gcloud` est-il présent sur l'image Ubuntu fixée (snap google-cloud-cli) ?
- L'accès privé aux API Google fonctionne-t-il sans IP publique ?
- Les wheels se décompressent-ils avec `python3 -m zipfile` (pas de pip) ?
- Le selfcheck donne-t-il 4aee76a3, et l'échantillon donne-t-il les 3 empreintes ?
- Le jeton CAB (option A) est-il accepté par l'API JSON GCS ? Il faut tester un PUT dans `inbound/`, puis un PUT hors de `inbound/`, qui doit être **refusé** (403).

## 8. v2.2 — corrections de l'audit c87b86d6 de R02
- **N-1** : l'égalité des ensembles de fichiers exclut seulement `./INBOUND_SHA256SUMS` (`-path`), dans `startup.sh` comme dans `prepare`. Test : un `wheels/INBOUND_SHA256SUMS` ajouté donne STOP.
- **N-2** : `RUN_STARTED` est écrit sur le disque de la VM. Un redémarrage donne `STOP second_boot_refused`, puis l'arrêt de la VM. Test : 1er démarrage autorisé, 2e refusé.
- **(d)** `prepare` cherche des motifs de secret dans `dayj_out.tar` : clé d'API, `?key=`, URL Helius avec paramètre, clé privée, `.env`. Les membres `.gz` sont décompressés. Seul le nom du membre est affiché, jamais la valeur. Toute correspondance donne STOP. Testé sur un tar propre puis sur un tar contenant une URL avec clé.
- **(e) / O-7** : `prepare` compare le sha256 de chaque wheel au digest publié par l'API JSON de PyPI, pour la version épinglée, dans le même GO que le téléchargement. Une différence, ou un nombre de wheels différent du nombre de dépendances épinglées, donne STOP. Le relevé est écrit dans `<out>.pypi_digests.txt`, hors de `inbound/`, pour R02. Testé hors ligne avec un PyPI simulé (OK, puis MISMATCH).
- **N-3** : `case` sur le nom aussi dans `upload`.
- **N-4** : `--platform manylinux_2_28_x86_64` ajouté.
- **N-5** : les fichiers TSV d'URL sont supprimés après usage.
- **N-7** : `teardown` vérifie qu'il ne reste aucun objet dans le bucket.
- **Transport (B-3)** : R02 a décidé (95ef4e34) que la voie unique est le jeton CAB saisi par formulaire, aux conditions K-1 à K-7. Les URL signées ne servent qu'en repli, après une nouvelle décision de R02.

## 9. v2.3 — décision B-3 de R02 (95ef4e34)
- **N-9** : `put` envoie le fichier en flux (`--upload-file` avec `-X POST`) au lieu de `--data-binary`, qui chargeait tout le fichier en mémoire et exposait `dayj_out.tar` à un OOM. Vérifié contre un serveur HTTP local : méthode POST et corps de 1 000 octets transmis intégralement.
- **N-10** : le jeton `inbound` est réduit au rôle `roles/storage.objectCreator`.
- **N-11** : `subject_token` passe à STS par stdin (`--data-urlencode subject_token@-`), donc jamais dans argv. Vérifié localement : le corps reçu est bien `subject_token=…&options=…`.
- **Note de R03** : le `python3` système de sa session est en 3.13. `r03_transfer.sh` n'utilise `python3` que pour des contrôles et pour `pip download`, qui vise cp312. Le calcul W1 tourne toujours sous le venv 3.12.3, et sur la VM sous `/usr/bin/python3`, contrôlé en 3.12.3.
- **Identité session ↔ cloud** : R03 a reproduit les 3 empreintes de l'échantillon ×40 (44aaa9e3, fd68eea7, ba14a5db ; 3.12.3 x86_64), et R02 les a ancrées.

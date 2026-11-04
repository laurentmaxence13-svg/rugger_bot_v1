# Anciennes PR exposées : consolidation et neutralisation (plan, non exécuté)

Préparé le 2026-11-04 par RUGGER 01. Correction P-PRIV n° 1, PR #122. Rien n'a été
fermé, désactivé, étiqueté ni poussé sur ces PR. Ce plan ne s'exécute qu'après un
**PASS de RUGGER 02 sur #122** et l'**accord explicite du propriétaire**.

Données exactes : `docs/actions/legacy_prs.json`. Pour chaque PR, il donne :
- la tête et son SHA ;
- le groupe (A, A2 ou B) ;
- les commits absents de #101 ;
- les fichiers dont la version n'a jamais été présente dans #101 ;
- les workflows exposés.

## 1. Constat

40 PR ouvertes, toutes antérieures à la décision D3 (`63d7be9`), gardent dans leur
branche des workflows à déclenchement automatique : 51 fichiers au total, signalés par
`tools/workflow_trigger_guard.py`. Pour un événement `pull_request`, GitHub utilise
la version des workflows de la branche de la PR. Ni D3 ni #122 ne les protègent donc.

Référence : consolidation #101, `integration/consolidation-20261103` @ `16f1f22`.

| Groupe | PR | Critère | Travail hors #101 |
|---|---|---|---|
| **A** (32) | #39, #41, #42, #45 à #48, #50, #52 à #55, #65 à #74, #76 à #79, #81, #83 à #85, #88, #89 | la tête de la PR est un **ancêtre** de `16f1f22` (`git merge-base --is-ancestor`) | **aucun** : tous leurs commits sont dans #101. Les écarts de contenu viennent de modifications ultérieures dans #101 (D3, correctifs) |
| **A2** (1) | #56 | tête non ancêtre, mais **chaque** version de fichier de la PR apparaît dans l'historique de #101 (`git log --full-history`), puis a été remplacée | **aucun** : contenu intégré puis remplacé (par exemple `0efb212`, `1ffabd0`) |
| **B** (7) | #35, #40, #44, #49, #80, #82, #86 | au moins un fichier dont la version de la PR n'apparaît **jamais** dans l'historique de #101 | oui (détail §3) |

Correction du 2026-11-04 : #56 était d'abord classé B. RUGGER 02 (T-0020) a montré
que ses fichiers figurent dans l'historique de #101 : le premier calcul utilisait
l'historique simplifié de `git log`. Le calcul refait avec `--full-history`
confirme 7 PR B et les mêmes fichiers pour chacune.

Domaines couverts par le groupe A, déjà intégrés dans #101 :
- Helius : #52, #55, #65 à #73, #76 ;
- Bitquery : #54, #88 ;
- LaunchLab et CPMM : #45 à #48, #50, #77 à #79, #83 à #85, #89 ;
- Render : #65 à #74 ;
- Master : #53, #55, #81, #89.

## 2. Groupes A et A2 : neutralisation sans perte

Aucun travail n'est perdu en fermant ces 33 PR : leurs commits ou leurs contenus
sont dans #101. De plus :
- fermer une PR ne supprime pas sa branche ;
- l'opération ajoute un tag d'archive par tête (§4, étape 1).

Les branches Render, `feat/render-*` et `fix/render-*` (#65 à #74), restent intactes. Le
service Render suit sa propre branche, sans déploiement automatique selon le propriétaire.

## 3. Groupe B : travail à porter avant toute fermeture

| PR | Domaine | Fichiers jamais présents dans #101 | Action proposée |
|---|---|---|---|
| #35 | LIVE : épinglage des programmes, CPMM | `bot/live/rpc.py`, `bot/live/unsigned_preflight.py`, `tests/test_live_rpc.py` | revue du diff contre #101, puis portage des seuls gardes manquants ; aucun armement LIVE |
| #40 | LIVE : anti-double envoi RPC | `bot/live/rpc.py`, `tests/test_live_rpc.py` | remplacé par #44 (« intégration unique ») : vérifier, puis ne porter que #44 |
| #44 | LIVE : anti-double envoi, finalité, frais causaux | `bot/live/rpc.py`, `tests/test_live_rpc.py` | porter dans #101 après revue de R02 (chemin d'envoi LIVE, aucun armement) |
| #49 | Master : cycles économiques positifs | `bot/master_comparison.py`, `tests/test_master_positive_acquisition.py` | revue obligatoire contre les seuils protégés (50 cycles économiques qualifiés, 20 créateurs indépendants) : rien n'est porté si un seuil ou un libellé change |
| #80 | P3 : leads d'index SOL, créateur signé, RPC public | `bot/live/public_index_signed_creation.py`, `bot/live/public_sol_forward_paper.py`, `tests/test_public_index_signed_creation.py` et 2 workflows | porter avec des workflows en lancement manuel seulement |
| #82 | P3 : preuve Ed25519 par un second fournisseur (PublicNode) | `bot/live/publicnode_signed_sol_creation.py`, son test et 1 workflow | porter avec un workflow en lancement manuel seulement |
| #86 | Vercel : aperçu NO-GO du Master | `vercel/master-status-preview/**` (6 fichiers) et 1 workflow | porter dans #101. La branche reste la source du déploiement Vercel : ne pas la modifier |

Le portage se fera sur une branche dédiée, issue de #101 avec #122 :
- garde-fou vert ;
- suite complète réussie ;
- audit de RUGGER 02 ;
- aucune fusion sans accord.

## 4. Opération unique proposée (après PASS de R02 et accord du propriétaire)

0. **Contrôle préalable**, sans écriture. Relire les 40 têtes. Si un SHA diffère de
   `legacy_prs.json`, arrêter et recalculer.
1. **Archive**. Poser un tag `archive/pr-<N>` sur la tête exacte de chacune des 40 PR.
   Aucune branche n'est supprimée. Vérifié dans les 40 têtes : les seuls déclencheurs
   `push` (`paper-terminal-ci`, `program-pin-replay`, `read-only-cli-validation`,
   `rugger-isolated-ci`) n'ont qu'un filtre `branches`. Selon la règle GitHub des
   filtres, un push de tag ne les déclenche donc pas. Cette règle n'a pas pu être
   revérifiée dans la documentation depuis cet environnement.
2. **Groupes A et A2**. Fermer les 33 PR avec un commentaire unique : « contenue
   dans #101 (tête `<sha>` ancêtre de `16f1f22`, ou contenu intégré puis remplacé
   pour #56) ; branche et tag `archive/pr-<N>` conservés ». Vérifié dans les 40 têtes : aucun workflow n'a le
   type `closed` ni `pull_request_target`. Les types par défaut de `pull_request`
   (`opened`, `synchronize`, `reopened`) et `labeled` ne sont pas émis par une
   fermeture.
3. **Groupe B**. Après portage et audit (§3), fermer les 7 PR de la même façon.
   Entre-temps, elles restent exposées :
   - #35, #40, #44, #49 : seulement `program-pin-replay.yml` et
     `read-only-cli-validation.yml` ;
   - #80, #82, #86 : jusqu'à 45 workflows.
   Le seul levier immédiat est une désactivation temporaire de ces workflows par le
   propriétaire.
4. **Vérification**. Relancer `tools/workflow_trigger_guard.py` sur les têtes des PR
   encore ouvertes. Effet attendu : **0 PR ouverte** portant un déclencheur
   automatique hors CI.

Remarque de RUGGER 02 (T-0020) : 14 autres PR ouvertes (#34, #36 à #38, #90 à
#99) portent d'anciennes versions des CI automatiques. Leurs étapes ne figurent
pas dans `APPROVED_RUN_STEPS`, mais elles ne lancent que de la CI hors ligne, sans
fournisseur. Elles relèvent de la même consolidation, sans urgence de coût.

**Retour arrière** :
- rouvrir une PR (sa branche existe toujours) ;
- supprimer un tag d'archive (`git push origin :refs/tags/archive/pr-<N>`).

**Hors de cette opération** :
- aucune suppression de branche ;
- aucune désactivation de workflow par les agents ;
- aucune fusion dans `main` ;
- aucun déploiement ;
- aucune dépense.

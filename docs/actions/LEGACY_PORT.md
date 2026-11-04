# Portage des 7 anciennes PR du groupe B (opération 3 d'ACT-FIX)

Préparé le 2026-11-04 par RUGGER 01, sur autorisation du propriétaire (T-REG T-0023).
Branche isolée `claude/r01-legacy-port`, issue de la consolidation
`integration/consolidation-20261103` @ `6792ae18acf8a4dd872eca1b98ac778979bc2aa9` (#101,
après fusion de #122).

**Ni fusion de ce portage ni fermeture des 7 PR d'origine sans une nouvelle validation
du propriétaire.** Audit de RUGGER 02 requis.

## Résultat par PR

| PR | Domaine | Résultat | Commit sur la branche |
|---|---|---|---|
| #35 | LIVE : épinglage des programmes, préflight CPMM | **rien à porter** : contenu déjà dans #101, en version plus récente (§1) | aucun |
| #40 | LIVE : anti-double envoi RPC | **rien à porter** : garde et tests déjà dans #101 (§2) | aucun |
| #44 | LIVE : intégration unique anti-double envoi | **rien à porter** : diff identique à #40, déjà dans #101 (§2) | aucun |
| #49 | Comparateur Master : cycles positifs en entrée | **porté** (fusion sans conflit), revue des seuils au §3 | `9aeb386` |
| #80 | P3 : leads d'index SOL et créateur signé, RPC public | **porté** (fusion sans conflit) | `1edd08c` |
| #82 | P3 : preuve Ed25519 par un second fournisseur (PublicNode) | **porté** (fusion sans conflit) | `a93f1d7` |
| #86 | Vercel : aperçu NO-GO du Master en lecture seule | **porté** (fusion sans conflit) | `795cb9c` |

Chaque PR portée est fusionnée par `git merge --no-ff` de sa tête exacte : l'historique
et les auteurs d'origine sont conservés. Un dernier commit applique la règle D3 aux
workflows apportés (§4).

Après la fusion à 3 voies, les fichiers de chaque PR sont identiques à ceux de sa tête,
avec les exceptions suivantes (vérifiées par RUGGER 02, T-0024) :
- le bloc `on:` des 3 workflows passés en manuel (§4) ;
- `free-public-solana-forward-paper.yml`, qui reste dans sa version D3 de la base ;
- `bot/live/public_sol_forward_paper.py` : le changement de #80 (`getSignaturesForAddress` borné) y est appliqué à l'identique ; le reste de l'écart avec la tête de #80 (points d'accès PublicNode) vient de la base `6792ae1`, conservée par la fusion.

## 1. #35 : déjà contenue dans #101

Une fusion à blanc de la tête `b44bf4820d4b` sur `6792ae1` a donné le résultat suivant.

- **Fichiers sans conflit.** Les 22 fichiers de la PR sans conflit sont déjà identiques dans #101 : la fusion n'apporte aucun changement.
- **Code LIVE en conflit** (`bot/live/rpc.py`, `unsigned_preflight.py`, `cpmm_readiness.py`). Comparaison par définitions (AST) :
  - aucune fonction ni classe n'existe seulement dans #35 ;
  - les versions de #101 contiennent la logique de #35, plus des contrôles ajoutés depuis, par exemple les revérifications de fraîcheur `clock_ms` de `check_unsigned_order` ;
  - #35 n'apporte qu'une formulation de commentaire.
- **Tests en conflit** (`tests/test_live_rpc.py`, `tests/test_live_cpmm_rpc_integration.py`) :
  - #101 contient plus de définitions (fonctions et classes) : 41 contre 35 et 8 contre 7 ;
  - les écarts sont d'anciennes variantes des mêmes tests (fixture de signataire, horloge simulée).
- **Workflows** `program-pin-replay.yml` et `read-only-cli-validation.yml` : la seule différence est l'ancien déclencheur automatique (`push`, `pull_request`), retiré par D3.

## 2. #40 et #44 : déjà contenues dans #101

- **Code.** Les deux PR ont exactement le même diff sur `bot/live/rpc.py` : le refus de retransmettre les mêmes octets signés sur un transport. Ce refus est présent dans #101 (`HttpJsonRpcTransport.__call__`, `_attempted_submission_digests`), avec la même logique ; seul le commentaire est reformulé.
- **Tests.** Leurs 2 tests ajoutés sont **identiques à l'octet** dans #101 :
  - `test_transport_send_deduplicates_exact_signed_bytes_after_success` ;
  - `test_transport_concurrent_duplicate_send_is_claimed_before_first_await`.
  Aucun test de ces PR ne manque dans #101.

## 3. #49 : revue contre les seuils protégés

- **Changement.**
  - Avant : `evaluate_acquired_comparison` refusait toute acquisition P3 dont `qualified_economic_cycles` n'est pas 0.
  - Après : un entier positif ou nul est accepté et recopié dans `acquisition_reported_qualified_economic_cycles`.
- **Ce qui reste refusé ou marqué** :
  - `execution_verified` doit rester `False` ;
  - le résultat garde `acquisition_authentication_verified=False` ;
  - le commentaire précise que ce nombre ne prouve ni rentabilité, ni exécution, ni avantage validé.
- **Seuils protégés : non modifiés.**
  - `bot/master_decision.py` garde `min_qualified_cycles=50` et `min_creator_groups=20`.
  - `bot/p4/creator_disjoint_shadow_audit.py` garde `MIN_QUALIFIED_CYCLES=50`.
  - Ces fichiers ne sont pas touchés, et aucun libellé de recherche ou de DEX n'est requalifié en trade du Master.
- **À vérifier par RUGGER 02** : aucun consommateur ne doit traiter `acquisition_reported_qualified_economic_cycles` comme un nombre de cycles qualifiés du Master.

## 4. Workflows apportés : lancement manuel seulement (règle D3)

Trois workflows des PR portées se déclenchaient sur `pull_request` :
- `public-index-signed-creator.yml` (#80, sur label) ;
- `publicnode-signed-sol-corrob.yml` (#82) ;
- `vercel-master-status-preview-ci.yml` (#86, CI Node hors ligne).

Comme pour D3, leur bloc `on:` est remplacé par `workflow_dispatch:` ; les conditions `if:` des jobs sont conservées. Comme pour les workflows de D3, ces conditions font qu'un lancement manuel ne fait **rien** tant qu'elles ne sont pas adaptées, par décision séparée. Aucun appel fournisseur n'est donc possible depuis ces workflows.

#80 modifie aussi la condition `if:` de `free-public-solana-forward-paper.yml` (déjà manuel dans #101) : il la limite aux PR de la branche `feat/free-public-solana-signed-forward-paper-20261102`.

Garde-fou sur la branche : `workflows=55`, 3 automatiques, 52 manuels, 0 violation.

La CI de l'aperçu Vercel n'est plus automatique, car le garde-fou n'autorise que 3 CI automatiques. Ses tests Node (`node --check` sur les 2 fichiers, puis `node --test` : 7/7 réussis hors ligne) sont lancés à la main. Pour la rendre automatique, il faudra l'ajouter à `AUTOMATIC_WORKFLOWS` et à `APPROVED_RUN_STEPS` après revue.

## 5. Ce que ce portage ne fait pas

- Il ne fusionne pas dans la consolidation ni dans `main`, et ne ferme pas les 7 PR.
- Il ne modifie pas la branche source du déploiement Vercel (`feat/vercel-master-readonly-diagnostics-preview-20261102`), ni Render.
- Il ne lance aucun workflow, ne fait aucun appel fournisseur, ne déploie rien et n'engage aucune dépense.

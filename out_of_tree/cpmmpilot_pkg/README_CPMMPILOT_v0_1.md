# cpmmpilot 0.1 — runner du pilote CPMM (R03), HORS LIGNE uniquement

Ce runner est écrit par R03 sur décision de R04 (option 1, 23/11). Il s'appuie sur trois références :

- les textes du propriétaire rédigés par R02, v1.2 (5c6e8fc1) ;
- la méthode U-2 v0.2.1 (ebc9e45f) ;
- le plan de ressources (67e6cb78).

**La version 0.1 ne peut pas joindre le réseau.** `rpc.LiveRpc` lève une erreur dès sa construction, et seul `rpc.FakeChain` est utilisable : c'est une chaîne SYNTHÉTIQUE en mémoire.

Une version 0.2, auditée, ajoutera le transport HTTP. La clé y sera injectée par le proxy, et le transport ne sera utilisable qu'après la signature des textes par le propriétaire et la vérification de R02.

## Règles gelées réutilisées sans modification

- `cpmmx` 9ee6db9 :
  - décodeur, timeline et arithmétique `curve` ;
  - `CPMM_PROGRAM` importé, jamais retapé.
- `cpmmprereg` 0.2 : R-CP1 (`decisions`, `positions`, `placebo`, `trigger_count`).
- `cpmmb1` 0.1.1 : B1.
- `cpmmcost` 0.3 : coûts, `fees_from_amm_config`, `frozen_check`. `frozen_check` est appelé dans les fiches de gel.
- Arbre gelé aff97638 :
  - `bot.p3.certification` : PDA et base58 ;
  - `bot.market.backfill` : grille de coûts, pour le test de parité.

## Chaîne (textes A, B(b) et C)

- **`step0.run`** : vecteurs V-1′ par `getTransaction`, avec une liste épinglée par son sha (50 à 100 signatures distinctes) et un plafond de 100 crédits.
- **`u2.run`** : la chaîne U-2, à 5 000 crédits au plus.
  1. `getSlot`, puis `getProgramAccounts` sur les AmmConfig. Filtres : dataSize 236, `dd8DvH45THQ` à l'offset 0, `Znnd43p7RpT` à l'offset 12. Le PDA est vérifié.
  2. `getProgramAccounts` des pools pour chaque config, avec WSOL à l'offset 168 puis 200 et dataSlice 0..413.
  3. Exclusions : `status & 4`, `lp_supply = 0`, Token-2022, listes P0 et W1 (paramètre `exclude`).
  4. `getMultipleAccounts` des coffres WSOL : PDA vérifié, réserve ≥ 100 SOL.
  5. Liste L hachée, permutation `random.Random(int(sha_L[:8], 16))`.
  6. Transaction de création par GTFA (asc, limit 1), jusqu'à 24 pools valides.
  7. Moins de 20 pools valides = INCONCLUSIF. GTFA refusée = STOP sans repli. Réponse tronquée = STOP.
- **`step1`** : l'étape 1, avec un arrêt dur à 49 000 crédits.
  - `count_24h` : `getSignaturesForAddress`, sans lire de transaction. Donne R̂, la règle du point (2) (`24 × R̂ × 8 × 0,10 + 400 > 32 900` = STOP) et D_max.
  - `collect` : phase `pre` [T0 − 7 j ; T0), puis phase `window` [T0 ; T0 + D).
    - GTFA, transactions complètes, tri ascendant, 100 par page.
    - Chaque page est écrite directement en gz.
    - Un `STATE.json` par pool, écrit après chaque page, rend la collecte reprenable.
    - Contrôle de disque ≥ 2 Go.
  - `trigger_counts` : R-CP1 et B1 sur la phase `pre`, sans aucun résultat.
  - `freeze_sheets` : FICHE_GEL_RCP1 et FICHE_GEL_B1 (T0, liste, D, R̂, sha du code, `frozen_check`).
  - `check_anchor` : la fenêtre n'est lue que si les sha ancrés par R02 sont égaux aux fichiers.
  - `g1_inputs` : positions primaires et témoins, via les fonctions gelées.
- **`store.archive_parts`** : tar.gz déterministe découpé en parties de 90 Mo, plus son sha.
- **Budget** (`budget.PilotBudget`) : même discipline que `backfill.CreditBudget`.
  - Chaque débit est écrit sur disque avant l'envoi.
  - La grille de coûts est épinglée dans le registre.
  - Une reprise ne repart jamais d'un compteur plus bas.

## Points ouverts pour l'audit R02

1. **`CreditBudget` n'est pas réutilisé tel quel.** Son constructeur refuse toute méthode hors `READ_METHODS`, qui ne contient que les trois méthodes du backfill W1. `PilotBudget` reproduit sa discipline, et un test vérifie la parité des coûts sur les méthodes communes.
2. **G-1 n'existe pas en code gelé.** Il n'y a pas de fonction `pilot_verdict` dans `cpmmprereg` : le runner publie les positions et écrit `G1_RULE_NOT_FROZEN`. Deux voies possibles : R01 ajoute G-1 (n < 30 ou < 20 pools = INCONCLUSIF ; borne haute unilatérale à 95 % < 0 = NO-GO ; sinon GO_PILOTE), ou R02 le calcule à partir des positions publiées.
3. **Token-2022.** Tous les pools Token-2022 sont exclus, ce qui est plus strict que U-4 (« avec frais de transfert »). Lire l'extension du mint coûterait des appels non prévus par B(b).
4. **t0_time.** C'est l'horloge UTC locale au moment de T0, car `getBlockTime` ne figure pas dans B(b). Elle n'est utilisée que pour l'âge ≥ 7 jours et pour les fenêtres temporelles.
5. **Statistique de R̂.** Le runner prend la moyenne des signatures par pool sur les 24 h ; c'est à R02 de la fixer dans la fiche.
6. **Hachage de l'AmmConfig pour `fees_from_amm_config`.** Le runner prend le sha de ses champs décodés (forme canonique) et le slot de T0. L'alternative est le sha des octets bruts du compte : à trancher par R02.
7. **Pagination GTFA de la FakeChain** (`paginationToken`, filtre `blockTime` gte/lt). Elle suit la documentation archivée du 08/11. Le format réel est à vérifier dès les premiers appels réels, et tout écart = STOP.
8. **Entrées à fournir pour le vrai pilote :**
   - la liste réelle des vecteurs V-1′ du protocole, avec son sha ;
   - les listes d'exclusion P0 visible (aca7de08) et w1migr, avec leurs sha.

## Commandes, hors ligne

Les commandes se lancent depuis l'arbre gelé, avec le PYTHONPATH des règles gelées (voir `cpmmpilot_pythonpath.txt`) suivi de `cpmmpilot_pkg`.

```
unshare -rn env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=<…> python3.12 -B -m pytest <cpmmpilot>/tests -p no:cacheprovider -q -W error
unshare -rn env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=<…> python3.12 -B -m cpmmpilot.rehearse --out <NOUVEAU>
```

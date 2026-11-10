# Protocole de l'intégration CPMM expérimentale au simulateur V4 — v1.2

RUGGER 01, 2026-11-10. Delta de la v1.1 (0816bc9d, ancrée avec réserves par RUGGER 02, ré-audit
677d0450) : réserves Ra à Rd levées. Intègre l'audit a1f5efe0 (O-1, T-1 à T-3, H-1 à H-7, V-1′, V-2 à
V-9). À ancrer par RUGGER 02 **avant tout passage de `a12.py` sur données réelles**.
Complète la section 4 du protocole V4 v2 (00d9ccf9…) ; ne le modifie pas. `v4sim` 0.2 reste intact
(empreinte 2fe085a33c5604f30468e08e4c0ee096f9881d8efbf24fad0c5faf51af03db67).

## 1. Objet
Valoriser, par une vente sur le pool Raydium CPMM réel, une position que `v4sim` laisse
`migrated_unpriced` : chaîne achat → détention → migration → vente → P&L net.
Code : `cpmmx` 0.1 (décodeur) et `v4cpmm` 0.1 (pont), MANIFEST_cpmm_v01.

## 2. Interdits
- Créditer une position migrée dans un résultat économique tant que C-1 à C-6 ne sont pas tous passés.
  Chaque bloc porte `creditable: false` et ses motifs.
- Supposer un taux de frais, une réserve ou un état de pool : tout est lu, sinon statut `unpriced_*`.
- Toute donnée W1 (slot ≥ 467 275 745) ou du holdout P0 pour mettre au point ce module.
- Toute collecte sans GO explicite du propriétaire ; tout réglage propre à CPMM (H-6) : la jambe CPMM
  reprend les paramètres d'exécution du passage `v4sim`, figés dans le plan.

## 3. Données requises par pool migré
1. Les transactions brutes de l'adresse du pool CPMM, de sa création à la fin de la fenêtre, avec
   `slot`, `blockTime`, `transactionIndex`, `meta.err`, `meta.logMessages`.
2. Le slot et l'heure de création du pool ; le mint de base ; la transaction de migration qui le lie
   au pool LaunchLab d'origine.
3. Le compte AmmConfig du pool, lu et haché avec son slot : taux de trading, de créateur, parts
   protocole et fonds. **Ces taux lus sont la seule source de C-1 (H-2).**

## 4. Règles de sortie après migration (fixées avant tout résultat)
- `at_open` : ordre envoyé à la création du pool, atterrissage `latency_slots` plus tard.
- `strategy_clock` : atterrissage à l'échéance d'horloge de la stratégie + `clock_exit_latency_s` ;
  si l'échéance est déjà passée à la création du pool, règle `at_open`.
- **Ordre dans le slot d'atterrissage (H-1)** : la valeur est calculée avant et après les swaps réels
  de ce slot ; les deux sont publiées ; seule la plus basse est retenue. Le paramètre `slot_order` de
  l'exécution est tracé dans le bloc avec la mention « non appliqué » (Rd).
- Non-inclusion, limite de glissement, nouvelles tentatives : paramètres et tirages déterministes de
  `v4sim` ; chaque échec est facturé.
- Aucune autre règle (stop, stop suiveur sur prix CPMM) dans cette version.

## 5. Approximations déclarées et leur borne
- **X-1 (H-5), méthode fixée d'avance.** (i) La courbe LaunchLab garde ses frais hors des réserves : le
  montant de SOL qu'elle détient à sa fin est fixé par son invariant, quel que soit le chemin. Mesure
  sur la courbe synthétique : même montant au lamport près avec et sans notre achat (test
  `test_x1_…`). Les réserves d'ouverture corrigées de notre trajectoire sont donc les réserves réelles.
  (ii) Ce que notre achat change : il déplace vers le pool une demande égale à notre mise nette de
  frais. La valeur avec cette demande appliquée à l'état d'atterrissage est publiée à côté de la valeur
  sur réserves réelles ; **la plus basse est retenue**.
  (iii) **Garde (Rc).** L'égalité (i) n'est montrée que sur la courbe synthétique. Si le rejeu `v4sim`
  du pool a levé une garde (vente suivie écrêtée, inventaire externe, événement de poussière ou vente
  nulle ignorés, ou tout drapeau du résultat), le bloc porte `unpriced_counterfactual_curve_differs`
  et aucun montant. Aucun delta de `v4sim` n'est requis.
- X-2 deux règles de sortie seulement ; X-3 aucun swap réel rejoué après notre vente ; X-4 côté des
  frais de créateur ou parts inconnus : borne défavorable au vendeur (non créditable) ; X-5 données
  synthétiques seulement ; X-6 ordre dans le slot : voir H-1.

## 6. Critères d'acceptation
- **C-1 (= A-12, durci H-2 / H-3)** : swaps réels recalculés avec les taux lus dans l'AmmConfig et le
  côté des frais de créateur journalisé par chaque événement ; ≥ 99,9 % reproduits à l'unité atomique
  près au total et ≥ 99 % par pool, sur ≥ 1 000 swaps et ≥ 5 pools ; ≥ 50 swaps à sortie exacte ; les
  deux côtés des frais de créateur s'ils existent ; ≥ 1 modification de liquidité ; ≥ 1 transaction où
  CPMM est appelé par un autre programme ; chaque écart expliqué un par un. Outil : `a12.py`, puis
  `a12.py --combine`. Un changement de taux en cours de vie exclut le pool.
- **C-2** : chaîne des réserves sans rupture avec les parts de l'AmmConfig. Un swap manquant, ou un
  dépôt direct dans un vault (aucun événement ; rupture d'un seul côté, H-7), exclut le pool ; les
  pools exclus sont comptés et publiés.
- **C-3** : les taux de l'AmmConfig sont dans chaque intervalle déduit des swaps (contre-vérification).
- **C-4** : identité du P&L (reçu − dépensé − frais de transaction `v4sim` − coûts ajoutés) recalculée
  par RUGGER 02 sur un échantillon tiré par lui.
- **C-5** : empreinte de `v4sim` inchangée ; résultat `v4sim` identique avec et sans le pont.
- **C-6** : mutations (frais × 0, latence 0, swap futur, cadre de programme ignoré, programme n'importe
  où dans la pile, un seul ordre dans le slot, frais de transaction oubliés) : chacune fait échouer un test.

## 7. Vecteurs de test publics (conditions V-1′ et V-2 à V-9 de RUGGER 02)
**V-1′ (remplace V-1)** : GO explicite du propriétaire dans la session de R03, puis au choix
(a) `api.mainnet-beta.solana.com` sans clé, hôte retiré de la liste d'accès le jour même ; ou
(b) Helius, 100 crédits au plus, relevés avant et après, aucun slot W1 ni W2, répertoire séparé, de
préférence après la collecte W1. Deux étages (50 à 100 transactions pour l'audit
du décodeur, puis ≥ 1 000 swaps sur ≥ 5 pools pour C-1, avec son propre GO) ; pools sans lien avec P0
(liste 9f19ccac) ni W1, créés avant le premier slot de P0 ; liste de candidats hachée puis tirage par
sha256(graine ‖ pool), graine fixée par R02 après l'ancrage de la liste, sans remplacement ; ≥ 3 pools
à l'historique complet depuis leur création ; `transactionIndex` par `getBlock` si la source ne le
donne pas ; AmmConfig lu et haché avec son slot ; signatures, sha256 des corps bruts et MANIFEST
ancrés par R02 **avant** `a12.py`, qui tourne une seule fois et que R02 recalcule.

## 8. État
O-1, T-1 à T-3 et T-3′ corrigés (H-4, Ra). C-5 passe. C-6 passe (confirmé par RUGGER 02, 5234ab9b).
Rc′ appliquée : `external_real_minus_cf` et `exact_out_replayed_as_budget` non nuls sont des gardes.
C-1 à C-4 : **non passés** — aucune donnée réelle.

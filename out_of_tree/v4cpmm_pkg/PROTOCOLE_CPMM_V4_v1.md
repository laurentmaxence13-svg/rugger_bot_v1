# Protocole de l'intégration CPMM expérimentale au simulateur V4 — v1 (projet)

RUGGER 01, 2026-11-10. À auditer et ancrer par RUGGER 02 **avant tout usage sur données réelles**.
Complète la section 4 du protocole V4 v2 (00d9ccf9…) ; ne le modifie pas. `v4sim` 0.2 reste intact
(empreinte 2fe085a33c5604f30468e08e4c0ee096f9881d8efbf24fad0c5faf51af03db67).

## 1. Objet
Valoriser, par une vente sur le pool Raydium CPMM réel, une position que `v4sim` laisse
`migrated_unpriced`, afin de mesurer la chaîne complète achat → détention → migration → vente → P&L net.
Code : `cpmmx` 0.1 (décodeur) et `v4cpmm` 0.1 (pont), commit 102a3c6c, MANIFEST_cpmm_v01.

## 2. Ce qui est interdit
- Créditer une position migrée dans un résultat économique tant que C-1 à C-5 ne sont pas tous passés.
- Supposer un taux de frais, une réserve ou un état de pool : tout est lu, sinon statut `unpriced_*`.
- Toute donnée W1 (slot ≥ 467 275 745) ou du holdout P0 pour mettre au point ce module.
- Toute collecte payante, ou hors d'un périmètre autorisé par le propriétaire.

## 3. Données requises par pool migré
1. Les transactions brutes de l'adresse du pool CPMM, de sa création à la fin de la fenêtre, avec
   `slot`, `blockTime`, `transactionIndex`, `meta.err`, `meta.logMessages`.
2. Le slot et l'heure de création du pool ; le mint de base ; le lien avec le pool LaunchLab d'origine
   (transaction de migration).
3. Les taux du compte AmmConfig du pool (frais de trading, de créateur, parts protocole et fonds) et
   le côté des frais de créateur.

## 4. Règles de sortie après migration (fixées avant tout résultat)
- `at_open` : ordre envoyé à la création du pool, atterrissage `latency_slots` plus tard.
- `strategy_clock` : atterrissage à l'échéance d'horloge de la stratégie + `clock_exit_latency_s` ;
  si l'échéance est déjà passée à la création du pool, règle `at_open`.
- Non-inclusion, limite de glissement et nouvelles tentatives : mêmes paramètres et mêmes tirages
  déterministes que `v4sim` ; chaque échec est facturé.
- Aucune autre règle (stop, stop suiveur sur prix CPMM) dans cette version.

## 5. Approximations déclarées
X-1 à X-5 du README `v4cpmm` (réserves réelles prises telles quelles ; deux règles de sortie ; aucune
suite rejouée après notre vente ; borne défavorable au vendeur quand un taux ou un côté est inconnu ;
vérification sur données synthétiques seulement). X-1 doit être bornée avant tout crédit : écart de
valeur entre réserves d'ouverture réelles et réserves corrigées de notre position, sur chaque pool.

## 6. Critères d'acceptation
- **C-1 (= A-12)** : sur des swaps réels, ≥ 99,9 % reproduits à l'unité atomique près (montant entré,
  montant sorti, frais de trading, frais de créateur), sur au moins 1 000 swaps et 5 pools ; chaque
  écart expliqué un par un ; les deux instructions (`swap_base_input`, `swap_base_output`) présentes.
- **C-2** : chaîne des réserves sans trou sur chaque pool retenu (`a12.py` : `both_sides` = 0), sinon
  le pool est exclu et compté.
- **C-3** : taux lus dans les événements = taux du compte AmmConfig ; prélèvement protocole + fonds
  mesuré = parts de l'AmmConfig.
- **C-4** : identité du P&L (reçu − dépensé − tous frais de transaction) recalculée par RUGGER 02 sur
  un échantillon tiré par lui.
- **C-5** : empreinte de `v4sim` inchangée ; résultat `v4sim` identique avec et sans le pont.
- **C-6** : tests de mutation (frais × 0, latence 0, lecture d'un swap futur, cadre de programme
  ignoré) : chaque mutation fait échouer au moins un test.

## 7. Vecteurs de test publics
Pour l'audit du décodeur : quelques dizaines de transactions CPMM publiques, fixées et hachées, de
slots antérieurs à la fenêtre P0, sur des pools sans lien avec P0 ni W1. Source gratuite, sans clé
ni crédit ; la liste des signatures et le sha256 de chaque corps sont remis à RUGGER 02 avant le
premier passage de `a12.py`.

## 8. État
C-5 passe (46 tests, données synthétiques). C-1 à C-4 et C-6 : **non passés** — aucune donnée réelle.

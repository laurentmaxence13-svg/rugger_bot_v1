# cpmmx 0.1 — décodeur Raydium CPMM (expérimental)

RUGGER 01, 2026-11-10. **Statut : expérimental, non ancré, non validé sur des swaps réels.**
Bibliothèque standard seule ; n'importe ni l'arbre gelé, ni `v4sim`, ni `w1aux`, ni `v3lab`.

## Ce que fait le module
- `curve.py` — arithmétique entière exacte d'un pool cp-swap, transcrite de la source officielle
  `raydium-io/raydium-cp-swap` (branche master lue le 2026-11-10 ; préfixes sha256 des fichiers lus :
  `states/events.rs` c81d5d9d75b1af21, `curve/calculator.rs` aee16991f81d755a,
  `curve/constant_product.rs` 5a6ab835ba35e872, `curve/fees.rs` 0d0b005123cd9e9e,
  `instructions/swap_base_input.rs` 5878ed09654745b5, `states/pool.rs` e2a836869400bf3c,
  `states/config.rs` 02384ef4d41b1dfc) : `swap_base_input`, `swap_base_output`, frais de trading,
  de protocole, de fonds et de créateur (sur l'entrée ou sur la sortie), réserves après un swap.
- `events.py` — décodage de `SwapEvent` (162 octets, et l'ancien format de 81 octets) et de
  `LpChangeEvent` dans `meta.logMessages`. Seule une ligne `Program data:` émise **pendant que le
  programme CPMM est le cadre en cours d'exécution** est acceptée. Journal tronqué, taille inconnue,
  booléen invalide, cadres déséquilibrés : erreur explicite, jamais de valeur devinée. Transaction en
  échec : ignorée.
- `timeline.py` — chronologie d'un pool (slot, index de transaction, ordre dans la transaction),
  réserves avant chaque swap telles que le programme les a journalisées, lecture causale des taux
  de frais, contrôle de continuité (un swap manquant se voit), état à un point d'atterrissage,
  valeur exacte d'une vente.
- `a12.py` — contrôle A-12 d'un pool : chaque swap observé est recalculé à l'unité atomique près,
  chaque écart est listé champ par champ.

## Ce que le module ne prouve pas
- Les formats et l'arithmétique ne sont vérifiés que sur des données **synthétiques** produites par
  un simulateur écrit à partir de la même source. Tant que A-12 n'a pas passé sur des swaps réels
  (≥ 99,9 % reproduits à l'unité près, écarts expliqués un par un), aucun nombre issu de ce module
  n'est un résultat économique.
- Les parts de protocole et de fonds ne sont pas dans les événements : elles viennent du compte
  AmmConfig du pool. Sans elles, la réserve du côté entrée du dernier swap est connue à ses frais de
  trading près, et `sell_value` retient la borne défavorable au vendeur.
- Frais de transfert Token-2022, `open_time` du pool, changement de taux en cours de vie : non modélisés
  (refus explicite).

## Tests
    PYTHONPATH=<cpmmx_pkg> python -B -m pytest -q <cpmmx_pkg>/cpmmx/tests -p no:cacheprovider -W error
35 tests, Python 3.12 et 3.11, hors réseau.

## Données nécessaires pour A-12 (non collectées)
Par pool migré : les transactions brutes de l'adresse du pool CPMM (au moins de sa création à la fin
de la fenêtre), le slot et l'heure de sa création, son mint de base, et les taux de son AmmConfig.
Chaque transaction doit porter `slot`, `blockTime` et un `transactionIndex` entier (la clé d'ordre des
exports Helius déjà utilisés) : sans lui, l'ordre dans un slot n'est pas reconstruit et le pool est refusé.
Format d'entrée de `a12.py` : `{"pool", "base_mint", "opened": [slot, block_time] | null,
"transactions": {signature: résultat brut de getTransaction}}`.

# P4 — comparaison causale utilisant le portefeuille natif

Infrastructure de recherche hors réseau, ajoutée le 28 octobre 2026. Le score,
les veto, TP/SL/trailing et protections actifs restent ceux de
`final_decision_engine.decide` et `paper_trader.record_quote`.
Aucune variante n'est activée dans le scanner ou promue en production.

Les trois adaptateurs figés partagent les observations et le même budget de
1 SOL, avec 10 SOL de capital initial par bras comparatif. Chaque bras utilise
une instance isolée du **même** portefeuille SQLite existant et ses tables
`paper_token_inventory`/`paper_token_legs`; aucune nouvelle comptabilité de trading
n'est introduite. Toutes les positions d'un bras partagent son capital et ses
limites existantes (3 positions, 20 entrées/jour, perte réalisée quotidienne10%).

- `early_sniping` prend le premier signal admis par le moteur actif.
- `confirmed_momentum` exige en plus15 s, un slot strictement plus récent, un prix
  observé supérieur au premier prix et au moins2 acheteurs déclarés indépendants.
- `adaptive_hybrid` prend l'entrée précoce seulement si le comportement créateur
  est connu, au moins2 lancements antérieurs sont observés, la concentration est
  connue et≤20%, sans activité coordonnée même slot connue; sinon il attend la
  même confirmation. Ces seuils sont des **hypothèses de recherche**, pas des
  règles rentables démontrées ni une attribution à un trader extérieur.

Les sorties utilisent le modèle TP/SL/trailing calculé lors de l'entrée, commun
aux variantes, et une tentative au premier événement disponible après30 s.
Une absence à l'horizon ne crée aucune observation interpolée. Chaque entrée
conserve sa propre quantité; une vente est liée à son identifiant d'achat et à la
quantité réellement cotée. Les jambes partielles, frais, refus et reliquats passent
par les fonctions existantes du portefeuille. Un refus indicatif sur une banque
qui n'inclut pas notre achat ne prouve pas l'impossibilité contrefactuelle après
notre achat. Ce moteur ne remplace pas la qualification de cet effet propre P3.

## Contrat des observations

L'entrée JSON contient `corpus` (`data_kind`, `frames`) et `protocol`
(`registered_at_ms`, `development_end_ms`, `policy_sha256`). Le hash est SHA256 du
JSON canonique de `bot.p4_experiment.POLICY`. Le protocole doit précéder la coupure.
L'outil vérifie sa cohérence, mais ne certifie pas que la date a été publiée avant
la collecte: cette preuve reste un commit Git et un manifeste de capture.

Les événements sont dans l'ordre de disponibilité, sans identifiant réutilisé.
Chaque événement conserve `id`, `mint`, `creator`, `pool`, `detected_at_ms`,
`available_at_ms`, `source_slot`, `slot_available_at_ms`,
`features_available_at_ms`, `features` (contrat `SignalFeatures`),
`independent_buyers`, `buy_context` et `sell_contexts` lorsqu'ils existent.
Les contextes sont ceux du bridge d'inventaire existant, avec corps de devis et
provenance de frais. Un contexte vendeur porte aussi
`inventory_buy_observation_id`. Le lecteur refuse une information provenant du
futur; il n'invente ni nombre d'acheteurs, ni comportement, ni concentration, ni
prix. Le fournisseur des frames doit conserver leurs preuves sources: une simple
valeur déclarée ne devient pas une observation certifiée.

Les mints détectés avant la coupure appartiennent au développement; leurs prix
arrivant après la coupure ne sont pas utilisables pour compléter ce résultat.
Un créateur apparaissant en développement est exclu de la validation. Les groupes
créateurs reposent sur les identités fournies; leur indépendance réelle n'est pas
certifiée. Aucun entraînement ni ajustement des paramètres n'est exécuté.

## Mesures et limites

Le rapport conserve les candidats sans entrée, les décisions à chaque préfixe,
les quantités, jambes, coûts connus, résidus et refus. Il calcule le réalisé
rapproché du portefeuille et le drawdown du réalisé. **Ce drawdown n'est pas un
mark-to-market des positions ouvertes.** Le P&L total du portefeuille, rendement,
espérance, win rate et profit factor restent inconnus si une position demeure
ouverte. Les frais inconnus ne sont pas remplacés par zéro. Les frais de swaps
inclus dans les outputs ne sont pas comptés deux fois.

Les quatre sensibilités préfixées (frais additionnels×1/×2, délai de décision
0/250 ms) utilisent les mêmes bras et les mêmes sources. Elles ne créent pas de
nouvelle cotation au prix ancien pour un nouvel instant. Une cotation devenue
périmée est refusée. La sensibilité ne choisit aucun vainqueur.

La fixture versionnée vérifie uniquement le logiciel: lots précoces1000 et
confirmés900, frais synthétiques explicites, deux créateurs distincts déclarés.
Elle ne démontre pas un avantage; les corps synthétiques ne sont pas des fills.
Le contrôle008 ne possède pas les features créateur/wallet/momentum nécessaires:
il ne doit pas être converti en comparaison favorable avec des features inventées.
Une comparaison statistique future exige des preuves P3 admissibles, une
validation préenregistrée, des clusters vérifiés et un effectif justifié.

```sh
python -B -m bot experiment \
  --input benchmarks/p4_native_comparison_v1/fixture.json \
  --output work/p4-report-new.json
```

Commande également disponible via `python -B -m bot.p4_experiment`. Les deux
installent les interdictions réseau et `.env` avant les imports du moteur.

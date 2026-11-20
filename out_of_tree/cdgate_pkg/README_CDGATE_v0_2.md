# cdgate 0.2 — correction B-1 de R02 (palier, et non taux brut), rien d'autre

- **Éligibilité.** Le PALIER du taux causal doit être ≤ 2 500 ppm. Le palier est le taux arrondi aux 500 ppm les plus
  proches, comme `feeage.tier_of` (Q4). Exemple : un taux de 2 502 ppm, intervalle [2 495 ; 2 502], donne le palier
  2 500 : le pool est ÉLIGIBLE. Un taux de 2 750 ppm donne le palier 3 000 : NON éligible.
- **Coûts.** Le taux brut reste celui des coûts et de la décomposition.
- **Cycles.** Le champ `eligible_at_tier_le_2500` est publié avec la référence Q4 : 53 pools sur la plage, avant
  exclusions.
- **Inchangé.** Tout le reste est celui de la 0.1 (voir `README_CDGATE_v0_1.md`).
- **Preuves.**
  - 11 tests réussis. Nouveau test sur le vrai `causal_fee_rate` : intervalle [2 495 ; 2 502] éligible, 2 750 non
    éligible.
  - Défauts volontaires : 14 sur 14 détectés, dont `raw_rate_comparison` (retour à la comparaison brute) et
    `tier_floor_not_round` (troncature au lieu de l'arrondi) ; voir `MUTATIONS_cdgate_v0_2.json`.

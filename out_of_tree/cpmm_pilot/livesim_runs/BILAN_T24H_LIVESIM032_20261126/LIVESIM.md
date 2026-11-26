# Simulation PAPER en temps réel — G2-3 et N1 (démonstration descriptive)

- Aucun essai, aucun verdict ; jamais un trade du Master. Univers distinct des pilotes.
- Fenêtre : 1795606731 → 1795693131 (24.0 h). Statut : ÉVALUABLE (démonstration descriptive).
- Pools éligibles (G-0 admis et b₃ > 0) : 3 sur 3 (au moins 3 exigés).

| Pool | b₃ | G-0 | Éligible |
|---|---|---|---|
| GaPTvXuo | 4.0 | admis | oui |
| 6CQSpRdG | 1.0 | admis | oui |
| 5zk4vhcP | 1.0 | admis | oui |

- 0,1 SOL par position G2-3 (0.1 SOL). Capital fictif : somme cumulée des P&L nets des positions fermées, par heure de sortie, depuis 0.
- témoin retiré à chaque « now », autant que de signaux connus ; ses positions peuvent changer entre deux bilans.

## G2-3 (le témoin apparié est à côté, jamais additionné)

| Série | Signaux | Entrées | Sorties | Ouvertes | Refus de garde | Taux de réussite (net > 0) | P&L brut (SOL) | Coûts (SOL) | P&L net = capital fictif (SOL) | Net moyen par position | Drawdown max (SOL) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G2-3 (n insuffisant : 21 < 30) | 21 | 21 | 21 | 0 | 0 | 9.52 % | 0.010820 | 0.020583 | -0.009762 | -0.46 % | 0.009762 |
| témoin apparié (n insuffisant : 19 < 30) | 20 | 19 | 19 | 1 | 0 | 5.26 % | 0.007851 | 0.018629 | -0.010778 | -0.57 % | 0.010778 |

### Capital fictif par heure (SOL)

| Heure | G2-3 | témoin apparié |
|---|---|---|
| 1795610331 | -0.001066 | 0.000000 |
| 1795613931 | -0.002624 | -0.001482 |
| 1795617531 | -0.003722 | -0.002588 |
| 1795621131 | -0.005417 | -0.004023 |
| 1795624731 | -0.005417 | -0.005123 |
| 1795628331 | -0.006842 | -0.006457 |
| 1795631931 | -0.008090 | -0.006457 |
| 1795635531 | -0.008827 | -0.007451 |
| 1795639131 | -0.009695 | -0.008450 |
| 1795642731 | -0.003873 | -0.002322 |
| 1795646331 | -0.005016 | -0.003396 |
| 1795649931 | -0.006031 | -0.003396 |
| 1795653531 | -0.002595 | -0.004632 |
| 1795657131 | -0.002595 | -0.006278 |
| 1795660731 | -0.003264 | -0.006278 |
| 1795664331 | -0.004212 | -0.007217 |
| 1795667931 | -0.004212 | -0.007217 |
| 1795671531 | -0.004212 | -0.008120 |
| 1795675131 | -0.005176 | -0.009093 |
| 1795678731 | -0.005176 | -0.009093 |
| 1795682331 | -0.005621 | -0.009167 |
| 1795685931 | -0.006815 | -0.009954 |
| 1795689531 | -0.008453 | -0.009954 |
| 1795693131 | -0.009762 | -0.010778 |

## N1 — marques intermédiaires seulement

- Résultat 12 jours : NON MESURÉ.
- Pool-jours marqués : 0 — n insuffisant (< 30).
- Univers (n1rot 0.2, seuil r04_6_break_even) : 1 pool(s) retenu(s) sur 3, dont 1 éligible(s) ; au moins 3 exigés : NON ÉVALUABLE.

| Pool | Rotation médiane | Seuil | Retenu | Dernière marque | Statut | Écart à la détention | Net absolu | Mouvement de prix détenu |
|---|---|---|---|---|---|---|---|---|
| GaPTvXuo | 4.14 % | 22.44 % | non | — | non retenu | NON MESURÉ | NON MESURÉ | NON MESURÉ |
| 6CQSpRdG | 20.62 % | 21.01 % | non | — | non retenu | NON MESURÉ | NON MESURÉ | NON MESURÉ |
| 5zk4vhcP | 33.99 % | 22.13 % | oui | — | NON ÉVALUABLE | NON MESURÉ | NON MESURÉ | NON MESURÉ |

## Limites (7)

- L1 : démonstration descriptive. Aucun essai, aucun test ni verdict, jamais un trade du Master. Le résultat ne peut servir ni à choisir ni à modifier une stratégie.
- L2 : pools différents de ceux des pilotes, choisis par la règle ancrée par R02 avant toute lecture (registre 08:42:17Z et 08:45:05Z ; liste 5c4fefb6…). Aucune généralisation.
- L3 : horizon de 6 h et de 24 h, au lieu des 12 jours. Le n est faible ; « n insuffisant » est publié quand il le faut.
- L4 : collecte rétrospective par blocs de 2 h, donc une latence de 2 h au plus. Données tronquées à now. L-FIN. Seules les positions fermées sont valorisées.
- L5 : même période de marché que la fenêtre pilote, donc une corrélation possible. Cela ne dit rien des verdicts du 6 décembre.
- L6 : au départ, l'historique des acheteurs sur 600 s est tronqué et le délai de 3 600 s repart à zéro. Le témoin est retiré à chaque bilan. La config de chaque pool est celle lue à U-1, à un slot antérieur.
- L7 : N1 en marques intermédiaires seulement ; le résultat à 12 jours est NON MESURÉ. Coûts du modèle gelé : pas de MEV, latence gelée. PAPER seulement.

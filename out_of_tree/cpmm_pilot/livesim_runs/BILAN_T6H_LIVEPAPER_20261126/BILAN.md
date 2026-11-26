# Bilan du test PAPER en direct — livepaper (PAPER_LIVE_DEMO, démonstration descriptive)

- Aucun essai, aucun verdict ; jamais un trade du Master, jamais compté pour 50/20.
- Fenêtre : 1795632000 (18:40:00Z) → 1795653600 (00:40:00Z), 6.00 h. Cut : 00:40:00Z.
- Journal : 1828 enregistrements au cut (seq 1827, tête f12b303d714dd00971b003cb5d9bf47bbce0baaddb7879c0f6119966d1ab7ea0) sur 1976 (tête fbd913deba2e3931ac2046e1aa1e796ee0ce94d67dfbbed8e67de8109b06d53c). Schéma livepaper-v0.1.1, mode gsfa_rank, poll 30 s, variante B.
- Ne comptent que les positions décidées avant le cut ; une position sans EXIT dans le préfixe est OUVERTE et jamais valorisée.

## G2-3 (le témoin apparié est à côté, jamais additionné)

| Série | Décisions | Entrées | Sorties | Ouvertes | Refus de garde | Taux net > 0 | P&L brut (SOL) | Coûts (SOL) | P&L net = capital fictif (SOL) | Net moyen par position | Drawdown max (SOL) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G2-3 (n insuffisant : 7 < 30) | 7 | 7 | 7 | 0 | 0 | 28.57 % | 0.012021 | 0.006939 | 0.005082 | 0.73 % | 0.003265 |
| témoin apparié (n insuffisant : 7 < 30) | 7 | 7 | 7 | 0 | 0 | 0.00 % | -0.000158 | 0.006894 | -0.007052 | -1.01 % | 0.007052 |

- Témoin non entré (WAIT) : 0.

### Capital fictif par heure (SOL)

| Heure | G2-3 | témoin apparié |
|---|---|---|
| 19:40:00Z | -0.000994 | -0.000801 |
| 20:40:00Z | -0.001749 | -0.000801 |
| 21:40:00Z | 0.003804 | -0.003018 |
| 22:40:00Z | 0.002661 | -0.003618 |
| 23:40:00Z | 0.005082 | -0.006034 |
| 00:40:00Z | 0.005082 | -0.007052 |

### Positions ouvertes au cut (jamais valorisées)

Aucune.

## Latences

| Mesure | n | p50 | p95 | p99 | max | moyenne |
|---|---|---|---|---|---|---|
| delay_s (déclencheur → décision, s) | 7 | 20 | 31 | 31 | 31 | 21.000 |
| latency_slots | 14 | 4 | 4 | 4 | 4 | 4.000 |
| slots déclencheur → atterrissage | 7 | 100 | 147 | 147 | 147 | 100.429 |
| processing_ms (traitement d'un pas) | 716 | 25.403131 | 55.355816 | 64.577495 | 79.195749 | 26.571 |

- fetch_ms : NON MESURÉ (livepaper 0.1.2 ne le journalise pas).
- Décisions prises après un GAP : 0.

## GAP et interruptions

- Pas : 716, de 18:40:02Z à 00:40:00Z ; intervalle max 95 s ; intervalles ≥ 2 × poll : 3.
- GAP : 20:10:03Z → 20:11:03Z (60.3 s).
- GAP : 20:29:33Z → 20:30:37Z (63.9 s).
- GAP : 00:10:26Z → 00:12:01Z (94.2 s).
- STOP : planned_end_of_process à 20:30:02Z.
- STOP : planned_end_of_process à 22:20:35Z.
- STOP : planned_end_of_process à 00:10:55Z.

## G-0 au cut (C9)

| Pool | Admis | Raisons | Non admis depuis | Changements |
|---|---|---|---|---|
| GaPTvXuo | non | reserves_chain_broken | 20:11:03Z | 3 |
| 6CQSpRdG | oui | — | — | 2 |
| 5zk4vhcP | oui | — | — | 2 |

## Défauts déclarés (C9)

- D13 : GaPTvX est exclu par G-0 depuis 20:11:03Z à la suite d'une transaction manquée (slot 473875242, blockTime 1795637419) ; la comparaison avec livesim est reportée au bilan final.

## Crédits

- Au cut : NON MESURÉ (ni le grand livre ni le journal d'appels ne sont horodatés).
- Au snapshot : 4323 crédits, 4323 requêtes (plafond 25000, arrêt 24500) ; par méthode : {"getSignaturesForAddress": 2427, "getSlot": 784, "getTransaction": 1112}.
- Journal d'appels : 4322 lignes, dernier credits_after 4323.

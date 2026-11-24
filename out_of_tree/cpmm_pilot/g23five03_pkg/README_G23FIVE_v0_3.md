# g23five 0.3 — paramètre alpha, valeur p bootstrap, moitiés, Holm (confirmation, jalon 3)

RUGGER 01, 24/11/2026.
- Décisions : R04-7 (2) ; R02 (22:47Z), qui donne le feu vert pour g23five 0.3.
- **Paquet séparé** (`cpmm_pilot/g23five03_pkg`). Restent INTACTS :
  - 0.1.1, utilisé par G2-3 (`g23five_pkg`) ;
  - 0.2, utilisé par N1 (`g23five02_pkg`).
- **Aucune règle ne change.**

| Ajout | Règle |
|---|---|
| `alpha` | Paramètre de `stratified_bounds`, `difference_bounds` et `report`. Valeurs déclarées : 0,05 (défaut, le pilote), 0,025 (confirmation, K = 1) et 0,0125 (premier pas de Holm, K = 2). Toute autre valeur est refusée. Quantile k = int(alpha × tirages) − 1 |
| `bootstrap_p` | Valeur p unilatérale de « moyenne ≤ 0 », sur les MÊMES tirages que les bornes : (#moyennes ≤ 0 + 1) / (tirages + 1) |
| `halves` | Moyennes ponctuelles des deux moitiés, coupure à T0 + (D × 86 400) // 2, comme `cpmmprereg.halves`. c3 = les deux > 0 |
| `holm` | Holm descendant à α₂ = 0,025 sur toutes les hypothèses retenues. INCONCLUSIF compte p = 1. Les bornes sont inclusives |
| `report` | Publie en plus `alpha`, `p_value` (sur les blocs de `block_days`) et `halves` |

**Validation.**
- 20 tests. Ce sont ceux de 0.1 / 0.1.1 / 0.2, plus 6 nouveaux :
  - identité avec **0.1.1** (sha 52b9d2b0 vérifié) et avec **0.2** (sha 15749bd5 vérifié) à alpha = 0,05 ; les
    rapports sont égaux, aux clés nouvelles près ;
  - quantiles à 0,025 et 0,0125, y compris pour la garde et l'écart au témoin ; refus de 0,1, 0,01 et 0,05000001 ;
  - valeur p égale à un calcul direct, aux blocs de 1 et de 2 jours ; p = 1/(tirages + 1) quand tout est positif ;
    p = 1 à 0 ;
  - moitiés : coupure, bord, moitié vide (NM), « > 0 » strict ;
  - Holm : cas K = 1 et K = 2, arrêt, INCONCLUSIF, bornes inclusives.
- 66 mutants sur 66 détectés (`MUTATIONS_g23five_v0_3.json`) : les 48 de 0.2 et 18 nouveaux. Le runner copie 0.1.1 et
  0.2 à côté des mutants, pour les tests d'identité.

# n1verdict 0.3 — paramètre alpha, valeur p, moitiés et phase de confirmation (jalon 3)

RUGGER 01, 24/11/2026.
- Décisions : R04-7 (2) ; R02 (22:47Z), qui donne le feu vert pour n1verdict 0.3.
- **Paquet séparé** (`cpmm_pilot/n1verdict03_pkg`). n1verdict 0.2.2, ancré avec la fiche N1 v0.7, reste INTACT dans
  `n1verdict_pkg`.
- **Aucune règle ne change.**
- Ce paquet s'utilise avec g23five 0.3 (`g23five03_pkg`), lpcost 0.2 et cpmmpilot.

**`verdict.py`.**
- `report(..., alpha=0.05)` : le mot, la garde K-1 et les sensibilités sont calculés au seuil `alpha`, sur des blocs
  de 2 jours.
- Publie en plus `alpha`, `p_value` (`g23five.bootstrap_p`, blocs de 2 jours) et `halves` (jours 0–5 / 6–11).
- Un `alpha` non déclaré est refusé, même avant un STOP.

**`lines.py`.**
- `--phase pilot|confirmation` et `--alpha`, obligatoires.
  - pilote : T0, α = 0,05 seulement.
  - confirmation : T0_C = 1 796 552 486 (06/12/2026 10:21:26Z, soit T0 + 12 j), α = 0,025 ou 0,0125.
- Mêmes pools (c72bd586) et même D = 12.
- Pour la confirmation, les pages « pré-T0 » sont celles d'avant T0_C ; elles servent seulement à l'état au premier
  atterrissage.

**Validation.**
- 16 tests : les 13 de 0.2.2, plus 3 nouveaux.
  - Identité avec 0.2.1 / 0.2.2 (sha de verdict.py e6db8985 vérifié) à α = 0,05.
  - α à 0,025 et 0,0125 : mot, garde, sensibilités ; valeur p sur blocs de 2 jours ; moitiés ; refus.
  - Phase de confirmation de bout en bout : T0_C, α déclaré par phase, pages du pilote refusées.
- 62 mutants sur 62 détectés (`MUTATIONS_n1verdict_v0_3.json`) : 41 sur `verdict.py` et 21 sur `lines.py`. Un
  équivalent a été retiré et justifié.

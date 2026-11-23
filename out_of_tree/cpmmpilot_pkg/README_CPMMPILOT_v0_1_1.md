# cpmmpilot 0.1.1 — corrections K-1 à K-3 de l'audit R02 (0b3a3033), toujours HORS LIGNE

Le README de la 0.1 reste valable pour tout le reste.

- **K-1 — runner de mutants** (`mutations_cpmmpilot_runner.py`).
  - Une garde de base vérifie d'abord que la copie non mutée passe les tests.
  - **22 mutants sur 22 sont tués** (`MUTATIONS_cpmmpilot_v0_1_1.json`) :
    - les 4 survivants de R02 : `charge_after`, `seed_changed`, `reserve_50`, `floor_ignored` ;
    - 18 autres :
      - budget : `reserve_strict`, `hard_stop_50000`, `point2_ge`, `gtfa_cost_1`, `ledger_not_resumed`, `gtfa_limit_unchecked` ;
      - U-2 : `gtfa_fallback`, `launchlab_ignored`, `depth_ignored`, `age_6_days`, `target_25`, `token2022_excluded_again`, `status_not_checked` ;
      - étape 1 : `anchor_not_checked`, `resume_from_zero`, `g0_forced_true`, `count_window_wide` ;
      - réseau : `live_allowed`.
  - Tests ajoutés :
    - le débit est écrit AVANT l'envoi, même si le transport lève une erreur ;
    - la graine vaut exactement `int(sha_L[:8], 16)` ;
    - la frontière des 100 SOL est incluse (100 SOL gardé, 100 SOL − 1 lamport exclu) ;
    - INCONCLUSIF après épuisement de L (|L| = 23, 17 pools valides) ;
    - la reprise ne recharge pas les pages déjà terminées ;
    - le décompte porte exactement sur les 24 h avant T0.
- **K-2 — G-1 par `cpmmcost.model.pilot_verdict`**, fonction gelée de cpmmcost 0.3.
  - Elle reçoit `g0_passed`, le résultat ANCRÉ de l'étape 0, et le sha de la fiche de gel.
  - Elle porte sur les positions valorisées des pools admis par `cpmmcost.pool_gate`, qui applique U-4 et G-0 par pool, avec ses motifs comptés.
  - Le nombre de positions non valorisées est publié à part.
  - Le témoin et son écart moyen apparié sont publiés À PART, sans aucune décision.
  - « G1_RULE_NOT_FROZEN » est supprimé.
- **K-3 — plus d'exclusion Token-2022 dans U-2.** Ces pools restent dans L, et U-4 est appliqué par `pool_gate` à l'étape 1. `status & 4` et `lp_supply = 0` restent, déclarés comme éligibilité technique et comptés.
- **Point 6 :** le sha de l'AmmConfig porte sur les OCTETS BRUTS du compte (`raw_sha256`). Les champs décodés sont publiés à côté.

Tests : 22 sur 22 sous `-W error`, avec `unshare -rn` et `env -i`.

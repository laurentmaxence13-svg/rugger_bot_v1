# w2arms.orch 0.1 — orchestration W2 des bras A0 (MASTER) et A1 (placebo) : un run et un dayj par fenêtre

**Ce que fait l'outil.** Il PLANIFIE et VÉRIFIE ; il n'exécute rien et n'envoie aucune requête. C'est l'option (a) du
Dossier B v1.8 (R02 2a6901f8).

**`plan`.** Pour la fenêtre i, l'outil fixe :
- **s0 :** s0_i = s0_1 + (i − 1) × 1 612 800 ;
- **collecte :** les bornes gelées `w1_collection.bounds(s0_i)` ; deux collectes successives se recouvrent de 407 313
  slots ;
- **chaîne dayj :** inchangée, sauf le ledger, qui passe par `w1aux.dayj_c1p1` (C1 + P1, paquet A2) ;
- **mois de quota :** le plafond par fenêtre vaut 1,5 × la mesure W1 de R03 (343 323 + 108 867 crédits) ; avec le
  pilote (6 363), on loge **2 fenêtres par mois** (k = 1 → 1 mois, 4 → 2, 15 → 8).

**`check`.** Contrôles effectués, sur un plan dont le sha est ancré :
- chaque manifeste de collecte a EXACTEMENT la fenêtre planifiée ;
- chaque état dayj a le s0 prévu ;
- les fenêtres sont consécutives.

**Déclarés, non modifiés (constantes W1 de dayj).**
- **DSR de l'étape evaluate :** N = 32 = P0 (25) + les 7 essais de la fenêtre. W1 et les autres fenêtres ne sont pas
  dans ce DSR. A0 ne conditionne pas le GO (§ 5).
- **Étape gate :** elle exige `--after-reading` pour chaque fenêtre. Qui signe cette lecture est une décision du
  propriétaire et de R02.

**Preuves.**
- `test_orch.py` : 5 tests réussis (16 au total avec `test_ce.py`).
- Défauts volontaires : 8 sur 8 détectés (`MUTATIONS_orch_v0_1.json`).

# w1loss 0.1 — ventilation descriptive des positions W1 (phase « rentabilité »)

**Écrit, non exécuté.** RUGGER 03 ne l'exécute qu'après l'audit et le PASS de RUGGER 02.

- **Garanties** : hors ligne, bibliothèque standard seulement, rien n'est affiché. L'outil ne modifie aucun chiffre
  W1, ne calcule aucun verdict et n'évalue aucune hypothèse gelée.
- **Entrées** : le `ledger.json` ancré, avec son sha256 vérifié, et le bundle L1, dont le sha256 doit être celui que
  le ledger a enregistré.
- **Sorties** : `VENTILATION_W1.json`, `VENTILATION_W1.md` et `SHA256SUMS.json`. Le dossier de sortie ne doit pas
  exister.
- **Liste fermée des tableaux (T0 à T8)** : voir la docstring de `w1loss/analysis.py`.
- **Pare-feu** : l'outil ne lit que l'essai `L1`, bras `master`, `reference` et `placebo_random`. Aucun déclencheur
  HW1 n'est calculé, et les classes d'âge s'arrêtent à ≥ 450 slots.
- **Contrôle** : les totaux T0 doivent égaler ceux de la lecture ancrée (`master.Q4_failure_factors.decomposition_lamports`
  et `others.placebo_random.decomposition_lamports`).

## Commande (R03)

    PYTHONPATH=<w1_loss_analysis> python -B -m w1loss.analysis --ledger <ledger.json> --ledger-sha256 <ancré> \
        --l1-bundle <run/bundles/L1.json.gz> --evaluation-min 467678545 --evaluation-max 469291345 --out <OUT>

## Preuves

- 5 tests avec des réponses connues, sous CPython 3.12.3 avec `-W error`.
- Défauts volontaires : 17 détectés sur 18 (`MUTATIONS_w1loss_v0_1.json`). Le seul non détecté,
  `cf_threshold_inclusive`, est équivalent au code d'origine : à r = r′, le facteur (1 − r′/r) vaut 0.

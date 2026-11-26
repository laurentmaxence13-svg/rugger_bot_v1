# lpbilan 0.1 — bilan d'un journal livepaper à un cut (hors ligne, 0 crédit)

RUGGER 01, 26/11/2026. Demande de R04 (01:12Z) : bilan T+6 h officiel du test en direct, même méthode et même
format que le bilan T+6 h de livesim. Les conventions C1–C8 ont été envoyées à R02 **avant toute lecture des
données** ; cet outil est écrit et testé sur des journaux synthétiques seulement. Le commit 8161ae2 (sans C9) n'a été ni
envoyé ni exécuté ; il est remplacé par celui-ci.

- Lecture seule du journal (et, en option, du grand livre de crédits et du journal d'appels). Aucun appel réseau.
- Code gelé importé, jamais modifié : `livesim.sim.metrics` et `by_hour` (livesim 0.3.2), `livepaper.journal`
  et `livepaper.cli._pct` (livepaper 0.1.2), `cpmmpilot.step1.assert_closed_vocabulary`.
- Conventions (détail dans la docstring de `bilan.py`) :
  - C1 : préfixe jusqu'au dernier STEP ≤ cut, chaîne vérifiée, tête au cut publiée ; le journal doit couvrir le cut.
  - C2 : seules les décisions du préfixe comptent ; sans EXIT dans le préfixe = ouverte, jamais valorisée.
  - C3 : heure de sortie = heure du STEP qui écrit l'EXIT.
  - C4–C6 : latences, interruptions, crédits ; crédit au cut = NON MESURÉ.
  - C7–C8 : identité de la décomposition à 1 lamport près ; vocabulaire fermé.
  - C9 (ajout R02 01:17Z) : état G-0 de chaque pool au cut (admis, raisons, non admis depuis) et défauts déclarés
    (`--notes`, une ligne par défaut, ex. D13) publiés tels quels.
- Précision R02 sur C1 : « ≤ cut » inclut le STEP dont receipt_time vaut exactement le cut (cohérent avec livesim).
- Sorties : `BILAN.json`, `BILAN.md`, `DECOMPOSITION.md`.
- Commande : `python -B -m lpbilan.bilan --journal J --cut 1795653600 [--ledger F] [--calls F] [--notes F] --out DIR`
  (chemins : lpbilan, livepaper 0.1.2, et les dépendances de livepaper).
- Tests : 17/17 (livepaper 0.1.2 + livesim 0.3.2 sur le chemin). Mutants : 30/30 (`MUTATIONS_lpbilan_v0_1.json`).
- PAPER_LIVE_DEMO : jamais un trade du Master, jamais compté pour 50/20, aucun verdict.

# lpbilan 0.1 — bilan d'un journal livepaper à un cut (hors ligne, 0 crédit)

RUGGER 01, 26/11/2026. Demande de R04 (01:12Z) : bilan T+6 h officiel du test en direct, même méthode et même
format que le bilan T+6 h de livesim. Les conventions C1–C8 ont été envoyées à R02 **avant toute lecture des
données** ; cet outil est écrit et testé sur des journaux synthétiques seulement.

- Lecture seule du journal (et, en option, du grand livre de crédits et du journal d'appels). Aucun appel réseau.
- Code gelé importé, jamais modifié : `livesim.sim.metrics` et `by_hour` (livesim 0.3.2), `livepaper.journal`
  et `livepaper.cli._pct` (livepaper 0.1.2), `cpmmpilot.step1.assert_closed_vocabulary`.
- Conventions (détail dans la docstring de `bilan.py`) :
  - C1 : préfixe jusqu'au dernier STEP ≤ cut, chaîne vérifiée, tête au cut publiée ; le journal doit couvrir le cut.
  - C2 : seules les décisions du préfixe comptent ; sans EXIT dans le préfixe = ouverte, jamais valorisée.
  - C3 : heure de sortie = heure du STEP qui écrit l'EXIT.
  - C4–C6 : latences, interruptions, crédits ; crédit au cut = NON MESURÉ.
  - C7–C8 : identité de la décomposition à 1 lamport près ; vocabulaire fermé.
- Sorties : `BILAN.json`, `BILAN.md`, `DECOMPOSITION.md`.
- Commande : `python -B -m lpbilan.bilan --journal J --cut 1795653600 [--ledger F] [--calls F] --out DIR`
  (chemins : lpbilan, livepaper 0.1.2, et les dépendances de livepaper).
- Tests : 13/13 (livepaper 0.1.2 + livesim 0.3.2 sur le chemin). Mutants : 25/25 (`MUTATIONS_lpbilan_v0_1.json`).
- PAPER_LIVE_DEMO : jamais un trade du Master, jamais compté pour 50/20, aucun verdict.

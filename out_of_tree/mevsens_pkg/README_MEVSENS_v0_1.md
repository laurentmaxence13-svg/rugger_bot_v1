# mevsens 0.1 + protocole PAPER_LIVE v0.1 — tâche P3-d (conception)

RUGGER 01, 22/11/2026. Rien n'est lancé.

## mevsens 0.1 — sensibilité N-6 (MEV, sandwich, tip Jito)

- Le modèle est paramétré sur les états de courbe des fixtures publiques. **Il n'est calibré sur aucune donnée,
  W1 compris** : chaque paramètre est un scénario déclaré.
- **Sandwich de notre achat.** Avec la garde (2 % en primaire), le pire front-run laisse notre remplissage EXACTEMENT
  au minimum garanti : la perte est bornée par la bande de la garde. Le front-run maximal est trouvé par recherche
  binaire exacte : un lamport de plus, et l'achat échoue. Sans garde, seul le capital déclaré de l'attaquant borne
  la perte.
- **Sandwich de notre vente.** Pas de garde en primaire : un front-run de k fois nos jetons.
- **Tip Jito.** Un coût pur par transaction, publié à part. Le modèle ne prétend pas que le tip supprime le
  sandwich.
- **Grille figée de 6 scénarios** (`SCENARIOS`) ; tout autre scénario est refusé.
- **Tests et mutants** : 4 tests, 10/10 mutants (`MUTATIONS_mevsens_v0_1.json`).

## Protocole PAPER_LIVE v0.1 (BROUILLON, `PROTOCOLE_PAPER_LIVE_v0_1.md`)

- Il couvre : l'objet, les étiquettes PAPER_LIVE et HISTORICAL_REPLAY, la durée (fenêtre fixe de 14 j, proposée),
  les critères techniques S-1 à S-6, le rapprochement (le rejeu doit être identique à l'octet près), la
  journalisation et les arrêts durs.
- Les **prérequis du propriétaire** (D-1 à D-7) forment une liste à part.
- Les valeurs chiffrées sont des propositions, à fixer par R02 avant toute donnée.

Commande des tests, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<landslip_pkg>:<mevsens_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <mevsens_pkg>/mevsens/tests -p no:cacheprovider -q -W error`

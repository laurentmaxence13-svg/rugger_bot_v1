# livepaper 0.1.2 — 0.1.1 + le sha du texte signé (une ligne)

RUGGER 01, 25/11/2026. Demande de R02 (17:43Z), après la signature du propriétaire : event a60ed568, 17:40:23Z,
session R03, vérifiée à la source et ancrée par R02.
- **Code : une seule ligne change** (`source.py`) :
  `AUTHORIZED_TEXT_SHA256 = frozenset({'1366025b6290c0a748c2190eebc5e3ee078a25868ef005591710b23658ebface'})`.
  Le reste est livepaper 0.1.1 (ff2a32e, PASS DE CODE R02), octet pour octet.
- **Test** (`test_the_signed_text_opens_the_transport_and_nothing_else_does`) :
  - `tests/data/AUTORISATION_LIVEPAPER.txt` est le fichier de R03 (cca08a7, 1 694 octets, sans saut de ligne final) ;
    son sha doit valoir le sha autorisé ;
  - seul ce fichier ouvre `LiveTransport`, avec un `opener` factice : aucun appel réseau dans les tests ;
  - un octet de plus donne `authorization_not_anchored` ; une clé dans l'URL est refusée.
- **Mutant ajouté** : `text_not_authorized` (le jeu redevient vide).
- Tests : 26/26, avec livesim 0.3.1 et avec 0.3.2. Mutants : voir `MUTATIONS_livepaper_v0_1_2.json`.
- Rien n'est appelé avant l'audit de R02 et ses GO : `collect-gsfa` (≈ 75 crédits), puis `ordercheck`, puis l'ancrage,
  puis `run --ordercheck-sha`.

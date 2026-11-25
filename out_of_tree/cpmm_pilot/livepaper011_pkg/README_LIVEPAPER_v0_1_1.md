# livepaper 0.1.1 — la version exécutable (réserves de R02 sur la 0.1)

RUGGER 01, 25/11/2026.
- livepaper 0.1 : commit 3c87b24, MANIFEST 8060453e, PASS DE CODE de R02 (16:24Z) avec des réserves.
- Pour tout le reste (boucle, journal, preuve, commandes, limites), voir `README_LIVEPAPER_v0_1.md` dans `livepaper_pkg`.
- R02 l'a dit (16:24Z) : il n'y aura qu'**une seule version exécutable**.
- **Tant que `AUTHORIZED_TEXT_SHA256` est vide, aucun appel réseau n'est possible.** Le sha COMPLET du texte du
  propriétaire signé, transmis par R02, y entre par la livraison finale de la 0.1.1, auditée par R02.

## Réserves de R02, et rien d'autre

| # | Réserve | 0.1.1 |
|---|---|---|
| 1 | fill.py recopie l'arithmétique gelée | Les tests d'identité avec `cpmmprereg.exit_point` et `cpmmcost.position` sont conservés |
| 2 | Le mutant `tp_strict` survit | Test de frontière : toute vente vaut exactement 102 000 000 lamports (`CC._sell_on` remplacé dans le test). La règle gelée et l'ancre live sortent toutes deux au TP. Le mutant est détecté |
| 3 | `bot.p4.historical_research_replay` est hors MANIFEST | `source.check_imports` vérifie son sha (`372385bd…`, wt_w1 e2143e6) au démarrage de `run` et de `collect-gsfa`. Un écart donne un refus |
| 4 | sha du texte signé et de l'ORDERCHECK | Texte : `AUTHORIZED_TEXT_SHA256`, rempli à la livraison finale (sha complet attendu de R02). ORDERCHECK : **argument** `run --ordercheck-sha`, comme `--eligible-sha` (R02 16:24Z) ; la constante de la 0.1 est retirée. Le fichier doit avoir ce sha, sinon refus |
| 5 | `test_commands` suppose livesim 0.3.1 | La variante suit `livesim.SCHEMA`. 25/25 avec livesim 0.3.1 et avec livesim 0.3.2 sur le chemin |

## Ordre de lancement (R02, 16:24Z)

1. Le propriétaire signe le texte.
2. Livraison de la 0.1.1 avec le sha du texte ; audit par R02.
3. R03 lance `collect-gsfa` (≈ 75 crédits, compteur unique 25 000 / 24 500).
4. `ordercheck`, puis ancrage par R02.
5. GO de R02, puis `run --ordercheck-sha <ancré>`.

## Validation

- 25 tests : les 23 de la 0.1 adaptés (`--ordercheck-sha`), plus la frontière du TP et le contrôle de `hrr`.
- Mutants : 75/75 détectés (`MUTATIONS_livepaper_v0_1_1.json`), dont `tp_strict`, le contrôle de `hrr` et `--ordercheck-sha`.
- Le sha du texte (1366025b6290…) n'est PAS dans `AUTHORIZED_TEXT_SHA256` : il n'y entrera qu'après la confirmation de
  la signature par R02 et sa vérification à la source.

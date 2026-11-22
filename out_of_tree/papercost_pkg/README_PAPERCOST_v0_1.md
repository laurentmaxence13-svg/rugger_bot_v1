# papercost 0.1 — moteur PAPER « coûts complets », paquet NOUVEAU (tâche P3-c)

RUGGER 01, 22/11/2026. Ce moteur applique les définitions N-1 à N-8 et les décisions de R02 (20:28Z, renvoyées à
21:10Z ; audit 0167b2d1).

- Le code gelé est intact : `StreamTrade` de paperstream 0.4 est SOUS-CLASSÉ, avec son sha e86f66b0 vérifié ; le
  `hrr.run_replay` gelé est appelé tel quel ; seul le moteur d'échange est remplacé, puis rétabli.
- HISTORICAL_REPLAY seulement. Fixtures seulement : **rien n'est appliqué à W1**.

## Moteur (`CostedTrade`, `Options`)

| Poste | Primaire | Sensibilité |
|---|---|---|
| N-5 garde d'achat (`landslip.guard`) | 20 000 ppm sur la sortie exacte à l'état de décision ; sous le seuil : échec facturé, aucune entrée, aucune relance | 50 000 ppm |
| H-1 (ordre dans le slot d'atterrissage) | Achat : le moins de jetons ; vente : la valeur la plus basse, entre les états avant et après les événements réels du slot | — |
| N-3 / N-4 échecs | 0 | 1 par transaction, ou une probabilité déclarée tirée de façon déterministe ; au plus 3 ; chaque renvoi atterrit +4 slots plus tard, chaque échec est facturé |
| Garde de vente | aucune | 50 000 ppm, renvoi +4 slots, au plus 3 fois, puis vente sans garde |

Les options neutres (`Options.neutral()`) redonnent EXACTEMENT le moteur gelé : même `TradeResult` pour 8 stratégies
sur les 3 pools, et même bundle W1 L1, octet pour octet, sur les fixtures.

## Coûts (`row_costs`, sur les lignes au format gelé)

- **N-1 / N-2** : deux modes publiés côte à côte.
  - `rent_lost` (primaire, comme C-B) : le loyer de 2 039 280 est perdu.
  - `closed` (closedacct 0.2) : (échecs + 1) × 105 000, le loyer est rendu ; après 3 échecs, loyer perdu + 3 frais.
  - Une position migrée ou non valorisable : loyer perdu dans les deux modes.
- **N-3** : 105 000 par tentative échouée.
- **N-7** : la rente WSOL est rendue dans la transaction ; son calcul supplémentaire est un forfait DÉCLARÉ de
  5 000 lamports par transaction en SOL. En sensibilité : 105 000, une fermeture séparée.
- **N-8** : une position ouverte en fin de données ou de fenêtre est MARQUÉE à sa valeur de vente exacte, moins la
  transaction de sortie et le loyer du mode, et COMPTÉE dans le net.
- **Positions non valorisables** (migration, divergence) : comptées à valeur NULLE, le pire cas.
- **Échec de garde** : compté, à −105 000.
- **N-6** (MEV, Jito) : non modélisable hors ligne, c'est une limite déclarée.
- Rendement sur la mise ; décomposition à résidu nul. Le mode `frozen_assumption`, réservé à la preuve d'identité,
  redonne la valeur gelée.

## Ce qui se déclenche réellement sur les fixtures

- La garde de 2 % refuse au moins 5 entrées en début de courbe ; 5 % en admet une partie.
- H-1 réduit les jetons dans au moins 5 cas, et la valeur de vente dans au moins 5 cas.
- Aucune baisse de 5 % ne suit une décision de sortie : la relance de la garde de vente est donc démontrée avec un
  seuil de test de 1 ppm, introduit par monkeypatch dans le test seulement.

## Tests et mutants

- 21 tests ; mutants 20/20 (`MUTATIONS_papercost_v0_1.json`).

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<closedacct_pkg>:<landslip_pkg>:<papercost_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <papercost_pkg>/papercost/tests -p no:cacheprovider -q -W error`

## Points à valider par R02

1. Le forfait WSOL de 5 000 par transaction (déclaré ; sensibilité 105 000).
2. Une position non valorisable est comptée à zéro, et non exclue.
3. À la fin des données, une vente en attente atterrit sans garde.
4. H-1 est actif en primaire sur les deux jambes.

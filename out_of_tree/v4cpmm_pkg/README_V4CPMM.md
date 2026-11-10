# v4cpmm 0.1 — pont expérimental simulateur V4 → pool CPMM

RUGGER 01, 2026-11-10. **Statut : expérimental, non ancré, non validé sur des swaps réels.**

`v4sim` 0.2 (ancré par RUGGER 02, empreinte de code 2fe085a3…) est **importé et appelé, jamais modifié**.
`v4cpmm.bridge.replay` a la même signature que `v4sim.engine.replay` et rend le même résultat, inchangé,
avec un attribut de plus : `result.cpmm`. Ce bloc décrit la vente, sur le pool CPMM réel, d'une position
que `v4sim` laisse `migrated_unpriced`. La comptabilité gelée continue de dire « non valorisée ».

## Chaîne couverte
détection → sélection → achat → détention (moteur V4) → migration → **vente sur le pool CPMM** → P&L net :
- valeur de la vente = sortie exacte du programme sur l'état du pool au point d'atterrissage (impact
  propre et frais de trading / créateur compris) ;
- latence : `latency_slots` après la création du pool (`at_open`), ou échéance d'horloge de la
  stratégie + `clock_exit_latency_s` (`strategy_clock`) ;
- transactions non incluses (tirage déterministe de `v4sim`), limite de glissement, nouvelles
  tentatives : chaque échec est facturé et tracé ;
- P&L net = reçu − dépensé − tous les frais de transaction (achat, échecs, vente).

## Règle : aucun nombre sans donnée lue
Le bloc porte un statut `unpriced_*` et **aucun montant** si manque : la chronologie du pool, son point
de création, un état du pool à l'atterrissage, ou un taux de frais (donné depuis l'AmmConfig, ou lu
causalement dans les swaps journalisés avant l'atterrissage). Une limite de glissement qui ne peut pas
être appliquée (aucune valeur attendue calculable à l'envoi) est signalée dans le bloc.

## Approximations déclarées (répétées dans chaque bloc)
- X-1 les réserves CPMM réelles sont utilisées telles qu'observées ; la valeur avec la demande que notre
  achat de courbe a déplacée vers le pool est publiée à côté, et la plus basse des deux est retenue ;
- X-2 après la migration, deux sorties seulement (à l'ouverture du pool, ou à l'échéance d'horloge) :
  les stops ne sont pas évalués sur les prix CPMM ;
- X-3 notre vente est notre seul trade sur le pool : aucun swap réel n'est rejoué après elle ;
- X-4 côté des frais de créateur inconnu, ou parts protocole / fonds inconnues : valeur défavorable au
  vendeur ;
- X-5 formats et arithmétique vérifiés sur données synthétiques seulement (A-12 non passé) ;
- X-6 l'ordre dans le slot d'atterrissage est inconnu : la valeur avant et après les swaps réels de ce
  slot sont publiées, la plus basse est retenue.

Chaque bloc porte `creditable: false` et la liste `credit_blockers` : rien n'est créditable avant A-12.

## Tests
    cd <arbre gelé aff97638>
    PYTHONPATH=<v4cpmm_pkg>:<cpmmx_pkg>:<v4sim_pkg> python -B -m pytest -q <v4cpmm_pkg>/v4cpmm/tests -p no:cacheprovider -W error
25 tests (dont 8 de mutation), Python 3.12 et 3.11, hors réseau, sur une courbe synthétique qui migre
pendant la détention.

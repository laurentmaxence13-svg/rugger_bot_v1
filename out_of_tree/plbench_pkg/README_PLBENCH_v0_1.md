# plbench 0.1 — banc d'essai PAPER_LIVE de bout en bout sur fixtures (tâche PL-1)

RUGGER 01, 23/11/2026. Étiquette **SIMULATED_FEED**, jamais PAPER_LIVE. Aucune connexion, aucun envoi, aucune signature.
Aucun cycle ne peut compter pour 50/20 : `cycle_receipts = 0`.

## Chaîne

Les étapes sont celles du protocole PAPER_LIVE v0.2, jugé CONFORME par R02 :

1. **Flux simulé.** Ce sont les événements des fixtures, livrés un par un. On peut y injecter des défauts : perte,
   doublon, inversion dans un slot, reconnexion déclarée.
2. **rtgate 0.2**, sous-classé pour que son moteur soit `papercost.CostedTrade`. Le code audité est inchangé.
3. **L'appel L1 gelé** (`hrr.run_replay`, MASTER, référence, placebo). Seul `hrr.replay` est remplacé.
4. **Journal et rapprochement.** Chaque ligne est décomposée à résidu nul, dans les deux modes, avec le net gelé à
   côté.
5. **Contrôles S-1 à S-6**, aux seuils fixés par R02.

**Pool INCOMPLET.** Une position ouverte y est comptée à valeur 0 (S-1). La source rtgate reste HISTORICAL_REPLAY, ce
que le flux de fixtures est vraiment.

## Preuves

- **Identité.** Options neutres et flux propre redonnent le bundle L1 gelé, octet pour octet. Le moteur derrière la
  porte est bien `CostedTrade`.
- **Flux propre.** S-1 à S-6 passent ; S-2 rejoue le même flux, qui est identique à l'octet près.
- **Défauts réparables** (inversion, doublons) : le résultat est identique.
- **Événement perdu** : le pool est INCOMPLET, S-1 tombe à 2/3 et échoue.
- **Position ouverte dans un pool INCOMPLET** : elle est valorisée à 0 et comptée. Sur les fixtures, la politique gelée
  n'ouvre jamais de position avant un trou possible : la règle est donc montrée sur une entrée forcée.
- **Échecs attendus des contrôles** :
  - S-3 échoue si la latence n'est pas mesurée (fermé par défaut) ou si son p95 vaut 5 slots ;
  - S-5 échoue si la série est périmée ;
  - S-4 échoue si un module de signature est présent ;
  - S-2 échoue si l'empreinte du code change pendant le run.
- **Arrêts durs.** Les 8 arrêts du § 7, dont l'ajout (a), sont testés un par un.
- **Tests et mutants** : 19 tests ; 17/17 mutants, avec la garde de base.

Valeurs à fournir par le propriétaire : `DX_VALEURS_PROPRIETAIRE_v0_1.md`.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<paperstream_pkg>:<closedacct_pkg>:<landslip_pkg>:<papercost_pkg>:<rtgate_pkg>:<plbench_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <plbench_pkg>/plbench/tests -p no:cacheprovider -q -W error`

# lpcompare 0.1 — test PAPER en direct arrêté ↔ livesim, décision par décision

RUGGER 01, 26/11/2026. Demandé par R04 (12:16Z). Conventions déclarées à R02 avant toute lecture des données. R02 les
a acceptées à 12:23Z, sous les conditions C-1 à C-7. Nouveau paquet hors ligne, 0 crédit, sans réseau. Aucun code
gelé n'est modifié : livesim 0.3.2, cpmmgen2, cpmmcost, cpmmrecon et livepaper.journal sont importés tels quels.

## Ce que fait le paquet

- **now commun** : `receipt_time` du dernier STEP du journal. Rien après now n'est lu, d'aucun côté (C-6, « ≤ now »).
- **Trois vues** :
  - L : le journal live, tel qu'il a été enregistré.
  - P : le calcul a posteriori sur les pages live.
  - S : livesim sur ses propres pages (blockTime ≤ now), avec le start et la graine de livesim.
  - S est restreint aux décisions de [départ live ; now].
- **Clé** : (pool, signature du déclencheur). Catégories : les deux, live seul, livesim seul, a posteriori seul.
- **Appariement « décalé »** : un live seul et un livesim seul du même pool sont rapprochés si |Δt| < 3 600 s. Le
  seuil est figé. Les comptes à clé stricte sont publiés à part (C-4).
- **Raison de chaque divergence** : arbre déterministe déclaré. Raisons possibles :
  - exclusion G-0 du live ;
  - transaction absente des pages live (étiquette D13) ou de la collecte livesim ;
  - signal décidable a posteriori mais non décidé en direct ;
  - décision live non confirmée a posteriori ;
  - chaîne de signaux différente ;
  - latence du live, règle de sortie, troncature.
- **Témoin** : publié à part. Une position live et une position livesim ne sont appariées que sur le même pool et le
  même swap d'entrée. Mention : « tirage au now de la comparaison, non comparable au T+24 h » (C-3).
- **Trois blocs publiés** :
  - le segment conforme [18:40:00Z ; 20:10:03Z[ ;
  - « conforme à l'entrée, sortie hors protocole », à part et jamais additionné au segment conforme (C-2) ;
  - le segment hors protocole [20:10:03Z ; now], qui porte la mention de D13 et de D14 (C-1).
- **En tête de COMPARE.md** : la mention D15/getSlot de R02 (C-1) et la limite L4 (C-5).
- **Contrôle T+24 h** : pour les primaires seulement. Chaque ligne S doit retrouver sa ligne du LIVESIM.json ancré.
  Une ligne fermée à now doit être identique à sa ligne T+24 h ; sinon le paquet s'arrête en erreur.
- **Annexe** : les transactions présentes d'un côté seulement, par pool et par segment.
- **Résultat** : COMPARE.json et COMPARE.md. Labels PAPER_LIVE_DEMO et PAPER_SIMULATION.
  `counts_for_operational_master = false`, verdict null, aucune conclusion économique. Les vocabulaires fermés sont
  vérifiés.

## Commande

Hors ligne (`unshare -rn`). Le chemin doit contenir livepaper 0.1.2 (le code qui a tourné), livesim 0.3.2 et
cpmmrecon 0.1.

```
python -B -m lpcompare.compare --live-dir LIVEPAPER_20261125T181913Z --journal-sha <ancré> \
  --collect LIVESIM_20261125T113851Z --list-l LIST_L.json --eligible ELIGIBLE.json --eligible-sha <ancré> \
  --livesim-json LIVESIM.json --livesim-json-sha <ancré> --out DIR
```

Contrôles avant tout calcul :
- les sha du journal, de ELIGIBLE et de LIVESIM.json ;
- le départ live 1795632000 ;
- POOLS_RUN issu du même ELIGIBLE ;
- l'univers identique des deux côtés ;
- les pools et les b3 du START.

## Vérification

- Tests : 26/26 avec `-W error`, sur des pools synthétiques. Un même marché est écrit au format de la collecte livesim
  et rejoué par le moteur livepaper 0.1.2 depuis un départ plus tardif.
- Mutants : premier tour 57/58. Le survivant (`row_exit_time_ignored`) est fermé par un test de bord et a été rejoué seul : il est détecté. Un deuxième tour complet a été interrompu sur décision de R04 (`MUTATIONS_lpcompare_v0_1.json`).
- Aucune donnée réelle n'a été lue. Décision de R04 (13:31Z) : une seule exécution, que R02 recoupe par son propre calcul sur les décisions concernées.

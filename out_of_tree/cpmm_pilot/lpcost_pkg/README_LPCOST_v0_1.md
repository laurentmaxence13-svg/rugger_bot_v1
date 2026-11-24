# lpcost 0.1 — modèle de coût PAPER d'une position de fournisseur de liquidité (CPMM 0,25 %)

RUGGER 01, 24/11/2026.
- Origine : décision R04-3 (24/11, 20:52Z, par délégation du propriétaire) ; principe N1 retenu, PAPER uniquement.
- Base : dossier N1 b7d5d9c.
- Hors ligne : pools synthétiques seulement, aucune donnée collectée lue. Soumis à l'audit de R02.
- Étiquettes : `MASTER_RESEARCH_PAPER`, `HISTORICAL_REPLAY`, `LP_SIDE_RESEARCH`. Ce n'est jamais un trade du Master
  opérationnel, et cela ne compte jamais pour 50/20.

## Les cinq étapes (`lpcost/model.py`, `lp_position`)

Position de 0,1 SOL sur un pool-jour ; décision à l'heure de début ; atterrissage après la latence d'horloge gelée.

| Étape | Règle |
|---|---|
| 1. Échange d'entrée | 0,05 SOL achète le jeton de base sur le PIRE des deux états d'atterrissage (H-1, comme cpmmcost). La garde de cpmmcost (20 000 ppm) compare le remplissage à la sortie sur l'état de décision : un refus est facturé et termine la position |
| 2. Dépôt | Proportionnel aux réserves des fournisseurs (parts protocole et fonds exclues par `timeline.after_swap`). Part s = min(base détenue / B, quote détenue / Q) ; montants arrondis par excès ; le reste est gardé |
| 3. Détention | Notre liquidité suit le pool. Chaque événement LP d'un AUTRE fournisseur entre l'entrée et la sortie ajuste s : un dépôt d'une fraction f divise s par (1 + f), un retrait par (1 − f) |
| 4. Sortie | Retrait de s × réserves, arrondi par défaut, sur le pire état de sortie. Puis vente de tout le jeton de base au pire des 4 états : 2 limites d'atterrissage, avec et sans notre retrait |
| 5. Net | SOL reçus − 0,1 SOL − transactions − loyer perdu |

**Identité exacte du net (en entiers).**
- net = hold_pnl + lp_vs_hold − transactions − loyer perdu.
- hold_pnl : détention des jetons acquis, vendus par la même règle, moins la mise.
- lp_vs_hold : chemin LP moins chemin de détention, soit les frais perçus moins la perte d'inventaire (LVR réalisée)
  et les arrondis.
- `fees_earned_estimate` et `inventory_loss_estimate` sont DESCRIPTIFS : s × la part LP du frais de chaque swap,
  valorisée au spot de ce swap.

**Transactions** (compte fermé, 105 000 lamports gelés) :
- échange d'entrée (1 + échecs d'achat), dépôt, retrait, échange de sortie (1 + échecs de vente) ;
- fermeture WSOL ;
- nettoyage des comptes jeton et LP (1 + échecs).
- Soit **6 transactions = 630 000 lamports = 0,63 % de la mise** en primaire. Le dossier N1 en comptait 4 : ce
  module le corrige.
- Après 3 nettoyages échoués, les 2 loyers sont perdus.

**Simplifications déclarées.**
- Nos propres échange et dépôt ne sont pas rejoués dans les états suivants : notre part est infime, 0,05 SOL dans un
  pool ≥ 100 SOL. Les règles du pire état en couvrent le coût sur les deux jambes.
- Un événement LP après le dernier swap avant un atterrissage n'est pas daté. cpmmcost refuse alors l'état
  (`lp_change_at_the_landing_point`), et le pool-jour est non valorisable.
- Le dépôt se fait aux réserves d'avant notre achat : le reste en jeton de base est toujours nul (voir le mutant
  équivalent).

## Validation

- 13 tests sur pools synthétiques. Ils couvrent :
  - le décompte des transactions ;
  - l'identité exacte ;
  - un recalcul indépendant des 5 étapes (arrondis, pires états) ;
  - un marché équilibré, où le fournisseur gagne les frais, et une tendance, qui coûte de l'inventaire ;
  - un jour sans swap ;
  - les événements LP d'autrui (pool doublé ou divisé) ;
  - l'estimation des frais ;
  - la garde : refus à 2,9 % ; accepté à 50 000 ppm et à 1 % ;
  - échecs, loyer et entrées.
- 29 mutants sur 29 détectés. Un mutant ÉQUIVALENT (`leftover_base_lost`) est retiré et justifié dans
  `MUTATIONS_lpcost_v0_1.json`.
- Commande, cwd wt_w1, sans `-I` :
  `env -i PYTHONPATH=<chemin commun des paquets>:<barmap_pkg>:<cpmmgen3_pkg>:<lpcost_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <lpcost_pkg>/lpcost/tests -p no:cacheprovider -q -W error`

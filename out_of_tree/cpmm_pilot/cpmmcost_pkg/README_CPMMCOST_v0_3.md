# cpmmcost 0.3 — garde de glissement de l'achat CPMM (amendement A1 (c) de R02) et latence de 10 slots déclarée

RUGGER 01, 23/11/2026. Base : cpmmcost 0.2 (a611621, PASS R02). Le reste du modèle est inchangé. Aucune donnée CPMM
n'existe ni n'est lue : tests sur pools synthétiques seulement.

## 1. Garde de l'achat (A1 (c), R-0.3)

- **Minimum de jetons** = sortie exacte de l'achat sur l'état JUSTE APRÈS le swap de décision × (1 − 20 000 ppm).
- On compare avec le remplissage H-1, c'est-à-dire le moins favorable des deux états du slot d'atterrissage. S'il est
  en dessous du minimum, l'achat échoue (`status = guard_failed`) :
  - (échecs déjà comptés + 1) × 105 000 lamports sont facturés ;
  - aucun compte n'est créé, il n'y a ni entrée ni relance ;
  - `net_return` = −frais / mise.
- **Sensibilité** : 50 000 ppm. `None` redonne exactement la 0.2 (testé). Tout autre seuil est refusé.
- **La vente reste sans garde** (testé).
- **`pilot_verdict`** :
  - les essais refusés restent dans la moyenne, car leurs frais sont payés ;
  - ils ne sont PAS des entrées. Les planchers de G-1 (30 entrées, 20 pools) ne comptent que les positions entrées,
    ce qui est plus strict et n'abaisse rien ;
  - sont publiés : `n`, `n_entered`, `pools_entered`, `guard_failed`.
- **Hypothèse déclarée.** Un achat refusé ne coûte que sa transaction. Le WSOL n'est pas facturé à part : l'enveloppe
  WSOL est dans la même transaction, qui est annulée. **À valider par R02.**

## 2. Latence de 10 slots (pour la condition « net > 0 à 10 slots » de A1 (a))

- Paramètre `latency_slots` : 4 (primaire) ou 10 (sensibilité). Toute autre valeur est refusée.
- Il décale ensemble :
  - l'achat ;
  - chaque renvoi, de l'achat comme de la vente, y compris après la sortie d'horloge.
- Le point de sortie déclaré (TP/SL ou horloge) est fourni par l'appelant, avec la même latence (cpmmprereg 0.2).

## 3. Preuves

- 22 tests, dont 7 nouveaux :
  - la garde ;
  - la frontière exacte de la garde pour les deux seuils (balayage) ;
  - la référence, qui est l'état après la décision ;
  - la vente sans garde ;
  - les essais refusés dans `pilot_verdict` ;
  - la latence de 10 slots ;
  - le renvoi d'horloge.
- **47/47 mutants détectés** (15 nouveaux), avec la garde de base : la copie non mutée doit passer d'abord.

## 4. Commande

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmcost_pkg>/cpmmcost/tests -p no:cacheprovider -q -W error`

## 5. Ce qui reste bloqué (propriétaire)

- La source de la liste U-2.
- Le GO de l'étape 0, puis celui de l'étape 1.

Sans eux : WAIT.

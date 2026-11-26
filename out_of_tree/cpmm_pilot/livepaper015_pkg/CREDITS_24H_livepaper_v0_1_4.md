# livepaper 0.1.4 — chiffrage des crédits sur 24 h, méthode par méthode (voie (i-a) gsfa_rank, 3 pools, poll 30 s)

RUGGER 01, 26/11/2026, demande de R04 (01:34Z).
- Source : snapshot **ancré** 1e86638 (J 734c15bd, L 1502470f, C d9f11e85). Lecture seule.
- Recoupement sur le dossier final 73aef7c, ancré par R02 à 01:34:41Z (J 17fa9372, L 2db54593, C b4cb1593 ; sha de
  R01 identiques à ceux de R02, confirmés à 01:56Z).
  - 821 sondages, 1 154 transactions reçues, 4 514 crédits : getSlot 821, GSFA 2 538 (dont 76 pour la collecte),
    getTransaction 1 155.
  - Par sondage : 2,998 GSFA, 1,407 getTransaction.
  - Mêmes 6 heures pleines (139 / 171,7 / 213 transactions) : la projection ci-dessous ne change pas.
- Coût unitaire (grand livre cpmmpilot) : 1 crédit par appel pour `getSlot`, `getSignaturesForAddress` et
  `getTransaction` ; 10 pour `getTransactionsForAddress` (non utilisé en (i-a)).

## Mesuré (18:40Z → 01:14Z, 784 sondages complets)
| Méthode | Débité | Par sondage | Origine |
|---|---|---|---|
| getSlot | 784 | 1,000 | un par sondage complet |
| getSignaturesForAddress (marche) | 2 350 + 1 en échec | 3,0 | un par pool (3) ; jamais de seconde page (< 1 000 signatures en 30 s) |
| getSignaturesForAddress (collecte de l'ordercheck) | 76 | — | une seule fois, avant la marche |
| getTransaction | 1 112 | 1,418 | une par transaction nouvelle : 1 111 reçues + 1 perdue (D13) |
| **Total** | **4 323** | | |

Transactions reçues par heure pleine, 3 pools : de 139 à 213 ; moyenne des 6 heures pleines : 171,7.

## Projection sur 24 h (2 880 sondages ; 0.1.4)
| Méthode | Bas | Central | Haut | Règle |
|---|---|---|---|---|
| getSlot | 2 880 | 2 880 | 2 880 | 1 par sondage |
| getSignaturesForAddress | 8 640 | 8 640 | 8 640 | 3 pools × 1 par sondage |
| getTransaction | 3 336 | 4 121 | 5 112 | heures pleines mesurées 139 / 171,7 / 213, × 24 |
| Rattrapage borné (0.1.4) | 0 | 0 | 110 | au plus 1 GSFA + 10 getTransaction = 11 par cassure ; 10 cassures supposées en haut |
| Relecture d'une réponse tronquée (0.1.4) | 0 | 0 | 10 | +1 par troncature ; aucune mesurée (le type de l'erreur de D13 est NON MESURÉ) |
| **Total de la marche** | **14 856** | **15 641** | **16 752** | |
| Collecte de l'ordercheck (une fois) | 76 | 76 | 76 | si elle est refaite |

## Lecture
- Avec un grand livre neuf (plafond 25 000, arrêt dur 24 500), 24 h tiennent avec 7 700 à 9 600 crédits de marge.
  Ce grand livre neuf supposerait un nouveau texte du propriétaire. L'actuel est à 4 514 (dossier final 73aef7c).
- Chaque pool de plus coûte 2 880 GSFA par 24 h, plus ses transactions.
- getTransaction dépend de l'activité des pools. Le haut de fourchette est la plus forte heure mesurée, pas un maximum
  garanti.
- La marche ne peut pas dépasser le plafond : elle est arrêtée à 24 500 (`credit_hard_stop_24500`), débit inscrit
  avant chaque requête.

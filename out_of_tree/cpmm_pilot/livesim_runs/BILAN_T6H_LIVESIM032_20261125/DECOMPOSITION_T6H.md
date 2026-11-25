# Décomposition des positions du bilan à T+6 h (descriptive)

RUGGER 01, 25/11/2026. Demande de R04 (19:47Z), selon le message du propriétaire « Notre état d'esprit » :
« chaque perte doit être comprise ».

- **Source** : LIVESIM.json `d586e170…` (bilan livesim 0.3.2 à T+6 h, commit 5b95c52, identique au bilan de R02).
- **Méthode** : lecture seule de `journal` ; aucun calcul nouveau de rendement, 0 crédit, hors ligne.
- **Décomposition** : celle du modèle gelé (cpmmcost 0.3.1 `decomposition_share_of_stake`, en % de la mise de
  0,1 SOL).
  - Pour chaque position, contrôle : brut + frais de pool + impact + frais fixes = net, à moins de 1 lamport près.
- **Frais fixes** : transactions d'achat et de vente (2 × 105 000), fermeture WSOL (105 000), nettoyage du compte
  (105 000), loyer perdu (0) ; soit 420 000 lamports = 0,42 % de la mise.
- **n insuffisant** : 6 positions G2-3 et 5 témoins. Aucune conclusion ni inférence ; c'est une description.

## G2-3 : 6 positions fermées (+ 1 ouverte, non valorisée)

| # | Pool | Décision | Sortie (durée) | Brut (mouvement de prix) | Frais de pool | Impact | Frais fixes | Net (% mise) | Net (lamports) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR | 11:48:08Z | horloge (1801 s) | -0.0944 % | -0.4991 % | -0.0522 % | -0.4200 % | -1.0657 % | -1065659 |
| 2 | 6CQSpR | 12:55:05Z | horloge (1801 s) | -0.5884 % | -0.4978 % | -0.0520 % | -0.4200 % | -1.5582 % | -1558229 |
| 3 | 6CQSpR | 13:59:51Z | horloge (1801 s) | -0.1264 % | -0.4990 % | -0.0522 % | -0.4200 % | -1.0977 % | -1097673 |
| 4 | 5zk4vh | 14:36:07Z | horloge (1801 s) | +0.5464 % | -0.5006 % | -0.0976 % | -0.4200 % | -0.4719 % | -471852 |
| 5 | 6CQSpR | 15:05:22Z | horloge (1801 s) | -0.2530 % | -0.4987 % | -0.0522 % | -0.4200 % | -1.2238 % | -1223839 |
| 6 | 6CQSpR | 16:11:48Z | horloge (1801 s) | -0.4542 % | -0.4982 % | -0.0520 % | -0.4200 % | -1.4243 % | -1424346 |
| Σ | | | | -0.9700 % | -2.9934 % | -0.3582 % | -2.5200 % | -6.8416 % | -6841598 |
| moyenne | | | | -0.1617 % | -0.4989 % | -0.0597 % | -0.4200 % | -1.1403 % | -1140266 |

## Témoin apparié : 5 positions fermées

| # | Pool | Décision | Sortie (durée) | Brut (mouvement de prix) | Frais de pool | Impact | Frais fixes | Net (% mise) | Net (lamports) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR | 12:11:42Z | horloge (1801 s) | +0.0799 % | -0.4995 % | -0.0523 % | -0.4200 % | -0.8919 % | -891932 |
| 2 | 6CQSpR | 13:22:34Z | horloge (1801 s) | -0.0236 % | -0.4993 % | -0.0523 % | -0.4200 % | -0.9951 % | -995146 |
| 3 | 5zk4vh | 14:54:03Z | horloge (1801 s) | +0.1486 % | -0.4996 % | -0.0971 % | -0.4200 % | -0.8682 % | -868204 |
| 4 | 6CQSpR | 15:18:23Z | horloge (1801 s) | +0.3875 % | -0.5003 % | -0.0525 % | -0.4200 % | -0.5852 % | -585233 |
| 5 | 6CQSpR | 16:40:12Z | horloge (1801 s) | -0.0575 % | -0.4992 % | -0.0523 % | -0.4200 % | -1.0289 % | -1028909 |
| Σ | | | | +0.5350 % | -2.4978 % | -0.3065 % | -2.1000 % | -4.3694 % | -4369424 |
| moyenne | | | | +0.1070 % | -0.4996 % | -0.0613 % | -0.4200 % | -0.8739 % | -873885 |

## Lecture descriptive

1. **Toutes les sorties sont à l'horloge** : 30 min + 1 s de latence (G2-3 et témoin). Aucun TP (+2 %) ni SL (−2 %)
   n'a été atteint pendant la tenue.
2. **Le coût d'un aller-retour est quasi fixe.** Moyenne 0.9786 % de la mise (G2-3) et 0.9809 % (témoin).
   - Frais de pool : ≈ 0,50 % (2 × 0,25 %, config U-1).
   - Frais fixes : 0,42 %.
   - Impact : 0,05 % (6CQSpR) à 0,10 % (5zk4vh).
   - Un mouvement de prix d'au moins ≈ 1,0 % en 30 min est donc nécessaire pour que le net soit positif.
     **Aucune** des 11 positions n'y est parvenue : le meilleur brut est +0.5464 %.
3. **Le mouvement de prix après le signal.**
   - G2-3 : 5 positions sur 6 ont un brut négatif ; brut moyen -0.1617 %.
   - Témoin : brut moyen +0.1070 %.
   - Le net G2-3 est inférieur au net du témoin à cause du brut ; les coûts sont les mêmes.
   - 5 des 6 positions G2-3 sont sur le même pool, 6CQSpR, et leurs bruts y sont tous négatifs. Les observations ne
     sont donc pas indépendantes ; n = 6.
4. **Part de la perte nette.**
   - G2-3 : le brut fait 14.2 % de la perte et les coûts 85.8 %.
   - Témoin : le brut est positif (+0.5350 % cumulés) ; la perte vient entièrement des coûts.
5. **GaPTvX** (b₃ = 4, seuil de 8 acheteurs distincts sur 600 s) : aucun signal en 6 h.

## Ce que cela suggère comme questions (aucune n'est validée, rien n'est modifié)

- Le seuil d'équilibre d'une rotation de 30 min sur ces pools est ≈ 1 % de mouvement de prix. Les
  mouvements observés après le signal sont d'un ordre de grandeur inférieur.
- Une hypothèse future devrait viser des mouvements attendus nettement supérieurs à 1 %, ou des coûts plus bas :
  - mise plus grande, pour diluer les 0,42 % de frais fixes ;
  - pools à frais de 0,25 % ou moins.
  Elle serait PRÉ-ENREGISTRÉE et auditée par R02 avant toute donnée.
- À compléter au bilan à 24 h, avec le même tableau. n restera faible.

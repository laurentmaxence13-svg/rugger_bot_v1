# n1verdict 0.2 — verdict du pilote N1 (essai 170), conception R04-6

RUGGER 01, 24/11/2026.
- Décision R04-6 (21:27Z) ; avis de R02 ancré : recevable sous C1 et C2.
- n1verdict 0.1 (conception « 0,1 SOL, aller-retour quotidien ») reste dans le commit 5ce70fd ; son audit est
  suspendu par R02.
- Code hors ligne. Il ne lit aucune donnée et ne s'exécute qu'après l'ancrage de la fiche N1.

## Ce que fait le code (`n1verdict/verdict.py`)

| Fonction | Règle |
|---|---|
| `pool_days` | UNE position par pool, `lpcost.continuous_position` (0.2), de T0 à T0 + D × 86 400 s. Mise = 0,5 % de la réserve WSOL de l'état de décision. Pool-jour k = valeur journalière de l'écart / mise. La ligne doit contenir l'état avant T0 (pages pré-T0 + fenêtre) |
| `UNPRICED` | Liste FERMÉE des causes « non valorisable », chacune avec son type d'erreur (acceptée par R02, point (a)). Toute autre erreur ARRÊTE le verdict |
| `total_loss_per_day` | Position non valorisable : chacun de ses D pool-jours vaut −(1 + (transactions + loyers) / mise) / D. La mise est 0,5 % de la réserve SOL journalisée avant le dernier swap pré-T0. **À confirmer par R02 pour R04-6** |
| refus de garde | Aucune position : ses D jours sont publiés et ne comptent pas comme entrées |
| `word` | g23five 0.2 avec `block_days = 2` : blocs de 2 jours consécutifs par pool, stratifiés par pool. Planchers et garde de G2-3 inchangés ; INCONCLUSIF avant NO-GO |
| `report` | G-0 non passé → STOP. Graine int(sha de la fiche N1[:8], 16). D pair, entre 7 et 30 |

**Le mot (C1)** : l'ÉCART À LA DÉTENTION, net de TOUS les coûts, réparti par jour avec les coûts / D (C2).

**Ce que publie `report` :**
- par pool, en DESCRIPTIF : le net absolu en SOL rapporté à la mise, l'écart, le mouvement de prix détenu, la
  variation de marque, les coûts et les frais perçus estimés ;
- les sensibilités, sans verdict : (1, 1, 1) échec, garde à 50 000 ppm, loyers perdus ;
- les limites L1 à L3, la portée déclarée (taille notionnelle, aucun capital, condition nécessaire) et la
  multiplicité ;
- « sous la cible » ;
- le vocabulaire fermé, contrôlé sur tout le document.

## Validation

- 7 tests. Ils couvrent :
  - la perte totale par jour ;
  - des pool-jours égaux aux valeurs journalières de `continuous_position` sur un pool synthétique réel ;
  - un événement LP au point d'atterrissage d'entrée, qui donne une perte totale sur les 8 jours, y compris sous la
    sensibilité, avec la mise lue avant le dernier swap pré-T0 ;
  - une autre erreur qui arrête le verdict ;
  - l'état pré-T0 exigé ;
  - des bornes égales à g23five 0.2 en blocs de 2 jours, différentes des blocs d'1 jour ;
  - GO, NO-GO, « sans le pool le plus fourni », les planchers avec un pool refusé, les sensibilités, STOP, les
    entrées et le vocabulaire.
- 29 mutants sur 29 détectés (`MUTATIONS_n1verdict_v0_2.json`). Un mutant équivalent a été retiré et justifié.
- Chemin : celui de lpcost 0.2 + `<lpcost_pkg>:<g23five02_pkg>:<n1verdict_pkg>`. Ce chemin porte g23five 0.2, pas
  0.1.1.

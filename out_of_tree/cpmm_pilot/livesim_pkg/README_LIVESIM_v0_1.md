# livesim 0.1 — simulation PAPER « en temps réel » de G2-3 et N1 (démonstration descriptive)

RUGGER 01, 25/11/2026.
- Directive du propriétaire (25/11, vers 08:39Z), relayée par R04 (08:41Z).
- **Démonstration descriptive** : aucun essai, aucun test d'hypothèse, aucun mot de verdict. Ce n'est jamais un trade
  du Master et cela ne compte jamais pour 50/20.
- **Univers distinct des pilotes** : les 4 pools de G2-3 (dont les 3 de N1) sont REFUSÉS par le code.
- **Modules gelés APPELÉS, jamais modifiés** :
  - G2-3 :
    - `cpmmgen2.baseline_b3`, calculé sur les 7 jours avant le début de la simulation ;
    - `cpmmgen2.decisions_g23` ;
    - `cpmmcost.pool_gate` (G-0) ;
    - `cpmmprereg.exit_point`, `positions` et `placebo`, via g23run 0.1 ancré (`positions_each`, `converted`, K01).
  - N1 : `lpcost` 0.2 `continuous_position`, mise de 0,5 % de la réserve WSOL.

## Ce que produit `simulate(...)` à l'instant `now` (bilans à 6 h, 24 h ou à toute heure)

**(a) Journal par pool.**
- Signaux G2-3 de [début ; now).
- Positions FERMÉES : sortie TP / SL trouvée parmi les swaps collectés, ou sortie horloge ≤ now. Chacune porte sa
  décomposition gelée (mouvement de prix, frais, impact, transactions, nettoyage, loyer).
- Positions OUVERTES : jamais valorisées.
- Le même journal existe pour le témoin apparié.
- Aucune donnée postérieure à `now` n'est vue (`truncated`).

**(b) Tableau de bord, par série (G2-3, puis témoin apparié).**
- Signaux, entrées, sorties, positions ouvertes, refus de garde.
- Taux de réussite (net > 0).
- P&L brut (mouvement de prix), coûts, P&L net.
- Rendement net sur le capital fictif et drawdown maximal.
- Courbe du capital fictif : 10 SOL au départ, 0,1 SOL par position, positions fermées classées par heure de sortie.

**(c) Témoins.**
- G2-3 : placebo apparié (`cpmmprereg.placebo`, même nombre que les signaux ; la graine est le sha de la liste et du
  début).
- N1 : la détention des mêmes jetons (mouvement de prix détenu), descriptive.

**(d) N1, observations intermédiaires horaires.**
- À chaque marque, la valeur liquidative de la position si elle était retirée à cet instant : écart à la détention,
  net absolu, mouvement de prix détenu.
- Elle est calculée par `continuous_position` sur les données disponibles à la marque.
- Ce n'est PAS le résultat 12 jours.
- Un état indisponible est publié « non valorisable ».

**(e) Rendu Markdown lisible (`render`)** : vocabulaire fermé contrôlé, et « 0 opération » affiché quand aucun signal
n'apparaît.

**Limite déclarée.** Les événements LP sont tronqués au slot du dernier swap connu à la marque.

## Exécution (R03, après la confirmation de R02 sur les pages à utiliser)

`python -B -m livesim.sim --pools POOLS.json --u2 U2.json --pre-root <pages [début − 7 j ; début)> --root <pages [début ; now]> --t0-slot S --start T --now T --out DIR`

- Sorties : LIVESIM.json et LIVESIM.md, avec leur sha imprimé.
- Une liste contenant un pool pilote est refusée, ainsi qu'un dossier de sortie existant.

## Validation

- 10 tests sur des pools synthétiques. Ils couvrent :
  - le refus des pools pilotes ;
  - un bilan à 6 h de bout en bout, avec le journal égal aux fonctions gelées et les sommes brut − coûts = net ;
  - les positions ouvertes jamais valorisées ;
  - l'affichage « 0 opération » ;
  - les observations N1 horaires égales à `continuous_position`, y compris au-delà de 24 h et sans état avant le
    début ;
  - aucune donnée future, et le filtre du début ;
  - G-0 et le vocabulaire ;
  - le drawdown et l'ordre des sorties ;
  - le CLI.
- 23 mutants sur 23 détectés (`MUTATIONS_livesim_v0_1.json`).

## Estimation et besoins

- **Code** : écrit, environ 3 h. **Audit R02** : NM.
- **Exécution d'un bilan** : de quelques secondes à quelques minutes par bilan, selon le nombre de transactions des
  pools.
- **« Temps réel »** : il faut des pages fraîches. R03 collecte les pages des pools choisis toutes les heures, ou à
  6 h puis à 24 h. Coût : 0,103 crédit par transaction ; le volume est NM et une autorisation du propriétaire est
  requise. Le code ne fait aucun appel réseau.
- **Univers proposé** : les pools de la liste U-2 d'A2r hors pilotes, soit 20 sur 24.
  - Pour des tests sur leurs pages pré-T0 d'A2r (déjà collectées, 0 crédit), une confirmation de R02 est requise avant
    toute exécution.

# livesim 0.2 — simulation PAPER « en temps réel » de G2-3 et N1 (démonstration descriptive)

RUGGER 01, 25/11/2026.
- La 0.2 remplace la 0.1 (3b793e9), qui n'a jamais été auditée ni exécutée.
- Elle applique la décision R04-10 (08:46Z) et les exigences de R02, qui a jugé la simulation RECEVABLE à 08:42:17Z.
- **Démonstration descriptive** :
  - aucun essai, aucun test d'hypothèse, aucun mot de verdict ;
  - jamais un trade du Master, jamais compté pour 50/20.
- **Univers** : K = 8 pools hors pilotes, liste fournie par R03 (`--pools`).
  - Les 4 pools pilotes de G2-3 (dont les 3 de N1) sont REFUSÉS par le code.

## Exigences R04-10 / R02 et leur réalisation

| Exigence | Réalisation dans `livesim/sim.py` |
|---|---|
| Code gelé appelé sans modification, **avec contrôle des MANIFEST** | Voir [Contrôle du code gelé](#contrôle-du-code-gelé) |
| **b₃ recalculé par la règle gelée sur 7 j pré-départ** des nouveaux pools | `cpmmgen2.baseline_b3(pre, pre_txs, départ)` par pool, avec les pages [départ − 7 j ; départ). Les b₃ 2 / 1 / 6 / 1 des pilotes ne sont jamais utilisés. Ils sont publiés dans `LIVESIM.json` (`b3`) |
| **Wrapper N1 sur une autre liste, sans modifier n1rot 0.2** | Voir [Wrapper N1](#wrapper-n1) |
| **Tableau de bord** | Voir [Tableau de bord G2-3](#tableau-de-bord-g2-3) |
| **N1 : marques intermédiaires seulement, résultat 12 jours « NON MESURÉ »** | Voir [N1](#n1) |
| **7 limites publiées** | `LIMITS`, dans `LIVESIM.json` (`limits`) et dans `LIVESIM.md` (section « Limites (7) ») |

### Contrôle du code gelé

- `check_frozen` et `check_trees` s'exécutent AVANT toute lecture de page, puis à nouveau APRÈS le calcul. Toute
  différence arrête l'exécution.
- MANIFEST vérifiés (sha du fichier MANIFEST, tel qu'il figure dans les fiches ancrées) :
  - cpmmcost 0.3 `a0bd2adb` ;
  - cpmmgen2 0.2 `70ef9a9b` ;
  - cpmmprereg 0.2 `9d8ebde6` ;
  - g1ind 0.6.1 `12a2e661` ;
  - g23run 0.1 `3e3cb105` ;
  - lpcost 0.2 `ee9c144c` ;
  - n1rot 0.2 `2a17791d` ;
  - cpmmpilot 0.2.8 `7251d4fe`.
- Trois vérifications pour chaque paquet :
  - le sha du MANIFEST ;
  - le sha de chaque fichier listé ;
  - tout fichier du paquet effectivement CHARGÉ doit figurer dans le MANIFEST.
- cpmmx n'a pas de MANIFEST. Il est contrôlé par son arbre git `e1034371`, celui de la fiche N1 v0.7, recalculé
  depuis le disque (`git_tree`).
- Le résultat est publié dans `frozen_code`.

### Wrapper N1

- La fonction est `n1_universe`.
- `n1rot.select_n1` est lié aux 4 pools pilotes : il n'est PAS appelé.
- Ses propres fonctions sont appelées pool par pool, sans modification :
  - `daily_rotation` ;
  - `median_rotation` ;
  - `break_even_rotation_r04_6`, seuil `r04_6_break_even`.
- Un pool est retenu si sa médiane est ≥ son seuil, la règle de `select_n1`.
- Historique exigé par n1rot, cité dans le code (`PRE_DAYS`) :
  - les 7 jours [départ − 7 j ; départ) ;
  - les données au départ ou après sont refusées ;
  - le dernier état avant le départ, avec une limite à départ − 1.
- Si le seuil n'est pas calculable, le pool est non retenu, avec le motif. Le plancher de 3 pools de n1rot est
  publié.
- Un test d'identité compare `n1_universe` et `select_n1` sur les mêmes lignes :
  - les lignes sont renommées avec les 4 noms pilotes, uniquement dans ce test synthétique ;
  - jours, médianes, seuils, pools retenus et sha de la liste sont identiques.

### Tableau de bord G2-3

- 0,1 SOL par position.
- **Capital fictif** : somme cumulée des P&L nets des positions fermées, classées par heure de sortie, en partant de 0.
  - Il est publié point par point et à chaque heure.
- **Drawdown** : la plus grande baisse de cette courbe depuis son plus haut. Il est publié en SOL et en nombre de
  mises de 0,1 SOL.
- **Taux de réussite** : part des positions fermées dont le P&L net est > 0. Les refus de garde comptent, avec leur
  P&L net négatif.
- Sont aussi publiés :
  - les signaux, les entrées, les sorties, les positions ouvertes (jamais valorisées) et les refus de garde ;
  - le P&L brut (mouvement de prix), les coûts et le P&L net ;
  - le net moyen par position.
- **Témoin apparié** : il est publié à côté, et n'est jamais fusionné avec G2-3 (`placebo_merged = False`, aucune
  série combinée).
- Si aucun signal n'apparaît, le rendu affiche « 0 opération ».

### N1

- Les marques horaires (valeur liquidative si retrait à la marque) concernent seulement les pools retenus par
  `n1_universe` et admis par G-0.
- `result_12_days = « NON MESURÉ »`, dans le JSON et dans le rendu.

## Les 7 limites

Elles sont rédigées par R01 ; R02 doit les confronter à son avis de 08:42:17Z, que R01 n'a pas reçu en texte
intégral.

1. **L1, démonstration descriptive.** Aucun essai, aucun test, aucun verdict. Jamais un trade du Master, jamais
   compté pour 50/20. Aucune généralisation.
2. **L2, horizon court (6 h, 24 h).** Il y a peu de positions. Les chiffres ne sont pas des estimations.
3. **L3, positions fermées seulement.** Seules les positions FERMÉES sont valorisées. Les sorties rapides (TP / SL)
   apparaissent avant les sorties horloge.
4. **L4, données jusqu'à « now ».**
   - Les événements LP sont tronqués au slot du dernier swap connu.
   - L-FIN s'applique.
   - Le « temps réel » dépend de la fraîcheur des pages collectées par R03.
5. **L5, univers choisi par R03 (R04-10).** Il n'est pas tiré d'une règle pré-enregistrée.
   - b₃ est recalculé.
   - G-0 peut exclure des pools.
   - La graine du témoin est déclarée.
6. **L6, N1 en marques intermédiaires seulement.** Le résultat 12 jours est NON MESURÉ. L'univers suit le seuil
   r04_6_break_even sur 7 jours, et le plancher de 3 pools est publié.
7. **L7, coûts du modèle gelé.** Pas de MEV ; latence gelée. PAPER seulement, aucun ordre réel.

## Exécution (R03, après l'audit de R02 sur cette version)

`python -B -m livesim.sim --pools POOLS_K8.json --u2 U2.json --pre-root <pages [départ − 7 j ; départ)> --root <pages [départ ; now]> --t0-slot S --start T --now T --out DIR`

- Le chemin Python porte les paquets gelés ci-dessus, dont **n1rot 0.2** (nouveau dans la 0.2) et **cpmmpilot
  0.2.8**.
  - Le MANIFEST de cpmmpilot est attendu sous le nom `MANIFEST_cpmmpilot_v0_2_8.txt`, à confirmer par R03. Sinon le
    code refuse avec `manifest_missing:cpmmpilot`.
- Sorties : `LIVESIM.json` et `LIVESIM.md`, avec leur sha imprimé.
- Une liste contenant un pool pilote est refusée, ainsi qu'un dossier de sortie existant.

## Validation

- 17 tests sur des pools synthétiques :
  - les 10 tests de la 0.1, adaptés ;
  - 7 nouveaux tests :
    - le MANIFEST : chaque altération est détectée (fichier modifié ou absent, MANIFEST modifié ou absent, fichier
      chargé non listé) ;
    - l'arbre git de cpmmx ;
    - le CLI contrôle le code gelé avant et après la lecture, et échoue sans lire de page ;
    - la fenêtre pré-départ de 7 jours, et b₃ recalculé (6, et non 2) ;
    - l'identité de `n1_universe` avec `select_n1`, y compris le cas d'égalité ;
    - N1 limité aux pools retenus, avec le résultat 12 jours « NON MESURÉ » et les 7 limites ;
    - les constantes gelées vérifiées à l'import.
- La copie locale de cpmmpilot est la 0.1.6 (f934bd2), pas la 0.2.8.
  - Son contrôle est testé : le refus `manifest_missing:cpmmpilot` est vérifié.
  - Il est retiré du seul test CLI de bout en bout. C'est déclaré.
- Mutants : voir `MUTATIONS_livesim_v0_2.json`.

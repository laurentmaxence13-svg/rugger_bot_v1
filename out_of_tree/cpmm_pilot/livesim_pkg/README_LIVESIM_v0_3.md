# livesim 0.3 — simulation PAPER « en temps réel » de G2-3 et N1 (démonstration descriptive)

RUGGER 01, 25/11/2026.
- Elle corrige l'audit R02 de la 0.1 (NON VALIDÉ, 08:51:39Z, F1 à F5).
- Elle suit le format des fichiers de R03 (08:52:30Z, pilote de collecte livesim_collect 198b3262).
- Elle garde tout ce qu'apportait la 0.2 (bc1da29) : R04-10, contrôle des MANIFEST, tableau de bord, 7 limites.
  Voir `README_LIVESIM_v0_2.md`.
- **Démonstration descriptive** :
  - aucun essai, aucun test d'hypothèse, aucun mot de verdict ;
  - jamais un trade du Master, jamais compté pour 50/20.

## Corrections de l'audit R02

| Point | Correction |
|---|---|
| **F1** Config des frais | Une config PAR POOL. `pool_config` appelle la fonction gelée `amm_config_for_rules([row])` sur la ligne de CHAQUE pool. Les configs sont les configs U-1 ancrées de LIST_L (`c96353b9`, `list[i].config` et `configs`, `t0_slot`). Chaque pool reçoit SA config dans G-0, dans les positions G2-3 et dans N1. Testé avec deux pools sur deux configs (frais créateur 0 et 1 %, comme D4FPEr et CRRS5i). La config A refuse le pool B à G-0. L'ancien appel à config unique échoue, comme en 0.1 |
| **F2** Entrée des pools | Les entrées sont les fichiers de R03 : CONFIG.json (t_start), QUALIFIED.json (sha de la liste vérifié), POLLS.json, et les pages `collect/pre/<pool>` et `collect/live_NNN/<pool>`. LIST_L fournit base_mint et config. U2.selected n'est plus lu. Les pools interdits sont les 4 pilotes et 2yLFom, la même liste que le pilote de collecte de R03 |
| **F3** N1 | `n1_universe` applique la règle de n1rot 0.2 sans modifier n1rot (fonctions gelées, seuil r04_6_break_even, médiane ≥ seuil). N1 ne marque que les pools retenus ET éligibles. Le test d'identité avec `select_n1` est fait sur des données synthétiques. **Identité sur 6b9b02a9** : commande `identity`, voir [Exécution](#exécution-r03-hors-ligne-0-crédit-après-laudit-de-r02-et-lancrage) |
| **F4** Seuil d'évaluation | Éligible = G-0 admis ET b₃ > 0. Il faut au moins 3 pools éligibles à « now », sinon **NON ÉVALUABLE** : `g23`, `n1` et `journal` valent null, et le rendu n'affiche aucun chiffre de P&L. La même règle produit ELIGIBLE.json (commande `eligible`) sur l'historique. N1 applique aussi le plancher de n1rot : moins de 3 pools retenus et éligibles donne N1 NON ÉVALUABLE, sans aucune marque |
| **F5** Placebo | Il est déclaré dans le JSON (`placebo_note`), dans le rendu et dans la limite L5. Le témoin est retiré à chaque « now », autant que de signaux connus. Ses positions peuvent changer entre le bilan à 6 h et celui à 24 h |

## Limites et « n insuffisant »

- Les 7 limites sont celles de R02 (09:06:59Z), MOT POUR MOT, dans `LIMITS`. Elles sont publiées dans le JSON et dans
  le rendu. Elles remplacent celles que j'avais rédigées en 0.2.
- « n insuffisant » (L3) :
  - G2-3 : publié pour une série dont le nombre de positions fermées est < 30 ;
  - N1 : publié quand le nombre de pool-jours marqués est < 30 ;
  - 30 est le plancher des pilotes ; R02 doit le confirmer.

## cpmmpilot : 0.2.8 ou 0.2.9 (décision de R02)

- R03 a confirmé deux points :
  - le paquet de R03 est versionné sur place et contient aujourd'hui la 0.2.9 ;
  - `step1.py` et `store.py` sont identiques à ceux de la 0.2.8 ; seuls `budget.py`, le test et le runner changent.
- La 0.3 vérifie le MANIFEST 0.2.8 (7251d4fe) en entier. Elle doit donc tourner sur une extraction figée de la 0.2.8,
  sur son propre chemin Python : c'est l'option (ii) de R03, `git archive 8c4a022 out_of_tree/cpmmpilot_pkg`.
- Si R02 retient l'option (i), il suffit de remplacer, dans `FROZEN`, la seule entrée cpmmpilot par le nom et le sha
  du MANIFEST 0.2.9 fournis par R03, puis de refaire les tests et les mutants.

## Commandes

```
python -B -m livesim.sim eligible --collect OUT --list-l LIST_L.json --out ELIGIBLE.json
python -B -m livesim.sim bilan --collect OUT --list-l LIST_L.json --eligible ELIGIBLE.json --eligible-sha <ancré R02> --now T --out DIR
python -B -m livesim.sim identity --a2r <OUT A2r> --u2 U2.json --result N1ROT_RESULT.json --t0-time 1795515686 --t0-slot 473309024 --out IDENTITY.json
```

- **Code gelé** : chaque commande contrôle les 8 MANIFEST et l'arbre git de cpmmx AVANT de lire un fichier, puis à
  nouveau APRÈS le calcul.
  - Le chemin Python porte cpmmpilot **0.2.8** (7251d4fe), pas la 0.2.9 du pilote de collecte.
- **eligible** :
  - pour chaque pool qualifié : b₃ par la règle gelée sur [t_start − 7 j ; t_start), et G-0 sur l'historique avec la
    config du pool ;
  - écrit ELIGIBLE.json : `pools` (éligibles, ordre de QUALIFIED), `rows` (b₃, G-0, sha de la config, sha des pages
    pré-départ), `evaluable`, et les sha de QUALIFIED, CONFIG et LIST_L ;
  - son sha est imprimé ; R02 l'ancre.
- **bilan** :
  - ELIGIBLE.json doit avoir le sha ancré ; il doit venir de la même collecte (t_start, sha de QUALIFIED) et garder
    l'ordre de QUALIFIED ;
  - les pages pré-départ et les b₃ recalculés doivent être identiques à ceux d'ELIGIBLE.json ;
  - les blocs de POLLS.json doivent être exactement les blocs fixes de 2 h ;
  - « now » doit être la fin d'un bloc terminé, au plus t_start + 24 h, avec tous les blocs précédents terminés ;
  - chaque page d'un bloc doit être dans la fenêtre de ce bloc ;
  - sorties : LIVESIM.json et LIVESIM.md, avec leur sha imprimé.
  - La graine du témoin, sha de « livesim|t_start|éligibles », est acceptée par R02.
- **identity** :
  - vérifie que N1ROT_RESULT.json a le sha ancré `6b9b02a9` ;
  - charge les 4 pools nommés comme `n1rot.main` (`timelines(out, 'pre', rows)`, config unique U2) ;
  - compare `n1_universe` au résultat : `kept`, `list_sha256` et, par pool, `kept`, médiane exacte, seuil exact et
    jours ;
  - écrit `identical` et la liste des différences.

## Exécution (R03, hors ligne, 0 crédit, après l'audit de R02 et l'ancrage)

1. `identity` sur les pages pré-T0 d'A2r, admises pour des tests TECHNIQUES (R02 (1)). Rien n'est publié comme
   performance.
   - `--a2r` est lu comme par `n1rot.main` (`<racine>/collect/pre/<pool>`).
   - Sur STEP1A2R_20261124T164909Z, R03 refait le lien `collect/pre → pre_pages`, comme pour n1rot : le chemin
     d'exécution est alors identique à celui de 6b9b02a9.
2. Après la phase history du pilote de collecte : `eligible`. R02 ancre le sha d'ELIGIBLE.json.
3. Après la collecte, aux bilans de 6 h et 24 h : `bilan --now t_start + 6 h`, puis `--now t_start + 24 h`.

## Validation

- 24 tests sur des pools synthétiques, écrits dans la disposition de R03 (CONFIG, QUALIFIED, POLLS, collect/pre,
  collect/live_NNN), avec une LIST_L synthétique.
  - Les tests de la 0.2 sont adaptés.
  - Nouveaux tests :
    - une config par pool ;
    - moins de 3 éligibles donne NON ÉVALUABLE, sans chiffre ;
    - les blocs et la fenêtre pré-départ ;
    - les commandes eligible, bilan et identity, avec chaque refus ;
    - le plancher N1 de 3 pools retenus et éligibles.
- Mutants : voir `MUTATIONS_livesim_v0_3.json`.
- La copie locale de cpmmpilot est la 0.1.6 : son MANIFEST est absent, et le refus est testé. Les tests CLI tournent
  sans ce seul contrôle ; c'est déclaré.

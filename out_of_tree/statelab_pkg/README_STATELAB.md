# statelab 0.2.1 — étude d'états des chemins de pools LaunchLab

Question testée : existe-t-il un état de la courbe (âge du pool, progression) où un preneur à environ
une seconde de latence, qui achète 0,1 SOL et revend à un horizon fixe, a une espérance NETTE
positive, meilleure qu'une entrée à un âge tiré au hasard ? Aucune stratégie n'est promue ; une
cellule « retenue » n'est qu'une hypothèse à envoyer en confirmation sur d'autres données.

Version 0.2 = corrections de RUGGER 02 (audit bfb18f0a : C-S1, C-S2, C-S3 ; cadre 243e2cca : R-a à R-f).
Les lignes produites par la version 0.1 (commit 8f24a84, fichier 7fc1838a chez R03) restent fermées
et ne servent à aucun tableau.

Version 0.2.1 = point E-S1 de RUGGER 02 (contrôle 63817ac9) : un placebo sous les planchers est dit
automatiquement dans le tableau (notes et markdown). Aucune règle, aucune valeur et aucune ligne ne
changent ; les lignes de la 0.2 restent lisibles telles quelles.

Premier tableau calculé (P0 visible, exploration + train, latence 4, K = 30 ancré, N = 64 ensuite) :
0 cellule retenue sur 30 ; rendement net moyen de -24,9 % à -7,2 % ; toutes les bornes hautes des
intervalles négatives (vérifié par RUGGER 02, 63817ac9). Placebo sous plancher sur P0 (28 sondes).

## Fixé dans le code avant toute lecture de données

- Grille (`points.py`) : premier événement entier d'âge >= A pour A = 0, 5, 15, 30, 60, 120, 300, 600,
  1200, 2400, 3600 s (retard maximal 30 s) ; premier franchissement à la hausse de 5, 10, 20, 35, 50,
  65, 80 % de progression ; horizons 10, 25, 60, 120, 300 s. Grille complète : 18 x 5 = 90 cellules.
- Placebo (C-S2) : la règle gelée `RandomEntry` de V3-02 — âge cible tiré de l'identifiant du pool
  (sel `v1`, 0 à 120 s), premier événement entier à cet âge ou après, perdu au-delà de 120 s.
  Cellule de référence : `age:5` (l'entrée de V3-01).
- Valeur d'un horizon (C-S1) : la SORTIE À L'HORLOGE gelée — vente due à h, qui atterrit après la
  latence d'horloge gelée (`clock_exit_latency_s` : 1 s pour 4 slots, 3 s pour 10 slots), derrière
  tous les événements réels arrivés avant. Égale au lamport près à une sortie à l'horloge rejouée par
  v4sim 0.2 mode M-P (test sur tous les points et tous les horizons). La valeur sans latence de vente
  n'est qu'une sensibilité.
- Rendement d'une sonde (R-d) : (valeur − mise − 2 frais de transaction − loyer) / (capital + loyer),
  loyer PERDU par la chaîne actuelle (classe du recensement) ; courbe achevée avant l'atterrissage de
  la vente : −1.
- Unité (R-e) : une sonde par pool et par cellule ; intervalles par rééchantillonnage des créateurs.
- Planchers : une étiquette n'est CALCULÉE que si elle compte au moins 30 sondes entrées et 20
  créateurs. `statelab.study` affiche ces effectifs (aucune valeur) : K = étiquettes calculées x 5
  horizons est donc connu, déclaré et ancré AVANT la lecture ; `statelab.table --declared-k K` refuse
  tout autre K. Calculer le tableau ajoute K au nombre cumulé d'essais N (R-b).
- Criblage (C-S3) : cellule retenue seulement si rendement net moyen > 0 ET borne basse de
  l'intervalle à 95 % de l'écart apparié au placebo > 0 ET Benjamini-Hochberg q = 0,10 sur les 90
  cellules de la grille (les cellules non calculées comptent dans la famille).
- Secondaire : écart apparié à `age:5` ; dérive moyenne (référence martingale = 0).
- Sensibilités pré-déclarées, publiées pour toutes les cellules, non comptées, sans effet sur un
  choix : sans latence de vente ; loyer récupéré (nettoyage, NON exécutable aujourd'hui) ; mêmes
  tableaux avec `--latency-slots 1` et `10`.

## Données et gardes

Pack visible ancré lu par `v3lab.pack.Pack` (scellés et tout slot W1 refusés). Découverte sur
`exploration` et `train`. `validation` exige `--confirm-validation <une hypothèse pré-enregistrée>`
et est alors lue seule. Population : pools rejouables à créateur signé. Un point dont l'horizon le
plus long sortirait de la fenêtre collectée est écarté et compté.

## Commandes (racine de l'arbre gelé ; PYTHONPATH = statelab_pkg : v3lab_pkg : v4sim_pkg)

    python -B -m statelab.study <pack_visible> --expect-manifest-sha <sha256> --out rows_lat4.json
    python -B -m statelab.table rows_lat4.json --declared-k <K ancré> --census <census.json> --markdown table_lat4.md > table_lat4.json

## Limites dites

P0 visible a déjà servi à 34 essais ; 141 pools seulement en découverte ; presque aucun état de fin
de courbe ni de migration ; latence d'achat du modèle, sans échec d'inclusion ; une cellule retenue
ici devra passer les critères économiques v1 de RUGGER 02 (dont R-1 : 200 cycles clos, 100 créateurs)
sur d'autres données.

## Tests

20 tests hors ligne ; 23 fautes plantées, toutes détectées (dont la lecture du futur, l'oubli de la
latence de vente, une courbe achevée créditée, le loyer oublié, la famille de multiplicité réduite,
l'appariement hors pool).

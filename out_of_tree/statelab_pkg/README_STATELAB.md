# statelab 0.1 — étude d'états des chemins de pools LaunchLab (descriptif)

But : mesurer, depuis une grille FIXE d'instants de décision causaux, la valeur de liquidation exacte
d'un achat de 0,1 SOL à des horizons fixes, nette de tous les coûts. C'est le test direct de la
question « existe-t-il un état de la courbe où un preneur à environ une seconde de latence a une
espérance nette positive ? ». Aucune stratégie n'est évaluée, aucun essai n'est enregistré, rien
n'est choisi ni promu.

Ce qui est fixé AVANT toute lecture de données (constantes du code, couvertes par l'empreinte) :
- points de décision (`statelab/points.py`) : premier événement entier d'âge >= A pour
  A = 0, 5, 15, 30, 60, 120, 300, 600, 1200, 2400, 3600 s (retard maximal 30 s) ; premier
  franchissement à la hausse des niveaux de progression 5, 10, 20, 35, 50, 65, 80 % de la courbe ;
- mise 0,1 SOL ; horizons 10, 25, 60, 120, 300 s ; latence d'ordre 4 slots (option `--latency-slots`
  pour les sensibilités 1 et 10) ; une seconde d'allocation pour la latence de vente (`value_late`) ;
- valorisation : `v4sim` 0.2 inchangé, mode M-P, registres par acteur, liquidation exacte ;
- population : pools rejouables dont le créateur est signé (celle des politiques de référence) ;
- une position dont la courbe s'achève avant l'horizon n'est pas créditée (`migrated`, critères R02 v1).

Données : uniquement un pack visible ancré, lu par `v3lab.pack.Pack` (fichiers scellés et tout slot
W1 refusés). Découverte sur `exploration` et `train`. La lecture de `validation` exige
`--confirm-validation <identifiant d'UNE hypothèse pré-enregistrée>` et est inscrite dans la sortie.

Commandes (depuis la racine de l'arbre gelé, PYTHONPATH = statelab_pkg : v3lab_pkg : v4sim_pkg) :

    python -B -m statelab.study <pack_visible> --expect-manifest-sha <sha256> --out rows.json
    python -B -m statelab.table rows.json --census <census.json> --markdown table.md > table.json

`statelab.study` n'affiche que des identifiants et des comptes (aucune valeur). `statelab.table`
produit le tableau principal : par cellule (âge ou progression) et par horizon, rendement net moyen,
intervalle par créateurs, coût instantané, dérive, variante loyer perdu, positions migrées, effet de
la latence de vente, borne rétrospective de sortie. Les cellules sont les étiquettes de la grille :
rien n'est cherché. Une cellule positive est une hypothèse à pré-enregistrer et à confirmer sur
d'autres données, jamais un résultat.

Limites dites : P0 visible a déjà servi à 34 essais ; les sondes d'un même pool sont corrélées
(l'intervalle rééchantillonne les créateurs) ; les états de fin de courbe et les migrations sont
presque absents de P0 ; la latence d'achat est celle du modèle (pas d'échec d'inclusion ici).

Tests : 11 (grille causale, valeurs égales à un recalcul indépendant par l'API des registres,
rien n'est lu après l'horizon, même entrée que la référence V3-01 au point 5 s, garde des segments,
fenêtre, courbe achevée dans l'horizon, achat refusé, transaction entière, créateur non signé,
tableau exact sur lignes faites à la main) ; 11 mutations tuées.

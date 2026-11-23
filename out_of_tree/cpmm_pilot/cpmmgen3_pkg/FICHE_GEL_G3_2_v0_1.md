# Fiche de gel G3-2 « approfondissement de liquidité » — génération 3 (v0.1, SANS T0)

RUGGER 01, 23/11/2026. Tâche T-R01-6 (R04, 22:03Z). Base : GEN-3 v0.2 (cf8a848a), RECEVABLE EN PROJET (R02 a3f194dc).

**Statut : prête à ancrer, NON ancrée.**
- Elle se gèle le jour où le propriétaire autorise une tranche NOUVELLE, distincte du texte D : +2 essais (174, 175) et
  les crédits de la fenêtre. Aucun développement de plus n'est alors nécessaire : on ne remplit que les champs `<…>`.
- **AVANT toute fiche** : le comptage de population des dépôts éligibles sur [T0 − 7 j ; T0)
  (`cpmmgen3.population_deposits`), qui ne lit aucun rendement.
- **[R02 a3f194dc] Conduite déclarée d'avance.** Moins de 30 dépôts éligibles : **NON ÉVALUABLE, aucune fiche de gel,
  aucun essai consommé, et le seuil de 30 n'est jamais abaissé.**
- **Hors de la famille « 10 min »** : aucun déclencheur de prix.

**Mécanisme.**
- Un dépôt de liquidité qui au moins double la réserve en une transaction vient d'un acteur qui engage du capital en
  anticipant du volume. C'est un signal d'information.
- Il abaisse aussi notre coût : la carte donne 1,12 % à 100 SOL et 1,02 % à 200 SOL.
- L'acteur qui perd n'est pas identifié avec précision (note 2 au critère de plausibilité).

**Dépôt éligible (`cpmmgen3.eligible`).**
- Un événement `LpChangeEvent` de type dépôt (`change_type` = 0) du pool.
- Il porte la réserve QUOTE de R à au moins 2 R dans sa transaction : montant quote ≥ réserve quote avant (R > 0).
- Le côté quote vient de l'ordre des mints CPMM : token_0 < token_1 en clés de 32 octets (`quote_index`).
- Le facteur 2 est déclaré, sans principe externe (note 1 au critère « degrés de liberté »).

**Entrée (`cpmmgen3.decisions_g32`).**
- Au PREMIER swap réel du pool qui suit le dépôt dans l'ordre (slot, index de transaction, ordre). Un swap du même
  slot mais d'une transaction antérieure n'est pas « après ».
- Aucune position G3-2 sur le pool depuis 3 600 s. Deux dépôts avant le même swap donnent une seule entrée.
- Un dépôt qu'aucun swap ne suit n'entre pas et n'est pas compté.
- Un retrait n'entre jamais.

**Comptage avant T0.**
- `population_deposits` : dépôts éligibles de [T0 − 7 j ; T0), datés par l'heure de bloc du premier swap qui les suit.
- `trigger_count_g32` : décisions, délai appliqué, sur la même fenêtre.
- Les données ≥ T0 sont REFUSÉES. Aucun résultat n'est calculé. Puis `power_stop`, qui déclare d'avance un pilote
  sous-puissant.
- Sortie : `<sortie de population_deposits>`.

**Sortie, coûts, ordre.** Ceux de R-CP1 (champs communs de la fiche G3-1).

**Témoin.** `cpmmprereg.placebo` (construction de R-CP1), graine de CETTE fiche.

**Données.** Les événements `lp_changes` sont déjà dans `cpmmx.timeline` de la collecte de la fenêtre : aucun crédit
au-delà de la fenêtre de la génération.

**Réfutation.** G-1 NO-GO si la borne haute est < 0.

## Champs communs

Identiques à ceux de la fiche G3-1 (`FICHE_GEL_G3_1_v0_1.md`, section « Champs communs ») : fenêtre et cut_time,
univers, ordre, garde, sortie, coûts, position non valorisable, latence, témoin, n et α₃, G-0 / G-1, confirmation et
Holm, compteur d'essais 173 → 175 sous une tranche NOUVELLE, code gelé, vocabulaire.

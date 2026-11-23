# Fiche de gel G3-1 « écart inter-pools » — génération 3 (v0.1, SANS T0)

RUGGER 01, 23/11/2026. Tâche T-R01-6 (R04, 22:03Z). Base : GEN-3 v0.2 (cf8a848a), RECEVABLE EN PROJET (R02 a3f194dc).

**Statut : prête à ancrer, NON ancrée.**
- Elle se gèle le jour où le propriétaire autorise une tranche NOUVELLE, distincte du texte D : +2 essais (174, 175) et
  les crédits de la fenêtre. Aucun développement de plus n'est alors nécessaire : on ne remplit que les champs `<…>`.
- **AVANT toute fiche** : le comptage de population des paires à T0 (`cpmmgen3.population_pairs`), qui ne lit aucun
  rendement. Avec moins de 10 mints appariés : **NON ÉVALUABLE, aucune fiche de gel, aucun essai consommé**.
- **Hors de la famille « 10 min »** : aucun déclencheur de prix sur 10 minutes.

**Mécanisme (loi du prix unique).**
- Un même jeton se négocie dans plusieurs pools CPMM à WSOL.
- Un gros swap qui déplace un pool l'écarte de son pool frère ; l'arbitrage doit ramener les deux prix.
- L'acteur qui perd est le trader qui a déplacé le pool : il a payé l'impact.

**Paires (`cpmmgen3.pairs`), fixées à T0 à partir de la liste U-2.**
- Un pool entre dans une paire s'il est Raydium CPMM, coté en WSOL, avec une réserve quote ≥ 100 SOL à T0
  (`qualifying`).
- **Pool A** : au palier 0,25 % seulement (le seul palier de U-1 et de cpmmcost).
- **Pool frère B** : le pool qualifié AUTRE que A, du même mint, le plus profond à T0 ; égalités départagées par
  l'identifiant du pool.
- **[R02 a3f194dc] B est un pool CPMM**, le seul décodeur audité. Aucun autre lieu n'est lu.
- B n'est JAMAIS négocié. Seul son spot est lu, avec les parts de frais de SON AmmConfig, lu et haché avec son slot
  (`sibling_fees`). Son palier doit faire partie des paliers CPMM déclarés de la carte (0,25 %, 1 %, 2 %, 4 %). Toute
  transaction reste valorisée par `cpmmcost.fees_from_amm_config`, qui refuse tout palier autre que U-1.
- Table des paires (A → B) : `<table des paires à T0>`. Comptage : `<sortie de population_pairs>`.

**Entrée (`cpmmgen3.decisions_g31`).** Au swap i de A, au temps t :
- spot_A (après le swap i) / spot_B − 1 ≤ **−b**.
- spot_B est pris après le dernier swap de B dont le couple (slot, index de transaction) est ≤ celui du swap i : c'est
  un état connu à la décision, y compris un swap de B dans la MÊME transaction (un arbitrage qui touche les deux
  pools). Aucune limite d'âge, comme dans GEN-3.
- Aucune position G3-1 sur A depuis 3 600 s.
- **b = 1,1217 %** : la barrière de la carte (barmap 0.1, f99c456 ; palier 0,25 %, 100 SOL, priorité 100 000, compte
  fermé). Elle est calculée par `barmap.carte`, jamais retapée. C'est un principe externe déclaré : on n'entre que si
  l'écart couvre nos coûts d'aller-retour.
- Achat dans A, le pool le moins cher.

**Sortie, coûts, ordre.** Ceux de R-CP1, sur A (champs communs ci-dessous).

**Réfutation.**
- G-1 NO-GO si la borne haute est < 0.
- **[R02 a3f194dc]** Si l'écart est refermé par un arbitrage dans le même bloc, avant nos 4 slots, l'hypothèse est
  réfutée par ce fait. C'est un résultat NÉGATIF admissible, pas un défaut de mesure.

**Témoin (`cpmmgen3.placebo_g31`).**
- Apparié par pool A : autant de swaps de A que d'entrées, tirés uniformément parmi ceux où B a déjà un état, avec le
  délai de 3 600 s.
- Graine = int(sha256(sha de CETTE fiche + pool A)[:8], 16).

**Comptage avant T0 (`cpmmgen3.trigger_count_g31`).** Décisions de [T0 − 7 j ; T0) de chaque paire. Les données ≥ T0
de A OU de B sont REFUSÉES. Aucun résultat n'est calculé. Puis `power_stop`.

**Données.** Il faut la liste U-2 PAR MINT (une source U-2 qui donne les pools CPMM de chaque mint), et la collecte
des pools frères. La collecte double par rapport au pilote : au plus 2 × 50 000 crédits, `<crédits autorisés>`.

## Champs communs (identiques pour G3-1 et G3-2)

| Rubrique (b4edc143 § 3) | Valeur gelée |
|---|---|
| Statut | PILOTE (mot maximal GO_PILOTE), puis CONFIRMATION sur une fenêtre NOUVELLE |
| Fenêtre | DISJOINTE des générations 1 et 2 : **[T0 ; T0 + D j)**, T0 = `<T0, ancré par R02>`, D = `<D, chiffré par R03>` ; cut_time = T0 + (D × 86 400) // 2 = `<cut_time>` (R02 21:57Z) |
| Univers | Pools Raydium CPMM établis U-1 à U-4 ; liste U-2 hachée à T0 : `<sha256 de la liste>` ; exclusions `cpmmcost.pool_gate` comptées |
| Ordre | Achat de 0,1 SOL, atterrissage +4 slots, H-1 au pire cas (cpmmcost 0.3) |
| Garde (R-0.3) | 20 000 ppm à l'achat ; refus facturé, sans entrée ni relance ; sensibilité 50 000 ; vente sans garde |
| Sortie | TP +2 % / SL −2 % de la mise sur la valeur de vente exacte, sinon horloge à 30 min + latence gelée (`cpmmprereg.exit_point`) |
| Coûts (R-0.3) | `cpmmcost.position` : frais lus dans l'AmmConfig, impact exact, tx 105 000 lamports, compte fermé, WSOL fermé séparément ; échecs 0 en primaire, (1, 1, 1) en sensibilité |
| Position non valorisable | Vente nulle comptée (K01, R02 f41c6cb0), valeur de `cpmmpilot.step1.zero_sale` ; rapport descriptif par g1ind 0.6 |
| Latence | 4 slots ; sensibilité 10 slots |
| Témoin | Apparié par pool ; graine = int(sha256(sha de CETTE fiche + pool)[:8], 16) |
| n | Pilote : 155 (α 0,05, puissance 0,80, σ 2,5 %, δ +0,5 %). Confirmation : α₃ = 0,0125, Holm sur les hypothèses CONSERVÉES : K = 2 → 1er pas 0,00625, n_c = 279 ; K = 1 → n_c = 238 (`cpmmgen3.confirmation_n`) ; σ_c = max(σ du pilote, 2,5 %). **[R02 a3f194dc] Valable sous l'option (i) du texte D seulement ; à recalculer sous l'option (ii) avant le gel** |
| GO / STOP du pilote | G-0 : décodeur C-1 à C-3, sinon STOP. G-1 (`cpmmcost.pilot_verdict`) : moins de 30 entrées ou moins de 20 pools → INCONCLUSIF ; borne haute unilatérale à 95 % < 0 → NO-GO ; sinon GO_PILOTE |
| Confirmation | Fenêtre NOUVELLE ; c1 à c5 sur grappes par pool ; Holm à α₃ (`cpmmgen3.holm`), une hypothèse sans p comptant p = 1 |
| Compteur d'essais | **[R02 a3f194dc]** 173 → 175 sous une tranche NOUVELLE du propriétaire, distincte du texte D, avec des crédits distincts ; 1 essai par fiche, compté au DÉBUT de la collecte (certificat d34c2c4e ; `cpmmgen3.trials`) |
| Code gelé | `cpmmgen3/rule.py` `<sha au gel>` ; cpmmprereg 0.2 `rule.py` 9f46f052 ; cpmmcost 0.3 ; barmap 0.1 `carte.py` 807fec5a (importés, inchangés) |
| Vocabulaire | R-0.1 : NÉGATIF / INCONCLUSIF / GO_PILOTE / CONFIRMÉ, jamais d'autre mot |

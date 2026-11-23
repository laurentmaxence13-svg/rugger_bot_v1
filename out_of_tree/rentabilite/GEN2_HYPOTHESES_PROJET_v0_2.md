# GEN-2 — Trois hypothèses de génération 2 après R-CP1 et B1 : fiches de préenregistrement en PROJET (v0.2)

RUGGER 01, 23/11/2026. Ordre permanent du propriétaire, relayé par R04 (tâche GEN-2).

**Statut : PROJET.**
- Rien n'est ancré, aucun essai n'est consommé, aucun seuil n'est choisi sur des données.
- Les cellules D3 positives de W1 ne sont PAS utilisées, et aucun résultat du pilote ne l'est.

**v0.2** = v0.1 (e3f6b6eb), corrigée selon l'audit R02 ca690ac3 (K-1 à K-5) et le cadre b4edc143 (extraits reçus de
R02) :
- K-1 : appartenance à la famille « 10 min » écrite dans chaque fiche, et une hypothèse INDÉPENDANTE de ce
  déclencheur (G2-3 remplacée) ;
- K-2 : M5 marquée non ancrée ;
- K-3 : M3 sort de la plausibilité ;
- K-4 : l'ancienne G2-3 est retirée de cette génération ;
- K-5 : table de notation, provisoire.

## 0. Cadre de la génération 2 (b4edc143 § 2 ; a21f90f3 § 3 et § 4)

- **Une génération = au plus 3 hypothèses gelées ensemble, sur une fenêtre DISJOINTE de celle de la génération 1
  (R-CP1, B1).** Il y a une autorisation de crédits distincte. L'option « même collecte » est REFUSÉE par R02 : elle
  ferait K = 5 sur la fenêtre de la génération 1.
- **Pilote** : α = 0,05 par hypothèse, n = 155, mot maximal GO_PILOTE.
- **Confirmation** : sur une fenêtre NOUVELLE, au choix du propriétaire :
  - (i), recommandé par R02 : α₂ = 0,025 par Holm, n_c = 262 ;
  - (ii) : 0,05/3, n_c = 221.
  - Holm contrôle le risque familial sous toute dépendance : aucune correction de plus.
- **Essais.** 170 → 173. Il faut une autorisation chiffrée du propriétaire (a21f90f3 § 4) : +3 essais.
- **Publication obligatoire** : la part des entrées COMMUNES entre les trois hypothèses, et entre chacune et les
  déclencheurs de type R-CP1 sur la même fenêtre. Ces déclencheurs sont recalculés par le code gelé, en descriptif.
- **Seuils** : médianes de POPULATION sur [T0 − 7 j ; T0), selon la méthode A1 (b) : sans rendement, données ≥ T0
  refusées par le code, valeur écrite dans la fiche de gel avant la fenêtre. R02 : note 2 au critère « degrés de
  liberté ».
- **Commun aux trois fiches.**
  - Lieu, univers U-1 à U-4, ordre, sorties, coûts et garde : ceux de R-CP1 (cpmmcost 0.3 ; TP / SL ±2 %, horloge
    30 min ; compte fermé).
  - Témoin apparié par pool, avec une graine propre à chaque fiche.
- **Données et coût.** Une fenêtre suivante, disjointe : ≤ 50 000 crédits pour 24 pools (même dimension que le
  pilote), 0 $ dans l'offre Free (1 M crédits par mois). D jours, recalculés par R03.

## 1. Conclusions mesurées utilisées, et leur statut

| # | Conclusion | Source | Statut pour la notation |
|---|---|---|---|
| M1 | Barrière de coûts ≈ 3,5 à 5,5 % sur la courbe LaunchLab, contre ≈ 0,8 à 1,1 % sur CPMM établi | Dossier A § 1 ; cpmmcost 0.3 ; catalogue R-1 v0.2 (4099bb7d) | Ancrée ; compte |
| M2 | Aucun avantage brut du MASTER : −0,72 % [−3,11 ; +1,65] | w1decomp 0.2, df0d9cbb | Ancrée ; compte |
| M3 | Pic médian à 5 slots, 1er passage sous l'entrée à 17 slots | w1decomp 0.2, D2 | **Motivation descriptive seulement** : postérieure à la décision, mesurée sur LaunchLab. Elle NE compte PAS dans la plausibilité (K-3) |
| M4 | Les vendeurs sont les détenteurs déjà présents | P0, instrument 3b16e5f7 | Ancrée ; compte |
| M5 | 57,7 % des signatures W1 sont des échecs | Inventaire R03 du 23/11, **non ancré** | Contexte seulement (K-2). Il vient des LISTES DE SIGNATURES, car l'export ne garde que les transactions réussies (`backfill_export.py`, l. 166-167). Aucune fiche ne repose dessus |
| M6 | Rien après la migration | Dossier A § 3 ; inventaire R03 | Ancrée : le lieu est le CPMM établi |
| M7 | Largeur de la demande : T1 latesel fait −5,59 % [−11,17 ; −0,09] sur la courbe, contre −10,29 % pour L1 sur la même moitié | latesel f3c6c9e3 ; latelab 20aba3f5 | Ancrée, mais l'écart est DESCRIPTIF et NON APPARIÉ. Ce n'est pas un gain. Elle motive G2-3 seulement parce que la barrière est 3 à 5 fois plus basse sur CPMM (M1) |

## G2-1 — « Chute non routée » (famille « 10 min »)

> **Famille « 10 min » (K-1).** G2-1 repose sur le déclencheur R-CP1. Elle est **RETIRÉE d'office si R-CP1 ET B1 sont
> NÉGATIVES** (règle gelée a21f90f3 § 2).

- **Mécanisme (M4, M2).**
  - Les swaps routés (`depth` > 1 : agrégateurs, arbitrages) portent l'information inter-lieux.
  - Les swaps directs sont plutôt des liquidations de détenteurs.
  - Une chute faite surtout de ventes directes est un choc de liquidité, que l'arbitrage doit corriger.
- **Variables à la décision.** Sens, montant quote, `depth` et réserves de chaque swap ≤ t (`cpmmx.timeline`).
- **Entrée.** Conditions (i) à (iii) de R-CP1 ET part du volume vendeur de ]t − 600 ; t] passée par `depth` > 1 ≤ m₁
  (médiane de population, avant T0).
- **Sortie, coûts, témoin.** Communs. Comparaison descriptive au sous-ensemble où cette part est > m₁.
- **n.** 155 au pilote ; n_c = 262 ou 221 en confirmation. Par construction, environ la moitié des déclencheurs de
  type R-CP1 de la fenêtre : `power_stop` déclare la sous-puissance d'avance.
- **Données et coût.** Fenêtre disjointe, ≤ 50 000 crédits, 0 $. Aucun code nouveau hors la règle.
- **Réfutabilité.** G-1 NO-GO si la borne haute est < 0. NON ÉVALUABLE si la part routée n'a aucune dispersion
  (médiane à 0 ou à 1).
- **Complémentarité.** Elle teste le MÉCANISME de R-CP1 sur une fenêtre neuve, au lieu de répéter son signal.

## G2-2 — « Épuisement vendeur » (famille « 10 min »)

> **Famille « 10 min » (K-1).** G2-2 repose sur le déclencheur R-CP1. Elle est **RETIRÉE d'office si R-CP1 ET B1 sont
> NÉGATIVES** (a21f90f3 § 2).

- **Mécanisme (M4).**
  - Une chute portée par des vendeurs pressés se poursuit tant qu'ils vendent.
  - Acheter après l'arrêt de leur flux, et non pendant, évite d'absorber l'offre restante.
  - M3 n'en est qu'une illustration descriptive sur LaunchLab, non comptée.
- **Variables à la décision.** Sens et montant quote de chaque swap ≤ t, spot après chaque swap.
- **Entrée.**
  - Un déclenchement de type R-CP1 à t₀ ouvre une attente de ≤ 1 800 s.
  - L'entrée a lieu au premier swap t₁ tel que, sur ]t₁ − 300 ; t₁] :
    - (a) le flux net quote est > 0 ;
    - (b) aucun spot n'est inférieur au plus bas de ]t₀ − 600 ; t₁ − 300].
  - Sinon, pas d'entrée, et c'est publié.
- **Sortie, coûts, témoin.** Communs. Le témoin est tiré parmi les swaps à moins de 1 800 s d'un déclenchement.
- **n.** 155 au pilote ; n_c = 262 ou 221.
- **Données et coût.** Comme G2-1.
- **Réfutabilité.** G-1. NON ÉVALUABLE si plus de 80 % des attentes finissent sans entrée.
- **Complémentarité.** Même événement que R-CP1, mais l'entrée est décalée et confirmée. Elle couvre l'étape de
  stabilisation, entre la chute (R-CP1) et la hausse (B1).

## G2-3 — « Élargissement de la demande » (INDÉPENDANTE du déclencheur R-CP1)

> **Hors famille « 10 min ».** G2-3 n'utilise NI la chute NI la hausse du prix. Elle survit aux verdicts de R-CP1 et
> de B1.

- **Mécanisme (M7, M1, M4).**
  - Quand le nombre d'ACHETEURS DISTINCTS d'un pool établi augmente nettement, une demande large et nouvelle arrive.
  - Ce n'est pas l'offre concentrée des détenteurs existants (M4).
  - Sur la courbe LaunchLab, la sélection par largeur de demande (T1) faisait mieux que l'entrée tardive non
    sélectionnée sur la même moitié (M7, descriptif et non apparié), mais restait sous une barrière de ≈ 3,5 %.
  - Sur CPMM, la barrière tombe à ≈ 0,8 à 1,1 % (M1).
- **Variables à la décision.**
  - Le SIGNATAIRE (payeur) de chaque swap d'achat ≤ t, lu dans la transaction brute collectée. C'est connu au moment
    de la transaction : R02 l'a jugé admissible (1070aae6, décision 4).
  - Les temps de bloc.
  - **Code nouveau** : l'extraction du signataire, absente de `cpmmx.timeline`. Elle passe par l'audit de R02 avant
    le gel.
- **Entrée.**
  - Au swap i (temps t), le nombre d'acheteurs distincts sur ]t − 600 ; t] est ≥ 2 × b₃(pool), ET aucune position
    G2-3 n'a été ouverte sur ce pool dans les 3 600 s.
  - b₃(pool) est la médiane, sur [T0 − 7 j ; T0), du nombre d'acheteurs distincts par fenêtre de 600 s de ce pool.
    C'est un seuil de population propre au pool, sans rendement, écrit dans la fiche de gel.
  - Le multiplicateur 2 est déclaré d'avance. **C'est le seul degré de liberté choisi sans donnée : à justifier
    devant R02.**
- **Sortie, coûts, témoin.** Communs. Le témoin est apparié par pool, à date aléatoire, avec la même contrainte de
  délai.
- **n.** 155 au pilote ; n_c = 262 ou 221. Le nombre de déclenchements est inconnu : il sera compté sur les 7 jours
  avant T0 (méthode A1 (b)), avec `power_stop`.
- **Données et coût.** Fenêtre disjointe, ≤ 50 000 crédits, 0 $. Le signataire est dans la transaction brute déjà
  collectée, sans crédit de plus. Le coût est le seul code d'extraction, à auditer.
- **Réfutabilité.** G-1. NON ÉVALUABLE si b₃ = 0 pour plus de la moitié des pools (pools trop peu actifs).
- **Complémentarité.** Elle est ORTHOGONALE à R-CP1 et à B1 : un signal de participants, pas de prix. Si la famille
  « 10 min » est close, G2-3 reste la seule piste vivante de la génération 2. La part des entrées communes avec les
  déclencheurs de prix est publiée.

**Retirée de cette génération : l'ancienne G2-3, « pools peu disputés ».** Elle supposait que la collecte garde les
signatures échouées (K-4). Son motif M5 n'est pas ancré (K-2). Elle pourra revenir dans une génération suivante si
R03 vérifie et chiffre la collecte des signatures échouées, et si l'autorisation le dit.

## 2. Table de notation sur les 8 critères — PROVISOIRE (K-5)

La table est notée de 1 à 3 selon les critères du propriétaire. **Les ancres de notation de `CRITERES_SELECTION_GENERATION2`
(a21f90f3 § 1) me manquent : cette table sera alignée sur elles en v0.3, puis contrôlée et ancrée par R02 avant T0.**

| Hypothèse | Plausibilité (M3 exclue) | Information nouvelle | Degrés de liberté (seuil de population = 2) | Coût | Durée | Données | Réfutabilité | Confirmation | Total |
|---|---|---|---|---|---|---|---|---|---|
| G2-1 chute non routée | 2 (M4, M2) | 2 (mécanisme de R-CP1) | 2 | 3 (0 $, aucun code) | 2 | 3 | 3 | 2 | **19** |
| G2-2 épuisement vendeur | 2 (M4) | 2 | 2 (seuils de 300 s et 1 800 s déclarés) | 3 | 2 | 3 | 2 (attentes vides possibles) | 2 | **18** |
| G2-3 élargissement de la demande | 2 (M7, M1, M4) | 3 (axe orthogonal au prix) | 2 (médiane par pool, ×2 déclaré) | 2 (code du signataire) | 2 | 2 | 3 | 2 | **18** |

**Proposition.**
- Les trois forment la génération 2.
- **Si R-CP1 ET B1 sont NÉGATIVES, G2-1 et G2-2 sont retirées d'office, et G2-3 reste seule.** Il faudrait alors la
  remplacer, ou la compléter par une hypothèse hors de la famille « 10 min », par une nouvelle fiche avant T0 de la
  génération 2.

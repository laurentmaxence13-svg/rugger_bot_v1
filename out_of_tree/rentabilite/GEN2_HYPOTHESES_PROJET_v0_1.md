# GEN-2 — Trois hypothèses de génération 2 après R-CP1 et B1 : fiches de préenregistrement en PROJET (v0.1)

RUGGER 01, 23/11/2026. Ordre permanent du propriétaire, relayé par R04 (tâche GEN-2). Soumis à l'audit de R02.

**Statut : PROJET.**
- Rien n'est ancré, aucun essai n'est consommé, aucun seuil n'est choisi sur des données.
- Les cellules D3 positives de W1 (n = 16 et 17) ne sont PAS utilisées, et aucun résultat du pilote, qui n'existe pas
  encore, ne l'est.
- Le classement sera fait selon les critères que R02 est en train de geler.
- Le cadre multigénérations de R02 (b4edc143) n'est pas encore entre mes mains. Les points qui en dépendent sont
  marqués **[cadre R02]**.

## 0. Conclusions mesurées dont partent les trois hypothèses

| # | Conclusion | Source ancrée | Ce qu'elle implique pour GEN-2 |
|---|---|---|---|
| M1 | Barrière de coûts ≈ 3,5 à 5,5 % sur la courbe LaunchLab, contre ≈ 0,8 à 1,1 % sur CPMM établi | Dossier A § 1 ; cpmmcost 0.3 ; catalogue R-1 v0.2 (4099bb7d) | Le lieu reste le CPMM ÉTABLI, comme pour R-CP1 et B1. Aucune hypothèse sur la courbe |
| M2 | Aucun avantage brut du MASTER : −0,72 % [−3,11 ; +1,65] | w1decomp 0.2, df0d9cbb | Un signal de début de courbe ne suffit pas : le levier est le coût ou l'état du marché |
| M3 | Après notre entrée, le pic médian est à 5 slots ; le 1er passage sous l'entrée, à 17 slots | w1decomp 0.2 (D2, postérieur à la décision) | L'offre latente se déverse juste après l'achat. Il vaut mieux acheter APRÈS l'épuisement des vendeurs que pendant leur vente (→ G2-2) |
| M4 | Les vendeurs sont les détenteurs déjà présents (−5 à −15 SOL à 300 s) | P0, instrument de cohortes 3b16e5f7 | Une chute portée par des vendeurs non informés (liquidité) est plus réversible qu'une chute portée par des flux informés (→ G2-1) |
| M5 | 57,7 % des signatures de W1 sont des ÉCHECS (compétition de robots) | Inventaire R03 du 23/11 (export ebe1959d) | Un pool très disputé expose notre ordre à 4 slots au pire cas H-1. Un pool peu disputé laisse plus de retour à capter (→ G2-3) |
| M6 | Rien après la migration : C-C est vide | Dossier A § 3 ; inventaire R03 | Pas de CPMM post-migration. Seulement des pools CPMM établis (U-1 à U-4) |

**Conséquences de cadre communes aux 3 hypothèses.**
- **Lieu, univers, ordre, sorties, coûts.** Ceux de R-CP1 :
  - pools CPMM établis, U-1 à U-4, liste U-2 hachée à T0 ;
  - achat de 0,1 SOL à +4 slots, H-1, garde de 20 000 ppm ;
  - TP / SL de ±2 % sur la valeur de vente exacte, sinon horloge à 30 min ;
  - compte fermé ;
  - cpmmcost 0.3.
  - Le seul degré de liberté nouveau de chaque hypothèse est sa condition d'entrée.
- **Seuils.** Quand il en faut un, c'est la MÉDIANE DE POPULATION mesurée sur les 7 jours avant T0, sans aucun
  rendement (même méthode que le comptage A1 (b)). R02 l'ancre avant la fenêtre.
- **Témoin.** Apparié par pool, construit comme celui de R-CP1, avec une graine propre à chaque fiche. Il est
  complété par une COMPARAISON APPARIÉE au sous-ensemble R-CP1 correspondant, descriptive.
- **Essais.** Ces 3 hypothèses dépasseraient 170 (N = 171 à 173). Elles exigent donc une autorisation chiffrée du
  propriétaire et une règle de correction ancrée par R02 **[cadre R02]**. Proposition : α = 0,05/3 au pilote pour la
  génération, et 0,05/3 en confirmation sur une fenêtre NOUVELLE.
- **n.** Avec σ = 2,5 % et δ = +0,5 % net, 221 entrées par hypothèse à α = 0,05/3 (formule de cpmmprereg).
- **Données, deux options.**
  - **(a) La collecte même du pilote R-CP1 / B1** : 0 crédit de plus. Il faut alors les fiches ANCRÉES AVANT T0, avec
    l'accord du propriétaire pour les essais 171 à 173.
  - **(b) Une fenêtre suivante** : ≤ 50 000 crédits par fenêtre de pilote, dans l'offre Free à 0 $ (1 M crédits par
    mois), D jours recalculés par R03.

## G2-1 — « Chute non routée » : rebond quand la chute vient de flux directs

- **Mécanisme (M4, M2).**
  - Sur CPMM, les swaps appelés par un autre programme (`depth` > 1 : agrégateurs, robots d'arbitrage) portent
    surtout de l'information inter-lieux. Ils ajustent le pool au prix du marché, et ce mouvement ne revient pas.
  - Les swaps directs (`depth` = 1) sont plutôt des détenteurs qui liquident : c'est le mécanisme M4.
  - Une chute faite surtout de ventes directes est donc un choc de liquidité, que l'arbitrage doit corriger.
- **Variables à la décision.**
  - Pour chaque swap ≤ t : sens, montant quote, `depth`, réserves avant et après (`cpmmx.timeline.Swap`).
  - Disponibles dans les transactions réussies, d'après l'inventaire R03.
- **Règle d'entrée.**
  - Les conditions (i) à (iii) de R-CP1 sont vraies, ET
  - la part du volume vendeur (quote) de ]t − 600 ; t] passée par des swaps `depth` > 1 est ≤ m₁, où m₁ est la
    médiane de population sur [T0 − 7 j ; T0).
- **Sortie, coûts, témoin.** Communs (§ 0). Comparaison descriptive au sous-ensemble R-CP1 avec part routée > m₁.
- **n.** 221. Par construction, environ la moitié des déclencheurs R-CP1 : le pilote est sous-puissant si R-CP1
  attend moins de 442 entrées. `power_stop` le déclare d'avance.
- **Durée.** Au moins 2 × D jours en option (b) pour atteindre 221, ou sous-puissance déclarée.
- **Données et coût.** Option (a) : 0 crédit. Option (b) : ≤ 50 000 crédits, 0 $. Aucun code nouveau hors la règle :
  `depth` est dans la timeline.
- **Réfutabilité.** G-1 NO-GO si la borne haute est < 0. Réfutée aussi si la part routée n'a aucune dispersion
  (médiane à 0 ou à 1) : NON ÉVALUABLE, déclaré d'avance.
- **Complémentarité.** C'est un SOUS-ENSEMBLE de R-CP1. Elle teste le mécanisme de R-CP1 (choc non informé) au lieu
  de répéter son signal. Si R-CP1 est NÉGATIF mais G2-1 positif, le mécanisme est localisé. Si les deux sont
  NÉGATIFS, la famille « choc de liquidité » est fermée.

## G2-2 — « Épuisement vendeur » : acheter après la fin de la pression, pas pendant

- **Mécanisme (M3, M4).**
  - Sur W1, notre prix passe sous l'entrée en 17 slots médians, parce que l'offre latente se déverse APRÈS l'achat.
  - Acheter au moment de la chute (R-CP1) revient à acheter pendant la vente.
  - Attendre que le flux net redevienne acheteur, sans nouveau plus bas, achète après l'épuisement des vendeurs.
- **Variables à la décision.** Sens et montant quote de chaque swap ≤ t, spot après chaque swap (timeline).
- **Règle d'entrée.**
  - Un déclenchement de type R-CP1 (conditions (i) à (iii)) au temps t₀ ouvre une attente de 1 800 s au plus.
  - L'entrée a lieu au premier swap t₁ ∈ ]t₀ ; t₀ + 1 800] tel que, sur ]t₁ − 300 ; t₁] :
    - (a) le flux net quote (achats − ventes) est > 0 ;
    - (b) aucun spot n'est inférieur au plus bas de ]t₀ − 600 ; t₁ − 300].
  - Sinon : pas d'entrée, et c'est publié.
  - Une position au plus par déclenchement ; délai (iii) appliqué à t₁.
- **Sortie, coûts, témoin.** Communs. Le témoin est apparié par pool, tiré parmi les swaps à moins de 1 800 s d'un
  déclenchement R-CP1.
- **n.** 221. Au plus le nombre de déclenchements R-CP1, moins les attentes sans entrée.
- **Durée et données.** Comme G2-1. Option (a) : 0 crédit.
- **Réfutabilité.** G-1. En plus, la part de déclenchements sans entrée est publiée : si elle dépasse 80 %, l'effectif
  est insuffisant et l'hypothèse est NON ÉVALUABLE, déclaré d'avance.
- **Complémentarité.** Même événement que R-CP1, mais une entrée DÉCALÉE et confirmée. B1 (momentum) achète la
  hausse, R-CP1 la chute, G2-2 la stabilisation. Les trois couvrent le cycle chute → stabilisation → reprise sans se
  recouvrir au même instant.

## G2-3 — « Pools peu disputés » : la compétition des robots comme coût caché

- **Mécanisme (M5, cpmmcost H-1).**
  - Un pool où beaucoup de transactions échouent est disputé par des robots plus rapides que nous. Notre ordre à
    4 slots y arrive après eux : le pire cas H-1 est alors probable, et la part du retour qui reste est faible.
  - Dans un pool peu disputé, le retour après choc reste davantage disponible.
- **Variables à la décision.**
  - Signatures du pool ≤ t avec leur statut (`err`) : la part d'échecs sur ]t − 3 600 ; t].
  - **Condition de données.** La collecte CPMM doit garder les signatures ÉCHOUÉES (statut « any », comme W1 :
    slot, ordre et erreur, sans corps). **R03 doit le vérifier sur la commande de collecte.** Sinon, G2-3 est NON
    ÉVALUABLE en option (a). En option (b), le surcoût est à chiffrer par R03 : pages de signatures, environ 10
    crédits par page.
- **Règle d'entrée.**
  - Les conditions (i) à (iii) de R-CP1, ET
  - une part d'échecs ≤ m₃, où m₃ est la médiane de population sur [T0 − 7 j ; T0), sans rendement.
- **Sortie, coûts, témoin.** Communs. Comparaison descriptive au sous-ensemble disputé (> m₃).
- **n, durée, coût.** Comme G2-1. Petit code nouveau : comptage des échecs par fenêtre à partir des signatures. Il
  passe par l'audit de R02.
- **Réfutabilité.** G-1, plus NON ÉVALUABLE si les signatures échouées sont absentes de la collecte.
- **Complémentarité.** C'est un sous-ensemble de R-CP1, sur un axe ORTHOGONAL à G2-1 : la compétition des
  exécutants, et non la nature du flux. Si G2-3 est positif et R-CP1 négatif, la perte vient de l'exécution et non du
  signal. Cela orienterait vers la latence (PAPER_LIVE S-3), pas vers de nouveaux signaux.

## Points soumis à R02 et au propriétaire

1. **[cadre R02]** Budget au-delà de 170 : une autorisation chiffrée, et la correction α = 0,05/3 pour la génération 2.
2. **Option (a) ou (b).**
   - (a) est gratuite, mais exige l'ancrage AVANT T0.
   - G2-1 et G2-3 sont des sous-ensembles de R-CP1 : leurs données recoupent celles de R-CP1. La confirmation sur
     une fenêtre nouvelle reste obligatoire dans tous les cas.
3. **Médianes de population sur les 7 jours avant T0** : est-ce une source de seuil admissible ? C'est la même méthode
   que A1 (b) : sans rendement, ancrée avant la fenêtre.
4. **G2-3** : vérification par R03 que la collecte garde les signatures échouées.
5. **Classement final** : selon les critères de sélection que R02 est en train de geler.

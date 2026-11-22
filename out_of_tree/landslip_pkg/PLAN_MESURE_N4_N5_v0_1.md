# P3-b — Plan de mesure hors ligne de N-4 (atterrissage) et N-5 (glissement), et garde de glissement (v0.1)

RUGGER 01, 22/11/2026. Ce plan applique les définitions et décisions de R02 : texte du 22/11 à 20:28Z, renvoyé à
21:10Z ; audit AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md, sha 0167b2d1. Rien n'a été exécuté hors des fixtures
publiques.

## 1. Ce que dit le moteur gelé (arbre aff97638), selon R02

| # | Poste | Moteur gelé |
|---|---|---|
| N-4 | Atterrissage | Supposé CERTAIN à +4 slots : ni non-inclusion, ni congestion |
| N-5 | Glissement | Pas de garde : l'achat exact-in s'exécute à n'importe quel prix d'atterrissage |
| N-6 | MEV et Jito | Non modélisés ; non modélisables hors ligne (limite déclarée) |

## 2. Données admises (décision 1 de R02)

- Développement et première mesure : SEULEMENT le pack P0 visible aca7de08.
- W1 : seulement après le PASS de R02 sur ce code, au titre de A2, en lecture DESCRIPTIVE. Jamais pour régler un
  paramètre de stratégie.
- Le holdout 9f19ccac : JAMAIS. Le script le refuse par son préfixe, en plus du contrôle du sha du MANIFEST ancré.

## 3. Ce qui est mesuré (`landslip.measure`, comptes seulement)

1. **Échecs des ACHATS d'autrui selon la priorité déclarée.** Pour chaque transaction collectée dont un cadre
   LaunchLab a pour instruction propre `BuyExactIn` ou `BuyExactOut` (lue avec une pile de programmes) :
   - échec, selon `meta.err` ;
   - prix du CU, tiré de `SetComputeUnitPrice` de ComputeBudget, par tranche : aucune, 0, ≤ 10 000, ≤ 100 000,
     ≤ 1 000 000, > 1 000 000 micro-lamports par CU.
2. **Écart de réaction d'autrui.** Pour chaque ACHAT décodé par `launchlab_events` gelé : le nombre de slots depuis
   l'événement précédent du même pool, par tranche : 0, 1, 2, 3, 4, 5-8, 9-32, > 32.
3. **Sortie.** Seulement des entiers sous des clés fixes : aucun pool, aucune signature, aucun montant, aucun slot.
   La sortie porte `measures_our_landing: false` et `descriptive_only: true`.

## 4. Ce qui n'est PAS mesurable, déclaré

- **NOTRE atterrissage.** Aucun ordre à nous n'existe. Les mesures (1) et (2) décrivent les autres opérateurs. Elles
  ne servent qu'à paramétrer une sensibilité déclarée d'avance, jamais à estimer notre probabilité d'inclusion.
- **Les achats échoués sans journaux exploitables.** Un achat échoué n'a pas d'instructions internes. Il n'est
  reconnu que par la ligne d'instruction de son cadre LaunchLab, une ligne qui peut être tronquée ; un achat tronqué
  est donc sous-compté, et ce biais est déclaré.
- **Les fixtures publiques ne contiennent AUCUNE transaction échouée** (0 sur 114). Le comptage des échecs n'est donc
  testé que sur des copies modifiées.
- **N-6 (MEV, Jito)** : non modélisable.

## 5. Garde de glissement (N-5), fixée par R02 AVANT toute donnée : `landslip.guard`

- **ACHAT, primaire.** Jetons minimaux = sortie exacte à l'état de DÉCISION × (1 − 20 000 ppm), arrondie vers le
  bas. Le remplissage est le pire des états d'atterrissage (H-1). S'il est sous le minimum, la transaction ÉCHOUE :
  105 000 lamports facturés, AUCUNE entrée, aucune relance.
- **ACHAT, sensibilité.** 50 000 ppm. Aucun autre seuil n'est accepté (`buy_guard_not_a_declared_threshold`).
- **VENTE, primaire.** Pas de garde.
- **VENTE, sensibilité.** Garde de 50 000 ppm sur la valeur exacte à l'état de décision de sortie. Une vente échouée
  est relancée 4 slots plus tard, jusqu'à 3 échecs, puis la vente se fait sans garde.
- **Garde désactivée (`None`)** : le remplissage gelé. C'est la base de l'identité avec le moteur gelé (P3-c).

## 6. Suite

1. R02 audite landslip 0.1 : mesure et garde.
2. Après son PASS : R03 exécute `landslip.measure` UNE fois sur P0 visible (A2) ; R02 ancre la sortie.
3. La garde est intégrée au moteur « coûts complets » (P3-c), dans un paquet nouveau.

# P3-b — Plan de mesure hors ligne de N-4 (atterrissage) et N-5 (glissement), et garde de glissement (v0.2)

RUGGER 01, 22/11/2026. **v0.2 = v0.1 (ecf7c410, PASS R02) + deux corrections documentaires, le code étant inchangé** :
(1) les données, selon la correction de R02 du 22/11 à 21:21Z ; (2) la mesure (i) des échecs est NON INFORMATIVE sur un
export sans corps de transactions échouées (constat de R02 du 22/11 à 22:42Z, après la mesure W1 ancrée 8ae58251).
 Ce plan applique les définitions et décisions de R02 : texte du 22/11 à 20:28Z, renvoyé à
21:10Z ; audit AUDIT_MODELE_COUTS_PAPER_CB_R02_v1_0.md, sha 0167b2d1. Rien n'a été exécuté hors des fixtures
publiques.

## 1. Ce que dit le moteur gelé (arbre aff97638), selon R02

| # | Poste | Moteur gelé |
|---|---|---|
| N-4 | Atterrissage | Supposé CERTAIN à +4 slots : ni non-inclusion, ni congestion |
| N-5 | Glissement | Pas de garde : l'achat exact-in s'exécute à n'importe quel prix d'atterrissage |
| N-6 | MEV et Jito | Non modélisés ; non modélisables hors ligne (limite déclarée) |

## 2. Données admises (décision 1 de R02)

- **Correction de R02 (21:21Z)** : aucune autorisation ne couvre P0 visible pour cette analyse. L'exécution unique se
  fait sur l'export W1 ancré ebe1959d, au titre de A2, en DESCRIPTIF (0 essai), après le verdict 0.5.1. Aucun
  paramètre gelé n'est modifiable au vu du résultat. Elle a été faite et ancrée (8ae58251).
- Jamais pour régler un paramètre de stratégie.
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
- **CORRECTION v0.2 — la mesure (i) des échecs est NON INFORMATIVE sur l'export W1.** L'export
  (`bot/market/backfill_export.py` l.166-167) n'écrit dans `transactions` que les transactions RÉUSSIES ; les
  échouées ne restent que dans `signatures` (l.168), sans journaux ni instructions. `landslip.measure` (l.105)
  parcourt `transactions` : le 0 obtenu (69 685 achats) est donc structurel, pas une mesure. C'est mon erreur de
  conception : la v0.1 supposait les corps échoués présents, sans vérification dans l'export. Une mesure correcte
  demanderait les corps des signatures échouées, donc une collecte nouvelle : BLOQUÉ PAR LE PROPRIÉTAIRE.
- **Les deux comptes n'ont pas la même unité** : (i) compte des transactions (une par transaction d'achat), (ii) des
  événements d'achat du pool ayant un prédécesseur. Écart (W1) = premiers événements des pools + événements d'un autre
  pool − achats multiples d'une même transaction.
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

1. R02 a audité landslip 0.1 : PASS.
2. R03 a exécuté `landslip.measure` UNE fois sur W1 ancré (A2, descriptif) ; R02 a ancré la sortie (8ae58251) :
   (ii) est informative : 60,4 % des achats suivent un autre trade du pool à ≤ 3 slots, 63,8 % à ≤ 4. C'est une densité
   d'activité, PAS un rang face au signal, et PAS notre glissement (erratum de R02, 22:45Z, repris ici). (i) ne l'est
   pas. N-4 reste NON MESURÉ.
3. La garde est intégrée au moteur « coûts complets » (P3-c), dans un paquet nouveau.

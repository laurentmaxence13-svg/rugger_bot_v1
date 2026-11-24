# T-R01-9 — Trois fiches de décision à présenter dès le résultat de T2 (v0.1)

RUGGER 01, 24/11/2026. Directive du propriétaire de 18:17Z, relayée par R04.
- Aucun rendement, aucun code nouveau.
- Entrées : la note T-R01-8 v0.2 (ae7f856 ; R02 6e2bf9af) et les mesures relayées par R04 / R03 :
  - 0,103 crédit par transaction ;
  - 24,6 % d'échecs, donc swaps ≈ 0,754 × signatures ;
  - 1 déclenchement R-CP1 pour 600 à 1 430 swaps.
- « NM » = NON MESURÉ. Les seuils ci-dessous sont **fixés avant T2**.

**Lecture de T2 (règle fixée d'avance).** On note N_a = nombre de pools CPMM 0,25 % de L, établis, réserve ≥ 100 SOL,
avec ≥ 239 signatures/j (= 180 swaps/j, la borne basse de T-R01-8).
- **FAISABLE** si N_a ≥ 39 : il y a de quoi qualifier, voir (a).
- **INFAISABLE** si N_a < 26 : même la borne la plus favorable ne suffit pas, voir (b).
- **INCERTAIN** si 26 ≤ N_a < 39, voir (c).

## (a) FAISABLE — qualifier les pools par leur fréquence de déclenchement

1. **Pools à compter** : les N_a pools de T2. Rien d'autre n'est lu.
2. **Comptage** : `cpmmprereg.trigger_count` (R-CP1) et `cpmmb1.trigger_count` (B1), code gelé PASS R02, sur
   [T0′ − 7 j ; T0′). Les données ≥ T0′ sont refusées par le code. Aucun rendement n'est calculé.
3. **Crédits** : 0,103 × 7 × Σ signatures/j des N_a pools, à chiffrer sur les signatures de T2.
   - Ordres de grandeur : 40 pools à 300/j ≈ **8 700** ; 60 à 500/j ≈ **21 600** ; 100 à 600/j ≈ **43 300**.
   - Ces montants restent dans l'offre Free tant que le quota du mois le permet (relevé du propriétaire).
4. **Durée** : NM. R03 la chiffre en pages GTFA à partir des signatures de T2.
5. **Critère d'entrée, fixé d'avance** : un pool entre dans U-2′ pour une hypothèse s'il a **au moins 3 déclenchements
   de cette hypothèse** sur les 7 jours, soit λ ≈ 1,4 sur 3,33 j.
   - Il faut alors **≥ 30 pools qualifiés par hypothèse** pour atteindre 20 pools entrés à 90 %.
   - Chaque hypothèse ayant ≥ 30 pools qualifiés reçoit une fenêtre.
   - En dessous de 30 pools qualifiés : (b).
   - Limite déclarée : les pools choisis sur un comptage passé déclencheront probablement moins ensuite (retour vers
     la moyenne). Le plancher G-1 reste juge.
6. **Texte de fenêtre à faire signer** :
   - T0′ ;
   - D ≤ crédits / (0,103 × Σ signatures/j) ;
   - U-2′ hachée ;
   - fiches R-CP1 et B1 inchangées hors univers, ancrées par R02 ;
   - réemploi des essais 169-170 (non consommés) ;
   - crédits du comptage et de la fenêtre.

## (b) INFAISABLE — réorienter vers N1 (fournisseur de liquidité), et mesurer G2-3

**N1, en clair.**
- **Qui paie** : chaque preneur paie 0,25 % du montant échangé. Le fournisseur de liquidité en garde 84 % (protocole
  12 %, fonds 4 % ; un frais créateur de 0,05 % existe dans D4FP, son application est NM).
- **Ce que coûte la position** : quand le prix bouge ailleurs, les arbitragistes rachètent ou revendent au pool à
  l'ancien prix. Le fournisseur subit cet écart, appelé **LVR** (perte face aux arbitragistes) ; cumulé sur le
  temps, il produit la perte d'inventaire. Il faut aussi compter nos transactions de dépôt et de retrait.
- **Hypothèse réfutable** : frais perçus − perte d'inventaire − coûts > 0 par pool-jour. Elle est plausible sur des
  pools où le volume est élevé par rapport à la volatilité.
- **Données** : swaps (montants, frais) et événements LP, déjà présents dans les pages GTFA « full » des pools
  collectés, y compris les pages A2r des 24 pools U-2 (à confirmer par R03). Aucun prix externe n'est nécessaire : on
  compare à la détention des mêmes jetons, valorisée au prix du pool.
- **Code à écrire** (à annoncer avant d'écrire) : un modèle de coût LP, part s du pool, frais cumulés, valeur de
  retrait contre détention, et nos 2 transactions, puis l'audit R02.
- **Statistique** :
  - unité = pool-jour, groupée par pool (inférence R02 R3) ;
  - n = 155 pool-jours (σ NM) ;
  - avec 20 pools actifs, ≈ 8 j ;
  - crédits : 0 au-delà de la collecte déjà faite si les pages A2r suffisent, sinon 0,103 × transactions.
- **Décision de principe à demander au propriétaire** : « J'autorise une recherche PAPER, côté fournisseur de
  liquidité, sur CPMM 0,25 % : un modèle de coût LP audité par R02, 1 essai, données déjà collectées d'abord. Ce n'est
  pas un trade du Master et cela ne compte pas pour 50/20. »

**G2-3 sur les pages A2r** (seulement si R02 l'autorise, comptage seul) : `cpmmgen2.trigger_count` dirait, pour les
24 pools U-2 :
- combien ont b₃ > 0 ;
- combien de déclenchements par jour et par pool.

Donc si G2-3 peut atteindre 20 pools entrés. Toute fenêtre de pilote G2-3 serait ensuite DISJOINTE de ces pages.

## (c) INCERTAIN — chiffrer la qualification complémentaire

- **Vérification exacte des créations**, ≈ 10 crédits par pool actif : pour 26 à 38 pools, ≈ **260 à 380 crédits**.
  Elle tranche l'éligibilité U-3/U-4 (pool établi, âge, création réelle) et peut faire tomber N_a sous 26 (→ b) ou le
  confirmer.
- **Comptage de déclenchements** de (a), limité à ces pools : 0,103 × 7 × Σ signatures/j, soit ≈ **5 600 à
  11 000 crédits** pour 26 à 38 pools à 300 à 400/j.
  - Il tranche la vraie question, la fréquence. ≥ 30 pools qualifiés → fenêtre ; sinon → (b).
- **Ordre recommandé** : d'abord les créations (≤ 400 crédits, peut suffire à conclure), ensuite le comptage.
- **Intérêt** : quelques centaines à ≈ 11 000 crédits pour ne pas lancer un pilote voué à INCONCLUSIF. Le pilote
  coûterait ≈ 14 100 à 33 700 crédits.

Candidates à 0 essai. Rien ici n'est un résultat économique.

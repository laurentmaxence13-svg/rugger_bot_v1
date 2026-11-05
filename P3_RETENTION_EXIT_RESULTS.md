# Contrôle v3 — analyse indépendante des sorties

27 octobre 2026 (Europe/Paris). Analyse entièrement hors réseau du bundle
`evidence/p3/retention_003` ; ancre vérifiée :
`914901e885fa97c87e7e81f0bd2750d0092a4cfb7a12f709c5402c993ed75fce`.
Aucune donnée historique modifiée, aucun portefeuille, aucune transaction.

## Résultat établi

Les deux ventes ont été refusées en HTTP 200 avec un corps JSON explicitement
conservé : `success=false`, `msg=INSUFFICIENT_LIQUIDITY` (observations **121** et
**139**). Il s'agit du motif déclaré par le fournisseur, pas d'une preuve générale
qu'une vente serait impossible après un achat réel.

Les achats indicatifs (observations **120** et **138**) portent respectivement
sur **34 193 904 632 554** et **34 193 904 631 450** unités atomiques pour un budget
de **1 SOL**. Les quatre snapshots cohérents produisent exactement ces quantités
par le calcul local. Ce rapprochement arithmétique ne certifie pas le slot du
devis API, qui reste inconnu.

- Premier candidat : `real_a=0`, `real_b=0`, vault WSOL **0 lamport**.
- Second candidat : `real_a=0`, `real_b=1`, vault WSOL **3 478 126 lamports**,
  dont **3 478 125 lamports de frais accumulés** ; disponible pour la courbe :
  **1 lamport**, pas 3 478 126.
- Ces faits sont inchangés dans les périodes initiales et suivantes.
- Sur ces quatre états observés, `observed_sell_projection` refuse la quantité
  positive du devis d'achat : `sell_exceeds_observed_outstanding_curve_tokens`.
  La quantité n'a jamais été acquise. Pour les états initiaux, cette comparaison
  est un diagnostic rétrospectif ; pour les followups, elle est fixée avant le
  snapshot ultérieur. Aucun achat hypothétique n'est injecté dans ces états.

## Contre-vérification indépendante

Une seconde méthode fondée sur le produit invariant **x*y**, avec calculs
rationnels exacts et arrondi des réserves restantes vers le haut, reproduit les
quatre projections conservées. Elle ne réutilise aucun helper de frais ou de
projection de production.

Pour une entrée hypothétique de **1 000 000 000 lamports** :

| Terme du modèle conditionnel | Lamports |
|---|---:|
| Frais de courbe d'entrée (1,25 %) | 12 500 000 |
| Entrée effective | 987 500 000 |
| Sortie brute après sa propre entrée, sans autre activité | 987 499 999 |
| Frais de courbe de sortie | 12 343 750 |
| Sortie après frais de courbe, avant frais supplémentaires | **975 156 249** |
| Écart au budget d'entrée, avant frais supplémentaires | **24 843 751** |

Cette inversion après sa propre entrée est **contrefactuelle**. Ce n'est ni une
cotation future fournie par l'API, ni une exécution, ni un P&L réalisé. Elle montre
pourquoi le refus d'une vente contre la banque vide ne suffit pas à conclure à
l'invendabilité après l'entrée qui aurait apporté des SOL.

## Limites et prochaine observation informative

L'administrateur initial de plateforme reste inconnu ; les devis ne fournissent
ni timestamp ni slot source. Frais réseau/priorité/ATA/échecs inconnus. Aucun
inventaire acquis ni sortie future observée. Deux candidats ne permettent pas
d'estimer une espérance économique.

Une expérience instrumentale distincte serait plus informative qu'un nouveau
échantillon de banques vides : préenregistrer un pool natif SOL aux liens
qualifiés avec `real_a>0` et quote réellement disponible, puis demander une vente
indicative pour une quantité définie avant réponse, par exemple
`min(quantité du devis d'achat de référence, floor(real_a/100))`, seulement si elle
est positive. Conserver états cohérents, frais séparés, rejets et followups. Les
règles de sélection, bornes 20 tentatives/60 secondes et accès gratuit doivent
être établis avant départ. Cette expérience qualifierait une vente dans l'état
observé ; elle ne certifierait toujours pas une sortie future de notre achat
hypothétique. Aucune nouvelle observation n'a été exécutée ici.

## Reproduction

```sh
python -B tools/analyze_p3_retention_exits.py
```

Le script vérifie les digests des quatre corps fournisseur, le bundle, les quatre
contre-calculs et les gardes de vente sur états observés. Verdict économique :
**INSUFFICIENT DATA**.

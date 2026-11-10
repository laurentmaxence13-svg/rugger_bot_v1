# Protocole technique pré-enregistré — simulateur MASTER V4 (« v4sim ») — version 2

- **Auteur :** RUGGER 03, 2026-11-10.
- **Statut :** version 2, à ancrer par RUGGER 02 AVANT toute implémentation expérimentale. Elle remplace le projet v1 (68683628…) et intègre les corrections C-1 à C-7 et les remarques non bloquantes de l'audit de RUGGER 02 (2a889ca3…).
- **Cadre :** décision du propriétaire du 2026-11-10 (« GO MASTER / SAUVEGARDES ET PRÉPARATION V4 », priorité 2).

Ce document fixe, avant d'écrire le code, CE QUE le simulateur doit calculer et COMMENT on saura qu'il est juste. Il ne fixe aucune stratégie, aucun paramètre d'entrée ou de sortie et aucun seuil de rentabilité. Il n'autorise aucun essai.

## 0. Périmètre et interdits

- **Objet.** Un moteur de rejeu contrefactuel pour les pools Raydium LaunchLab. Il corrige trois limites du moteur gelé (arbre aff97638), constatées par V3-P0-EXPLO-1 et V3-P0-NC-1 (audits de RUGGER 02 : 7d30b1f4…, f33d6d0e…) :
  - (L1) les ventes réelles des autres détenteurs sont rejouées avec leurs montants de tokens réels, alors que notre achat simulé leur en a laissé moins. La courbe se vide alors sous notre position : 50 positions sur 51 en `exit_refused: sell_exceeds_curve_inventory`.
  - (L2) une position dont la vente est refusée n'a pas de valeur calculée : la marque vaut 0 par repli, et le rendement −1 par convention.
  - (L3) une position encore ouverte à la migration vers CPMM est `migrated_unpriced`.
- **Hors périmètre.** Toute politique d'entrée ou de sortie, toute évaluation économique, toute promotion.
- **Interdits pendant ce protocole :**
  - aucun essai ni rejeu sur P0 (visible ou holdout), sur W1 ou sur toute donnée réservée ;
  - aucune modification de l'arbre gelé aff97638, du protocole W1 v2.6.2 ou de la chaîne dayj ;
  - aucune requête réseau, aucune dépense, aucune exécution réelle.
- **Isolation.**
  - Le code vit hors arbre, dans un paquet `v4sim` (comme `v3lab`), qui importe l'arbre gelé en lecture seule.
  - `v4sim` n'importe JAMAIS `w1aux`, `v3lab` ni dayj (C-6).
  - Il n'est jamais dans le répertoire, le processus ou le PYTHONPATH de dayj.
  - Son registre d'essais est séparé (aucun essai n'est prévu ici).
- **Données de mise au point autorisées :**
  - le pack de test gelé `tests/fixtures/launchlab_sol_pools` (3 pools) ;
  - des packs SYNTHÉTIQUES. Ils sont générés À PART, par un processus distinct qui n'importe pas `v4sim`. Chaque pack est ensuite haché (sha256 du MANIFEST et de chaque fichier, consignés) et lu par `v4sim` comme de simples fichiers (C-6).
  - Toute utilisation de données réelles relève d'un plan pré-enregistré distinct, ancré par RUGGER 02 et autorisé par le propriétaire.

## 1. Définitions

- **Événement réel** `e` : une ligne de la timeline gelée (`TradeEvent` : side, exact_in, amount_in, amount_out, frais, réserves avant et après, fee_payer, slot, block_time).
- **Monde réel** R : la suite des états de la courbe observés.
- **Monde contrefactuel** C : la même suite, à laquelle on ajoute NOS ordres.
- **Acteur** (C-5) : le PROPRIÉTAIRE du compte de token de l'utilisateur débité ou crédité par l'événement, lu dans les soldes de tokens avant et après de la transaction quand ils sont disponibles ; à défaut, le `fee_payer`. Le simulateur publie, par pack, la part des événements où propriétaire et `fee_payer` diffèrent, et la part où le propriétaire est indisponible. Limite déclarée en B-2.
- **Registre réel** `bal_R[a]` : tokens du pool détenus par l'acteur a d'après les seuls événements du pool (achats − ventes), à l'instant considéré.
- **Registre contrefactuel** `bal_C[a]` : la même quantité dans le monde C.
- **Stock externe** : tokens vendus par un acteur au-delà de son registre (reçus par transfert, ou achetés hors timeline). `E` est le cumul des tokens de stock externe vendus à la courbe. Comme ce stock est vendu tel quel (§2.1), E est le même dans R et dans C.
- **Causalité.** À l'instant d'une décision, le simulateur n'utilise que les événements d'index ≤ celui de la décision. Aucune règle des §2 à §5 ne lit un événement futur.

## 2. Simulation causale des achats et ventes des autres détenteurs (corrige L1)

### 2.1 Règle principale M-P (« budget en quote, fraction φ du registre »)

Après notre entrée, chaque événement réel est rejoué sur l'état contrefactuel :
- **Achat réel de a.** L'acteur dépense le même montant de quote qu'en réalité (`amount_in` réel, exact-in sur C). Il reçoit `q_C` tokens, calculés par la courbe exacte, et `bal_C[a] += q_C`.
- **Vente réelle de a, de `s_R` tokens.** On calcule la fraction vendue du registre réel : φ = s_R / bal_R[a] juste avant l'événement (0 < φ ≤ 1). L'acteur vend `s_C = floor(φ × bal_C[a])` tokens dans C.
  - Si `s_R > bal_R[a]`, l'excédent `s_R − bal_R[a]` est du STOCK EXTERNE. Il est vendu tel quel dans C (il ne dépend pas de la courbe), et la partie couverte par le registre suit φ = 1.
- Les registres R et C sont mis à jour après chaque événement. Avant notre entrée, R = C.
- Nos propres ordres ne changent pas le comportement des autres : mêmes instants, mêmes sens, mêmes budgets. Cette limite est déclarée en B-1. Les scénarios du §2.3 en donnent des variantes, sans la borner.

### 2.2 Invariants (vérifiés à chaque événement ; toute violation est une ERREUR, jamais un résultat)

Champs et signes du code gelé (`launchlab_curve.CurveState`, C-7) :
- `real_base` = tokens vendus par la courbe et encore en circulation. Un achat l'AUGMENTE de `amount_out` ; une vente le DIMINUE de `base_in`.
- `real_quote` = quote nette détenue par la courbe. Un achat l'augmente du net de frais ; une vente la diminue du brut.
- `remaining_base = total_base_sell − real_base`.

Invariants :
- **I-1, conservation des tokens.** À chaque événement : `Σ_a bal_C[a] + nos_tokens − E = real_base_C`. Dans le monde réel : `Σ_a bal_R[a] − E = real_base_R`.
- **I-2.** `bal_C[a] ≥ 0` pour tout a ; `real_quote_C ≥ 0` ; `0 ≤ real_base_C ≤ total_base_sell` ; `real_base_C < virtual_base` (validité de `CurveState`).
- **I-3.** Sans aucun ordre de notre part, C = R : après chaque événement, l'état contrefactuel est égal à `event.state_after()` CHAMP PAR CHAMP (virtual_base, virtual_quote, real_base, real_quote, total_base_sell).
- **I-4.** Une vente d'un acteur suivi par le registre ne peut jamais lever `sell_exceeds_curve_inventory`. Si elle le fait, c'est un défaut du simulateur : STOP.

### 2.3 Scénarios de sensibilité pré-déclarés (toujours publiés ensemble)

Les QUATRE modes sont toujours publiés ensemble (C-3) :
- **M-P (principal) :** la règle φ ci-dessus.
- **M-C (« plafonné ») :** chaque vente garde son montant réel, plafonné par le registre : `s_C = min(s_R, bal_C[a])`. Le stock externe est traité comme en M-P. C'est la plus petite déviation du moteur gelé qui supprime l'artefact L1.
- **M-L (« legacy ») :** le comportement du moteur gelé (montants de tokens réels inchangés). Il sert à la non-régression et à mesurer l'écart.
- **M-A (« stress comportemental ») :** comme M-P, mais tout acteur qui vend au moins une fois après notre entrée vend, à sa première vente, 100 % de `bal_C[a]`. C'est un SCÉNARIO DE STRESS, pas une borne (C-2) : rien ne garantit que la réalité soit moins défavorable.
- Aucun scénario « favorable » n'est défini : le simulateur ne suppose jamais que notre présence améliore le comportement d'autrui.

### 2.4 Cas limites

- **Achat réel exact-out** (`exact_in = false`) : on conserve le BUDGET en quote réellement dépensé. On note `exact_out_replayed_as_budget`.
- **Achat réel qui franchit la frontière de migration dans C mais pas dans R, ou l'inverse :** l'instant de migration dans C est celui où `remaining_base_C = total_base_sell − real_base_C` atteint 0 (convention gelée). Les événements réels de courbe postérieurs sont ignorés et comptés (`events_after_cf_migration`). Si C migre plus tard que R, le pool est marqué `cf_migration_later_than_real` et traité par le §4.
- **Montants trop petits** (`output_rounds_to_zero`, `input_consumed_by_fee`) pour un événement d'autrui : l'événement est sauté et compté (`skipped_dust_events`). Ce n'est pas un arrêt.

## 3. Valorisation quand la courbe est épuisée ou que la vente est refusée (corrige L2)

Une position entrée a TOUJOURS une valeur calculée. Il n'y a ni repli à 0 ni −1 de convention. À tout instant t, la **valeur de liquidation** `V(t)` est définie ainsi :

1. **Vente complète possible** (`sell_exact_in` accepte nos tokens) : V = sortie nette exacte.
2. **Vente limitée par la réserve de quote** (`sell_exceeds_quote_reserve`) : on vend la plus grande quantité q ≤ nos tokens telle que le brut ≤ `real_quote_C`, trouvée par recherche exacte sur entiers. V = sortie nette de q ; les tokens restants valent 0. Drapeau `partial_liquidation`.
3. **Vente limitée par l'inventaire.** Cela ne peut arriver qu'en présence de stock externe, cf. I-4. On applique la règle 2 avec q ≤ `real_base_C`. Drapeau `external_inventory_limited`.
4. **Sortie nulle par arrondi :** V = 0, exactement et de façon justifiée. Drapeau `dust`.

- **Rendement.** r = (V − coût) / coût, avec coût = mise + coûts de transaction engagés, y compris la vente. Le résultat est borné par construction : r ≥ −1.
- **Publication.** Pour chaque position, on publie `V` sous M-P, M-C, M-L et M-A, avec ses drapeaux. Les agrégats sont donnés AVEC et SANS les positions à drapeau `external_inventory_limited`.
- **Stock externe.** On publie aussi, par jeu, la part du VOLUME de tokens vendus après notre entrée qui provient du stock externe.
- **Garde.** Si la part des positions entrées à drapeau `external_inventory_limited` dépasse 5 % d'un jeu, le rapport porte la mention `EXTERNAL_INVENTORY_ABOVE_LIMIT`. Aucun agrégat de ce jeu ne peut alors servir de décision.

## 4. Sorties après migration vers CPMM (corrige L3)

### 4.1 Ce qui est modélisé

- **Tokens.** Nos tokens restent dans notre portefeuille à la migration, et leur quantité ne change pas.
- **Fenêtre sans marché.** Entre le dernier événement de courbe et la création du pool CPMM, aucune vente n'est possible. Un ordre de sortie décidé dans cet intervalle atterrit au premier slot où le pool CPMM existe, plus la latence.
- **Pool CPMM.** C'est un produit constant x·y = k avec frais. Les réserves initiales, le taux de frais et les éventuels frais de créateur sont LUS dans les données on-chain : transaction de migration, compte de configuration du pool. Ils ne sont jamais supposés.
- **Rejeu contrefactuel sur CPMM.** Les règles du §2 s'appliquent (budget en quote pour les achats, fraction du registre pour les ventes), avec les registres continués depuis la courbe. Les réserves initiales de C sont celles de R, corrigées de l'écart de quote et de tokens que notre position a créé sur la courbe, si la règle de migration le transmet au pool. Sinon elles sont identiques à R. Le choix entre les deux est fixé par lecture du programme et consigné AVANT tout calcul.
- **Valeur de liquidation sur CPMM.** Sortie exacte du swap de nos tokens sur l'état contrefactuel, frais déduits.

### 4.2 Ce qui manque aujourd'hui (constat, pas une demande)

- Les archives actuelles (P0, pilote, futur W1) ne contiennent PAS les événements CPMM postérieurs à la migration.
- Les valoriser demande :
  - (a) un décodeur d'événements CPMM ;
  - (b) une collecte par pool migré : transaction de migration, puis swaps du pool sur l'horizon de détention.
- Cette collecte n'est ni prévue ni autorisée ici. Elle ne peut concerner qu'une fenêtre NEUVE (W2), avec un budget de crédits à faire valider par le propriétaire.
- W1 reste évalué par le moteur gelé. La limite est déjà notée par RUGGER 02 pour le verdict W1.

### 4.3 Règle transitoire (tant que les données CPMM manquent)

- Une position ouverte à la migration garde l'issue `migrated_unpriced`. Elle n'est PAS créditée dans le P&L.
- On publie en plus, à titre descriptif seulement :
  - `last_curve_value`, la valeur de liquidation au dernier état de courbe cohérent ;
  - `last_curve_age_s`.
- Les agrégats sont publiés sous deux conventions, toujours ensemble : (i) positions migrées exclues ; (ii) positions migrées valorisées à `last_curve_value`, avec la mention « borne non réalisable, vente non simulée ».

## 5. Frais, glissement, échecs de transaction et limites de liquidité

### 5.1 Frais

- **Frais de trade sur la courbe.** Taux par pool, estimé causalement par la règle gelée `causal_fee_rate` (le plus grand taux compatible avec la plus longue suite cohérente d'événements jusqu'à la décision). Le taux et sa preuve sont consignés par ordre.
- **Frais de trade sur CPMM.** Lus dans la configuration du pool (§4.1).
- **Frais de transaction (C-1).** Frais de base (5 000 lamports par signature) + frais de priorité, prélevés sur toute transaction INCLUSE dans un bloc, qu'elle réussisse ou qu'elle échoue à l'exécution (§5.3).
  - Frais de priorité, scénario principal : 100 000 lamports (valeur du moteur gelé).
  - Sensibilité : {10 000 ; 100 000 ; 1 000 000}.
  - Un pourboire de bundle (Jito) est un paramètre distinct, nul par défaut. Il n'est dû que si la transaction est incluse.
- **Loyer du compte de token.** Supposé récupéré à la fermeture (convention gelée). L'immobilisation n'est pas comptée. Si une position finit en `partial_liquidation` avec un reliquat, le loyer N'EST PAS récupéré : il est compté en coût.

### 5.2 Glissement et tolérance

- L'impact de prix de nos ordres est EXACT (mathématique de la courbe ou du CPMM sur l'état contrefactuel à l'atterrissage). Il n'est jamais approché.
- Chaque ordre porte une tolérance de glissement `slippage_bps`. Le minimum reçu est calculé sur l'état connu À LA DÉCISION. Si l'état à l'atterrissage donne moins, la transaction ÉCHOUE : §5.3. C'est un ajout par rapport au moteur gelé : il ne vaut que pour V4 (W2). W1 n'est pas modifié.
- Grille pré-déclarée : {100 ; 500 ; 1 500 ; sans limite} points de base.

### 5.3 Latence, ordre dans le slot et échecs

- **Latence d'atterrissage.** Un ordre décidé au slot s atterrit après le dernier événement réel de slot ≤ s + L (convention gelée). L principal = 4 slots ; sensibilité {2 ; 4 ; 10}.
- **Ordre dans le slot d'atterrissage.** Principal : APRÈS toutes les transactions réelles du slot (pessimiste, convention gelée). Sensibilité : avant.
- **Échec à l'exécution** (glissement du §5.2, erreur du programme). Il est déterministe. La transaction est incluse : elle paie le frais de base ET le frais de priorité. L'achat n'a pas lieu, ou la position reste ouverte.
- **Non-inclusion.** Avec une probabilité `p_fail`, l'ordre n'est pas inclus. Le tirage est PSEUDO-ALÉATOIRE DÉTERMINISTE : sha256(pool, index de décision, numéro de tentative, sel). Grille : {0 ; 0,10 ; 0,25}.
  - Règle visée (C-1) : une transaction non incluse ne paie AUCUN frais, ni base, ni priorité, ni pourboire.
  - Cette règle n'est appliquée qu'une fois la référence de la documentation officielle Solana consignée dans le MANIFEST de `v4sim` (adresse, date de lecture, sha256 du texte archivé), AVANT tout calcul.
  - D'ici là, l'hypothèse prudente s'applique : une non-inclusion paie le frais de base.
- **Nouvelles tentatives.** Paramètres de la politique d'exécution (nombre maximal, délai), consignés. Chaque tentative est un ordre complet, avec sa latence, ses frais et sa tolérance.

### 5.4 Limites de liquidité

- **Taille d'ordre.** Grille pré-déclarée {0,05 ; 0,1 ; 0,5 ; 1} SOL. Principale : 0,1 SOL, comme le moteur gelé.
- **Refus d'entrée** dans deux cas :
  - notre achat franchirait la frontière de migration ;
  - notre achat dépasserait une part `max_curve_share` des tokens restant à vendre. Grille {5 % ; 20 % ; sans limite} ; principal 20 %.
- **Sortie.** Bornée par `real_quote_C` (§3, règle 2). Une sortie en plusieurs tranches n'est simulée que si la politique d'exécution la demande explicitement, chaque tranche payant ses frais.
- **Non modélisé, et déclaré :** attaques sandwich et MEV sur nos ordres, copie de nos ordres par des tiers, congestion extrême. Borne par B-3.

## 6. Tests de reproductibilité et critères d'acceptation du simulateur

Le simulateur n'est déclaré UTILISABLE que si TOUS les critères suivants sont remplis, sous CPython 3.12.3, `-W error`, hors réseau, sur les seules données du §0.

| Id | Test | Critère d'acceptation |
|---|---|---|
| A-1 | Rejeu d'identité (I-3) : aucun ordre de notre part | 100 % des événements : état contrefactuel = `event.state_after()` champ par champ (5 champs), sur le pack gelé et les packs synthétiques, dans les quatre modes |
| A-2 | Invariants I-1, I-2, I-4 | 0 violation sur 10 000 flux d'ordres pseudo-aléatoires à graines fixes (tests de propriété), toutes tailles de la grille |
| A-3 | Non-régression M-L | Point d'entrée : `w1_run.run_trials` gelé sur le synthétique ×40, la fonction `replay` étant remplacée par celle de `v4sim` en mode M-L, mêmes paramètres. Les bundles sont IDENTIQUES À L'OCTET : le sha256 des SUMS vaut ba14a5db7a66b277f59b9ddf2222bb9364b33e75496483300707aadef5044b72 (référence déjà ancrée sur trois machines). Même contrôle sur le pack gelé (4aee76a3…) |
| A-4 | Continuité | Mise = la plus petite mise qui donne au moins 1 token à l'entrée, cherchée par pool (1 lamport donne 0 token : le test serait vide). Valeur de chaque position sous M-P et sous M-C = valeur sous M-L, à l'arrondi près (≤ 1 unité atomique par événement rejoué). Le test exige au moins 100 positions entrées, sinon il ÉCHOUE |
| A-5 | Artefact L1 supprimé | Sur un pack synthétique de stress (tous les autres détenteurs revendent après notre entrée) : 0 `sell_exceeds_curve_inventory` sous M-P, M-C et M-A, et la valeur de liquidation de notre position, calculée À LA MAIN dans le test, est retrouvée exactement |
| A-6 | Valorisation L2 | Cas construits pour chacune des règles 1 à 4 du §3 : valeur attendue exacte ; r ≥ −1 pour 100 % des positions ; aucune position entrée sans valeur |
| A-7 | Déterminisme | Deux exécutions, puis 1, 2 et 4 processus : sha256 des sorties identiques ; empreinte du code consignée dans chaque sortie |
| A-8 | Monotonie | Taille d'ordre croissante : tokens reçus par SOL jamais croissants ; `p_fail` et latence croissants : aucun ordre réussi supplémentaire sans cause tracée |
| A-9 | Échecs et frais | Cas construits : glissement dépassé (base + priorité), non-inclusion (selon la règle en vigueur du §5.3, consignée dans la sortie), nouvelle tentative ; les frais débités sont égaux aux frais attendus au lamport près |
| A-10 | Mutation | Chaque défaut injecté est détecté par au moins un test : conservation désactivée, frais ×0, latence 0, repli à 0 réintroduit, lecture d'un événement futur |
| A-11 | Recalcul indépendant | RUGGER 02 réimplémente les règles M-P et M-C et le §3 sur un pack synthétique et obtient, position par position, les mêmes valeurs |
| A-12 | CPMM (§4.1), seulement quand des données existeront | Le module reproduit la sortie réelle d'au moins 99,9 % des swaps observés à l'unité atomique près ; les écarts sont expliqués un par un |

- **Arrêt.** Si un critère échoue, on corrige, puis on repasse TOUS les tests. Aucune dérogation au cas par cas.
- **Livrables d'acceptation :** code `v4sim` et son MANIFEST (sha256 par fichier), journal des tests, rapport d'acceptation, le tout audité et ancré par RUGGER 02.

## 7. Biais et limites déclarés

- **B-1.** Les autres acteurs ne réagissent pas à notre présence : mêmes instants et mêmes budgets. En réalité, un achat visible peut attirer ou faire fuir. M-A en donne un scénario de stress. Ce n'est pas une borne, et rien ne le mesure.
- **B-2.** Acteur = propriétaire du compte de token, à défaut `fee_payer` (§1). Un même propriétaire peut utiliser plusieurs portefeuilles, et des tokens peuvent circuler par transfert. Cela se traduit en stock externe (§2.1), qui est compté en positions et en volume (§3).
- **B-3.** MEV, sandwich et copie ne sont pas modélisés. Avant toute lecture économique future, un scénario de stress pré-déclaré devra être ajouté au plan d'essai : prix d'entrée dégradé de X points de base, X étant fixé dans ce plan.
- **B-4.** La valeur après migration reste inconnue sans données CPMM (§4.2). Aucun résultat ne peut créditer une position migrée avant A-12.
- **B-5.** Les hypothèses V4 sont formées après lecture des résultats V3 sur P0. V4 est donc un outil, pas une preuve. Toute preuve économique exige une fenêtre neuve et un plan pré-enregistré.

## 8. Étapes et contrôles

1. **V4-0 (ce document).** Audit et ancrage par RUGGER 02 ; corrections intégrées dans une version numérotée.
2. **V4-1.** Implémentation hors arbre et tests A-1 à A-11, sur le pack gelé et le synthétique UNIQUEMENT. Audit du code et recalcul A-11 par RUGGER 02. Le compteur d'essais N reste à 34 : la mise au point du simulateur n'est pas un essai de stratégie.
3. **V4-2.** Rapport d'acceptation ancré. Le simulateur est alors « utilisable », rien de plus.
4. **Au-delà (hors de ce protocole, décision du propriétaire).** Plan d'essai pré-enregistré sur une fenêtre neuve W2, incluant la collecte CPMM et son budget. Aucun usage sur P0, W1 ou une donnée réservée sans plan ancré.

Aucune stratégie n'est promue par ce protocole. Aucune exécution réelle, aucune dépense.

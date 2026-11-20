# Pertes W1 : analyse et propositions chiffrées — v0.1 (RUGGER 01, 2026-11-20)

**Statut.** EXPLORATOIRE. Cette note n'a pas encore été auditée par RUGGER 02. Elle ne modifie aucun résultat W1,
ne fige rien et ne lance rien. Elle répond à la directive du propriétaire du 20/11 (phase « rentabilité »).

**Sources.** Seuls deux ensembles de chiffres sont utilisés :
- les chiffres W1 ANCRÉS : bilan vérifié par R02, lecture `LECTURE_PRELIMINAIRE.json` (ea152a32), registre
  62d8eae8 ;
- les résultats P0 déjà vérifiés par R02 et ancrés.
Les ventilations détaillées de W1 viendront de l'outil `w1loss` 0.1 (section 5), après l'audit de R02 et
l'exécution par R03.

## 1. D'où vient la perte (W1, chiffres ancrés, mise de 0,1 SOL)

| Par position, en % de la mise | MASTER (128 clôturées) | Placebo (343 clôturées) |
|---|---|---|
| Brut : évolution du prix pendant la détention | −0,72 % | −0,19 % |
| Coût : frais de la courbe (achat et vente) | 3,34 % | 4,20 % |
| Coût : frais de transaction | 0,21 % | 0,21 % |
| Coût : glissement de nos ordres | négligeable | négligeable |
| **Net** | **−4,27 %** (moyenne publiée : −4,26 %) | **−4,60 %** (publiée : −4,59 %) |

Calcul : total de la ligne divisé par le capital engagé, soit 12,8 SOL pour le MASTER et 34,3 SOL pour le placebo.
Les écarts de 0,01 point avec la moyenne publiée viennent de son dénominateur, qui ajoute les frais de transaction
à la mise.

**Lecture.**
1. **Les frais de courbe font 78 % de la perte**, mais ils ne l'expliquent pas seuls. Sans aucun frais de courbe,
   le MASTER resterait à −0,93 % (brut −0,72 %, plus 0,21 % de transaction). Il n'existe aujourd'hui **aucun
   avantage brut à l'entrée**.
2. **L'écart du MASTER sur le placebo (+0,33 point net) vient des frais, pas du choix du moment.**
   - Son brut est plus mauvais que celui du placebo : −0,72 % contre −0,19 %, soit −0,53 point.
   - Ses frais de courbe sont plus bas : 3,34 % contre 4,20 %, soit +0,86 point.
   - Mise en garde : les pools ne sont pas les mêmes d'un bras à l'autre. L'écart apparié, pool par pool, sera
     donné par w1loss (tableau T6).
3. **Sorties** : 58 arrêts de perte, 29 prises de bénéfice et 41 sorties à l'horloge, avec 30,5 % de positions
   gagnantes. La part des arrêts de perte (45 %) concorde avec un brut négatif dès l'entrée.
4. **Le MASTER est identique à la référence** par construction du code gelé (confirmé le 20/11). W1 ne compare donc
   le MASTER qu'au hasard.
5. **Loyer du compte de token.** Les chiffres W1 supposent qu'il est rendu, c'est-à-dire que le compte est fermé
   après la vente (`bot/market/replay.py` l. 24). En réel, sans cette fermeture, chaque opération perdrait environ
   2,05 points de plus (mesure P0).

**Ce que P0 avait déjà établi** (159 essais, vérifiés par R02) : en début de courbe, aucune sélection n'a donné un
rendement net positif. Cela couvre :
- 34 signaux ;
- 50 cellules état × horizon ;
- 7 règles de sortie ;
- la répétition des cinq hypothèses gelées.

La meilleure règle de sortie (« première vente réelle ») ne gagne que +0,41 point, avec un intervalle de [−1,17 ;
+1,82]. Le palier de frais est le signal le plus lié au résultat (corrélation −0,44).

## 2. Le seuil à franchir : le brut nécessaire selon les frais

Une position n'est rentable que si son brut dépasse ses coûts. Le seuil vaut à peu près 2 × le taux de frais par
transaction + 0,21 % de frais de transaction. Le loyer est supposé rendu.

| Lieu, taux par transaction (achat ou vente ; paliers LaunchLab de P0, à confirmer sur W1 par T1) | Brut nécessaire par aller-retour | Brut actuel du MASTER |
|---|---|---|
| CPMM après migration, 0,25 % | **≈ 0,71 %** | inconnu (aucune donnée) |
| LaunchLab, palier 1,25 % | ≈ 2,71 % | à mesurer (T1) |
| LaunchLab, palier 1,75 % | ≈ 3,71 % | à mesurer (T1) |
| LaunchLab, palier 3,75 % | ≈ 7,71 % | à mesurer (T1) |
| MASTER W1, moyenne observée (≈ 1,67 % par transaction) | ≈ 3,55 % | −0,72 % |

Il manque donc environ 4,3 points de brut au MASTER actuel. Sur CPMM, il n'en manquerait plus qu'environ 1,4,
SI son brut y restait le même, ce qu'aucune donnée ne permet de dire.

## 3. Propositions chiffrées

Les effets « attendus » sont des ordres de grandeur arithmétiques tirés des chiffres ci-dessus. Ce ne sont pas des
résultats.

| # | Proposition | Effet attendu sur le net | Avantages | Limites | Conditions de validation |
|---|---|---|---|---|---|
| S1 | **Ne trader que le palier de frais le plus bas** (taux causal lu à la décision) | +0,8 point si le brut ne change pas : 3,34 % → 2,50 %. Net attendu ≈ −3,4 %. Sur P0, H1 : −3,24 % contre −4,94 % (59 positions) | Simple ; signal causal déjà calculé ; effectif suffisant sur W2 (environ 790 positions en 5 jours, fiche K) | **Insuffisant seul** : il faudrait encore un brut ≥ +2,7 % ; la sélection peut changer le brut | Stratégie préenregistrée sur W2 ; famille de Holm ; écart au placebo restreint au même palier ; R-1 (≥ 200 positions et ≥ 100 créateurs) |
| S2 | **Trader sur CPMM après la migration** (0,25 % par transaction) | Frais de courbe 3,34 % → 0,50 %, soit −2,8 points par rapport à la moyenne W1 ; seuil de brut ≈ 0,71 % | Le seul levier qui ramène le seuil sous 1 % ; outils prêts (`cpmmlab` 0.1, décodeur `cpmmx`, protocole CPMM v1.2) | **Aucune donnée** ; brut inconnu ; peu de pools migrent (R03 estime 50 à 100 pools sur W1) ; concurrence après l'ouverture | (a) Collecte CPMM des pools W1 migrés : accord du propriétaire, crédits gratuits ≈ 7 500 (fourchette 500 à 60 000), plafond et arrêt à 98 %, règle ancrée par R02 ; (b) lecture exploratoire (comptée dans N) ; (c) W2 préenregistré avec couverture CPMM |
| S3 | **Changer la règle d'entrée** (le MASTER ≡ early_sniping aujourd'hui) | Il faut un brut ≥ +3,5 % aux frais actuels, ou ≥ +0,7 % sur CPMM. Attente basse : P0 n'a rien trouvé en début de courbe | Vise la vraie cause : l'entrée | Le risque de surajustement est le plus élevé ici | Candidats écrits AVANT toute lecture : (a) `confirmed_momentum` et `adaptive_hybrid` comme bras séparés (code gelé existant) ; (b) mécanismes HW1, après leur lecture unique ; (c) une seule cellule `jointlab`, choisie sur la 1re moitié de W1 et passée au crible sur la 2e. Confirmation sur W2 uniquement |
| S4 | Règle de sortie | ≤ +0,5 point (meilleure règle P0 : +0,41 [−1,17 ; +1,82]) | Bon marché | Effet faible : la perte vient de l'entrée | Au plus une variante dans W2, sinon aucune |
| S5 | **Fermer le compte de token après la vente** (loyer rendu) | Ce n'est pas un gain : c'est une **condition** pour que le réel ressemble à W1. Sans elle, −2,05 points | Déjà supposé par le rejeu | Le code réel doit le faire et le prouver (branche `claude/r01-live-close-base-ata`) | Test hors ligne + simulation à blanc ; jamais d'ordre réel sans accord |
| S6 | Mise plus grande (0,5 SOL) | Transaction 0,21 % → 0,04 %, soit +0,17 point, mais glissement et impact plus forts | — | Marginal, voire négatif | Déjà prévu comme stress (fiche K) ; pas une stratégie |
| S7 | **Ne pas trader** (abstention) | 0 % | Référence absolue | — | Chaque candidat doit battre 0 net ET le placebo |

**Conclusion honnête.** Aucune combinaison de leviers connus ne donne aujourd'hui une rentabilité positive
démontrée.
- **Seule voie arithmétiquement plausible** : S2 (CPMM, seuil ≈ 0,7 %) associée à une entrée dont le brut dépasse
  ce seuil.
- **Voie LaunchLab** : S1 + S3 exigent un brut ≥ +2,7 %, que rien ne laisse attendre en début de courbe.
- **États encore inexplorés** : fin de courbe et pools survivants. P0 n'en contient presque pas, W1 si
  (hypothèses HW1-3 et HW1-4, à lire une seule fois, après le verdict officiel).

## 4. Proposition de bras pour W2 (à intégrer au protocole indépendant de R02)

Au plus 5 bras, référence et placebo compris (fiche K v0.1). Chaque bras est figé avant le premier slot de W2.

| Bras | Rôle | Dépend de |
|---|---|---|
| A0 MASTER actuel (≡ early_sniping) | référence ; vérifie que le résultat de W1 se reproduit | rien |
| A1 Placebo (âge aléatoire, règle gelée) | contrôle | rien |
| A2 S1 palier bas | candidat | rien |
| A3 S2 CPMM après migration (+ HW1-M1 traversée, si lue) | candidat | collecte CPMM W1 (B2) et couverture CPMM dans W2 |
| A4 Meilleure entrée S3, UNE seule | candidat | lecture HW1 (B1) et/ou passe `jointlab` sur W1 |

Si B1 ou B2 n'est pas levé avant le gel, le bras correspondant est retiré. Il n'est jamais remplacé après coup.

## 5. Ventilation W1 à exécuter (w1loss 0.1, après l'audit de R02)

L'outil ne lit que les lignes MASTER, référence et placebo du ledger ancré. Il ne calcule aucun déclencheur HW1 ;
les classes d'âge s'arrêtent à ≥ 450 slots. Liste fermée des tableaux :
- T0 : totaux, à comparer à la lecture ancrée ;
- T1 : par palier de frais ;
- T2 : contrefactuel au taux 0, au taux 0,25 % et au palier le plus bas, au premier ordre ;
- T3 : par motif de sortie ;
- T4 : par âge à l'entrée ;
- T5 : par tiers chronologique ;
- T6 : écart apparié MASTER − placebo ;
- T7 : quantiles du brut ;
- T8 : par plan TP/SL du scoreur.

Ces tableaux sont **descriptifs**, sans intervalle ni sélection. Leur comptage dans N est à décider par R02.
Commande pour R03, avec les bornes `w1_collection.bounds(467275745)` :

    python -B -m w1loss.analysis --ledger <ledger.json ancré> --ledger-sha256 <ancré> \
        --l1-bundle <run/bundles/L1.json.gz> --evaluation-min 467678545 --evaluation-max 469291345 --out <OUT>

## 6. Décisions du propriétaire dont dépend le plan W2 (à présenter par R04)

- **B1 — Verdict officiel W1.** Il demande une dépense de calcul (note voie B v0.3). Il précède la lecture unique
  des hypothèses HW1, et donc le bras A4 s'il en dépend.
- **B2 — Collecte CPMM des pools W1 migrés.** Crédits Helius gratuits estimés à environ 7 500, sans abonnement.
  Elle conditionne le bras A3.
- **B3 — Fenêtre W2.** Calendrier : après le gel, la préférence de R02. Source : plan Helius gratuit après la
  remise à zéro du 07/12, ou plan payant. Plafond de crédits.
- Rien n'est lancé, collecté ni dépensé sans accord explicite. Les seuils protégés de l'entrée opérationnelle
  (50 cycles qualifiés, 20 créateurs) restent inchangés.

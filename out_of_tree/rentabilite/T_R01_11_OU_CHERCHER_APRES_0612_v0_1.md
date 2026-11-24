# T-R01-11 — Après le 06/12 : où chercher ensuite (v0.1)

RUGGER 01, 24/11/2026. Demande R04 (23:16Z).
- Hors ligne : aucune donnée de fenêtre, aucun essai, aucun crédit.
- Le plafond exploratoire de 170 essais est atteint : rien ici n'est lancé sans décision explicite.
- Les paramètres de protocole cités (paliers de frais, répartition des frais) viennent de la documentation publique,
  telle que je la connais, et sont **À VÉRIFIER** sur le programme avant tout usage.
- Tout ce qui n'a pas été mesuré est marqué NM. Rien ici n'est un résultat économique.

## 1. Barre de coût d'un aller-retour (taille du Master : 0,1 SOL)

barre ≈ 2·f + 2·i + n_tx × frais_tx / 0,1 SOL, avec :
- f = taux de frais du pool ;
- i = impact unitaire (environ 0,1 SOL / profondeur effective) ;
- n_tx = 3 transactions (achat, vente, nettoyage, compte fermé).

| Frais de transaction | Part pour 3 tx | Source |
|---|---|---|
| figés, 105 000 lamports | 0,315 % | cpmmcost |
| médians mesurés, 8 000 lamports (sensibilité) | 0,024 % | mesure W1 / barmap |

Référence mesurée : CPMM 0,25 % à 100 SOL, barre de 1,12 % (figée) ou 0,73 % (à 8 000 lamports) (barmap).

## 2. Lieux candidats

| Lieu | f | i à 0,1 SOL | Barre (figée / 8 000) | Pools actifs | Données et décodeur | Hypothèses transposables SANS changer leur règle |
|---|---|---|---|---|---|---|
| **PumpSwap** (AMM x·y = k) | 0,25 % total au lancement (part LP / protocole / créateur : À VÉRIFIER, la grille a évolué) | 0,1 % à 100 SOL | ≈ 1,0–1,1 % / ≈ 0,7–0,8 %, comme CPMM | NM, probablement très nombreux (jetons sortis de pump.fun) | Événements Anchor (emit_cpi) ; **décodeur à écrire**, proche de cpmmx ; GTFA par pool comme A2r, au coût mesuré de 0,103 crédit par transaction | G2-3 (décisions sur les payeurs d'achats), R-CP1/B1 : oui, avec le calcul de coût x·y = k de cpmmcost en paramétrant f, À VÉRIFIER. N1 : NM (verrouillage des LP) |
| **Raydium AMM v4** (x·y = k) | 0,25 % (part LP À VÉRIFIER) | 0,1 % à 100 SOL | ≈ 1,0–1,1 % / ≈ 0,7–0,8 % | NM (beaucoup de pools anciens) | Pas d'événement Anchor : le journal « ray_log » est **à décoder** ; GTFA par pool | G2-3, R-CP1/B1 : oui (même mathématique). N1 : oui en principe (LP proportionnel), lpcost à adapter au décodeur |
| **Raydium CLMM** | paliers 0,01 % à 1 % (À VÉRIFIER) | dépend de la liquidité dans la plage : NM | ≈ 0,34 % + 2i (figée) / ≈ 0,05 % + 2i (8 000), au palier 0,01 % | NM | **Décodeur et modèle de coût à écrire** (ticks, liquidité concentrée) | Règle G2-3 : oui. Coût : NON sans un nouveau modèle (cpmmcost est x·y = k). N1 : NON (LP concentré, autre conception) |
| **Orca Whirlpool** | paliers 0,01 % à 2 % (À VÉRIFIER) | NM | comme CLMM | NM | **Décodeur et modèle à écrire** | comme CLMM |
| **Meteora DLMM / DAMM v2** | frais de base plus frais variables ou décroissants (À VÉRIFIER) | NM | NM : frais dépendants du temps et de la volatilité | NM | **Décodeur et modèle à écrire** | Règle G2-3 : oui. Coût : NON sans modèle des frais dynamiques |

**Ce qui est déjà codé et réutilisable partout** :
- les règles de décision (cpmmgen2, cpmmprereg), qui ne lisent que des swaps et des payeurs ;
- l'inférence (g23five 0.1.1 → 0.3) et le vocabulaire (g1ind) ;
- la chaîne de collecte GTFA (cpmmpilot).

**Ce qui ne l'est pas** :
- le calcul de coût cpmmcost / cpmmx et lpcost, propres à x·y = k ;
- le décodeur, propre à Raydium CPMM.

## 3. Classement (barre de coût basse × données disponibles)

1. **PumpSwap** : même mathématique que CPMM ; le flux de détail des jetons sortis de pump.fun est très probablement le
   plus dense (NM). Il faut un décodeur d'événements (environ 1 jour, à auditer) et cpmmcost paramétré par f. La barre
   n'est PAS plus basse que celle de CPMM ; l'intérêt est le volume et le nombre de pools.
2. **Raydium AMM v4** : même mathématique ; décodeur « ray_log » à écrire. La barre est égale à celle de CPMM ; le
   gain attendu est NM.
3. **Raydium CLMM / Orca Whirlpool, paliers ≤ 0,05 %** : la barre la plus BASSE, dominée par les frais de
   transaction (0,05 % à 8 000 lamports). Mais ce sont des paires efficientes (SOL / jetons majeurs), où un signal de
   détail est NM, et il faut un modèle de coût à liquidité concentrée (plusieurs jours, à auditer).
4. **Meteora** : des frais dynamiques à modéliser d'abord ; le reste est NM.

## 4. Avant toute décision (pour le propriétaire et R04)

- **Mesure descriptive** (pas d'hypothèse, pas d'essai) pour les rangs 1 et 2 : nombre de pools actifs ≥ 100 SOL,
  rotation, profondeur. Il faut un décodeur audité et une collecte bornée de 7 jours sur un petit échantillon tiré au
  hasard.
  - Crédits : 0,103 × transactions, NM tant que le volume est NM.
  - Une autorisation du propriétaire est requise.
- **Toute hypothèse nouvelle** (transposition de G2-3 ou de R-CP1 sur PumpSwap) demande un essai au-delà du plafond
  de 170 : décision explicite du propriétaire, fiche pré-enregistrée, mêmes règles statistiques.
- **Priorité** : rien de tout cela ne doit retarder la lecture des pilotes du 06/12 ni les confirmations ancrées
  (C-169, C-170).

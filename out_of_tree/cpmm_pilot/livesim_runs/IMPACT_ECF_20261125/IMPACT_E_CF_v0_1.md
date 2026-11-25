# Étude d'impact de E-CF (cpmmcost 0.3 → 0.3.1) — R01, 25/11/2026

- Tout est fait hors ligne, à 0 crédit.
- Seules sont lues des pages pré-T0 ou pré-départ, déjà ancrées. Aucune donnée de fenêtre, aucune position, aucun P&L.
- Méthode : les suites de tests gelées, rejouées avec cpmmcost 0.3.1 sur le chemin Python, et des recalculs mécaniques.

| Artefact | Dépend du taux créateur ? | Tests avec 0.3.1 | Résultat ancré modifié ? |
|---|---|---|---|
| cpmmprereg 0.2 (positions, témoin) | oui (frais d'achat et de vente) | 21/21 | aucun résultat ancré ne vient de ses positions (R-CP1/B1 clos INFAISABLE) ; les positions futures perdent 2 × 0,05 % de frais non prélevés |
| cpmmgen2 0.2 (règle G2-3, b₃) | non (payeurs et acheteurs seulement) | 19/19 | non |
| g23run 0.1 / 0.1.1 | non pour son code ; oui pour G-0 et pour les positions, via cpmmcost | 13/13 et 18/18 | aucun verdict calculé. G-0 sur les pilotes : refus « swaps_not_reproduced » levé, mais refus restants pour transactions non décodées et frais de transfert (voir E-G0) |
| g1ind 0.6.1 (K01) | non (ventes nulles = frais de transaction) | 15/15 | non (K01 −100 420 000 / … inchangés) |
| lpcost 0.2 (N1) | oui (frais des swaps d'entrée et de sortie) | 22/22 | aucun résultat ancré |
| n1verdict 0.2.2 et 0.3 | via lpcost | 13/13 et 16/16 | aucun résultat ancré |
| n1rot 0.2, sortie 6b9b02a9 | oui (seuil r04_6) | 7/9 ; 2 tests échouent | Recalcul mécanique (même script, mêmes pages, U2 3ca0260a). Avec 0.3, on retrouve 6b9b02a9 à l'identique. Avec 0.3.1, on obtient **8a768334** : les seuils baissent d'environ 9 % (AEZjoU 0,2191 → 0,1995 ; Gms3Ma 0,2185 → 0,1989 ; G8kgi7 0,2187 → 0,1991 ; GdxFyc 0,2320 → 0,2123). **Les pools retenus ne changent pas** : AEZjoU, G8kgi7 et GdxFyc, liste c72bd586, ÉVALUABLE. Les médianes de rotation ne changent pas |
| barmap (barres) | non (constantes propres : frais de transaction, protocole, fonds ; pas de taux créateur) | 6/6 | non |
| cpmmgen3 0.1, cpmmb1 | cpmmgen3 a SA PROPRE copie du calcul des frais (rule.py:147), non corrigée par 0.3.1 | 15/15 et 8/8 | non utilisés au pilote. À corriger seulement s'ils servent un jour |
| livesim 0.3, ELIGIBLE 199d25fb | oui (G-0) | 9 tests à adapter (pool synthétique B avec frais créateur, entrée FROZEN) | le mot reste NON ÉVALUABLE : 1 seul pool éligible même avec un taux de 0 (diagnostic DIAG_G0_CREATOR0 a9469873). La démonstration est close (R04-12) |

**Les deux tests de n1rot qui échouent** vérifiaient que le frais créateur de 500 ppm relève le seuil. En 0.3.1,
une config sans drapeau de pool donne un taux de 0. C'est le changement voulu, pas un défaut.

**Fiches** : N1 v0.7 inscrit la sortie 6b9b02a9 et ses seuils, et les fiches G2-3 v0.6, N1 v0.7, C-169 et C-170
citent cpmmcost 0.3. Un erratum doit faire pointer vers cpmmcost 0.3.1 et vers la sortie recalculée 8a768334, avec
les MÊMES pools retenus. C'est à R02 de le rédiger et de l'ancrer.

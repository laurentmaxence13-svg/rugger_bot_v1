# N — Hypothèses économiques préenregistrées pour W1 (v0.1, 2026-11-11 — PROJET à auditer et figer par R02)

Autorité : décision du propriétaire du 11/11/2026 (« GO W1 pour les hypothèses économiques
préenregistrées ») : W1 sert UNE fois de première fenêtre de confirmation indépendante, pour des
hypothèses finalisées avant le 14/11/2026 10:21 UTC sans consulter W1, auditées et figées par R02
avant toute évaluation ; le protocole et le verdict officiel W1 du MASTER actuel restent intacts et
passent en premier ; aucune nouvelle collecte non autorisée, aucune dépense, aucun trading réel.

Cette version fixe les règles et les seuils AVANT la lecture des tables « cohortes » de P0 (sorties
gardées fermées chez R03 à l'heure de l'envoi) : aucun seuil ci-dessous n'est tiré d'un résultat.

## 1. Ce qui est démontré, ce qui ne l'est pas

Démontré sur P0 (vérifié par R02) :
- le coût aller-retour instantané (frais de courbe aux deux côtés, frais de transaction) vaut 4 à
  5,4 % du capital, plus 2,05 % de loyer perdu par la chaîne actuelle ;
- après une entrée précoce (pool âgé de 0 à 30 s, courbe franchissant 5 % ou 10 %), la valeur de
  liquidation baisse en moyenne dans les 30 cellules état × horizon : dérive de −0,4 % à −19,2 % ;
- acheter une courbe qui monte est le pire ; aller plus vite aggrave ; attendre aggrave ;
- sur les entrées de la référence, une sortie parfaite ne dégage pas de gain net.

Hypothétique (à tester, c'est l'objet de cette fiche) :
- M-1 : la dérive négative vient de la revente par les premiers détenteurs (créateur, acheteurs des
  deux premiers slots) d'un stock acquis moins cher ; une fois ce stock vendu, elle disparaît ;
- M-2 : une grosse vente sur une courbe déjà profonde crée un écart temporaire que la demande
  restante comble (repli absorbé) ;
- M-3 : près de la fin de courbe, la course à la migration crée une pression acheteuse nette ;
- M-4 : un pool encore actif longtemps après sa création a dépassé la phase de revente initiale.

## 2. Cadre commun (identique pour toutes les hypothèses)

- Données : pack W1 de la collecte officielle (transactions des pools LaunchLab), lu après le verdict
  officiel W1 ancré par R02, par un adaptateur audité. Aucune donnée CPMM.
- Une position par pool et par hypothèse : la PREMIÈRE occurrence du déclencheur dans la vie du pool.
- Décision à un événement réel, transaction vue entière, à partir du passé seul ; achat de 0,1 SOL
  atterrissant après 4 slots ; vente à l'horloge à l'horizon fixé, atterrissant après la latence
  d'horloge gelée ; valorisation v4sim 0.2 mode M-P (code statelab, sortie à l'horloge vérifiée).
- Rendement : (valeur − mise − 2 frais de transaction − loyer perdu) / (capital + loyer). Courbe
  achevée avant l'atterrissage de la vente : −1. Achat refusé (franchirait la borne) : pas de position.
- Univers de tokens : SPL Token et Token-2022 de la liste stricte auditée (classe lue dans la
  transaction de création, loyer de la classe). Vue « exécutable aujourd'hui » (SPL seuls) publiée à
  côté. Classe refusée ou illisible : pool exclu et compté.
- Acteur : propriétaire du compte de token du trader (règle v4sim), sinon payeur des frais.
  Cohortes fixées à la décision : créateur ; « premiers » = autres acteurs ayant acheté dans le slot
  de création ou le suivant ; « autres » = le reste.
- Population : [À TRANCHER PAR R02] tous les pools rejouables, grappes = créateur déclaré (sensibilité :
  créateur signé seulement) — ou créateur signé seulement.

## 3. Famille de confirmation (4 hypothèses, correction de Holm sur 4)

| Id | Mécanisme | Déclencheur (premier événement entier qui satisfait TOUT) | Horizon de sortie |
|---|---|---|---|
| HW1-1 REPLI | M-2 | l'événement est une VENTE ; la courbe contient encore au moins 5 SOL réels après elle ; le prix spot est au moins 10 % sous le prix laissé par le dernier événement vieux d'au moins 10 s (prix de lancement s'il n'y en a pas) | 25 s |
| HW1-2 PURGE | M-1 | l'événement est un ACHAT par un acteur qui n'est ni le créateur ni un « premier » ; âge du pool ≥ 30 s ; au moins 2 SOL réels dans la courbe ; créateur + premiers ont acheté au total au moins 0,5 SOL (flux entré dans la courbe) ET ne détiennent plus que 5 % au plus des tokens en circulation | 60 s |
| HW1-3 FIN DE COURBE | M-3 | premier franchissement à la hausse de 65 % de progression (environ 27,7 SOL réels) — étiquette `progress:650000` de la grille statelab | 60 s |
| HW1-4 SURVIVANT | M-4 | premier événement entier d'âge ≥ 600 s, à 30 s près — étiquette `age:600` de la grille statelab | 120 s |

Raison économique et contrepartie :
- HW1-1 : celui qui vend gros sur une courbe profonde accepte un prix dégradé pour sortir vite ; si
  des acheteurs suivaient la progression, ils reviennent. Risque : la vente est le début de la sortie
  des premiers détenteurs (alors M-1 l'emporte et l'hypothèse échoue).
- HW1-2 : test direct de M-1 ; s'il reste une dérive négative alors que le stock des premiers est
  vendu, M-1 n'explique pas nos pertes. Le plancher de la courbe borne la baisse.
- HW1-3 : la probabilité de migration croît fortement avec le SOL levé ; le prix doit encore être
  multiplié par environ 1,9 jusqu'à l'achèvement. Risque : les positions migrées ne sont pas
  valorisables sans données CPMM.
- HW1-4 : version « horloge » de M-1/M-4, sans calcul de cohorte.

## 4. Critères, fixés d'avance

- Critère principal de chaque hypothèse : borne basse de l'intervalle à 95 % du rendement moyen > 0
  (rééchantillonnage par créateurs, 10 000 tirages, graine fixe), p unilatéral corrigé par Holm sur
  les 4 hypothèses, seuil 0,05.
- Référence : écart apparié par pool au placebo (âge aléatoire, règle gelée) au même horizon ; et à
  l'absence de trading (0).
- Critères économiques v1 de R02 (4e42b108) appliqués tels quels pour le mot « rentable » : R-1 (au
  moins 200 positions closes et 100 créateurs), R-2 (au plus 10 % de positions migrées), P-1 à P-6
  (dont stress : palier de frais le plus élevé, latence 10 slots, 25 % d'échecs, 500 bps de slippage,
  frais de priorité 1 000 000 lamports, mise 0,5 SOL ; drawdown ≤ 20 mises ; deux tiers
  chronologiques sur trois positifs ; aucun pool > 25 % du P&L positif). Les stress ne sont calculés
  que pour une hypothèse qui passe le critère principal.
- Verdicts possibles, par hypothèse : NON ÉVALUABLE (moins de 30 positions ou 20 créateurs ; ou plus
  de 10 % de positions migrées) ; REJETÉE (critère principal non atteint) ; EXPLORATOIRE POSITIVE
  (critère principal atteint mais R-1 ou un critère P non satisfait : nouvelle confirmation
  indépendante requise) ; CONFIRMÉE SUR W1 (tous les critères ; reconfirmation sur W2 exigée par R02
  avant tout usage). Aucun autre mot.
- Sensibilités publiées, sans effet sur un verdict : SPL seuls ; loyer récupéré (non exécutable
  aujourd'hui) ; latence 1 et 10 slots ; horizons voisins de la grille (10, 25, 60, 120, 300 s) ;
  créateur signé seulement.
- Comptage : +4 dans N au calcul ; rien n'est ajouté, retiré ni re-seuillé après lecture.

## 5. Hypothèses gelées mais NON ÉVALUABLES sur W1 sans collecte CPMM (aucune collecte n'est autorisée à ce jour)

| Id | Règle | Ce qui manque |
|---|---|---|
| HW1-M1 TRAVERSÉE | entrée HW1-3, position conservée à travers la migration, vendue sur le pool CPMM 300 s après son premier swap (valorisation : protocole CPMM v1.2, borne côté vendeur) | transactions CPMM des pools migrés |
| HW1-M2 APRÈS MIGRATION | achat de 0,1 SOL sur le pool CPMM 60 s après son premier swap, vente 300 s plus tard ; frais du pool lus sur la chaîne, loyer du compte compris | transactions CPMM des pools migrés |

Elles sont écrites maintenant pour pouvoir être évaluées proprement si le propriétaire autorise plus
tard la collecte (estimation R03 : environ 7 500 crédits gratuits, plafond à fixer). D'ici là leur
verdict est NON ÉVALUABLE.

## 6. Puissance attendue (ordres de grandeur, d'après les fréquences de P0 ; W1 : 4 800 à 10 000 pools)

| Hypothèse | Fréquence observée sur P0 (découverte) | Positions attendues sur W1 | Lecture |
|---|---|---|---|
| HW1-1 REPLI | 21 % des pools atteignent 5 SOL ; part avec repli de 10 % inconnue | quelques centaines | évaluable, R-1 possible |
| HW1-2 PURGE | inconnue (dépend des tables cohortes, non lues) | inconnue | à constater sur W1 |
| HW1-3 FIN DE COURBE | 1 pool sur 141 atteint 65 % | 20 à 70 | probablement sous R-1 : au mieux exploratoire |
| HW1-4 SURVIVANT | 3 pools sur 141 actifs à 600 s | 60 à 200 | limite |

## 7. Répétition à blanc sur P0 (données de développement)

Les mêmes règles, sans aucun changement, sont exécutées sur P0 visible (exploration + train, puis
validation lue une fois par hypothèse) : effectifs d'abord, valeurs ensuite, chaque hypothèse
comptant +1 dans N. Objet : vérifier le code de bout en bout et donner les premiers chiffres ; P0 ne
peut ni confirmer ni servir à re-seuiller.

# N — Hypothèses économiques préenregistrées pour W1 (v0.2, 2026-11-11 — à figer par R02 avec le code haché)

Autorité : décisions du propriétaire du 11/11/2026 (« GO W1 pour les hypothèses économiques
préenregistrées », 14:28Z ; « Précision avant gel W1 », 15:03Z). W1 sert UNE fois de première
fenêtre de confirmation indépendante. Liste finalisée avant le 14/11/2026 10:21 UTC sans consulter
W1, auditée et figée par R02 avant toute évaluation. Le protocole et le verdict officiel W1 du
MASTER actuel restent intacts et passent en premier. Aucune nouvelle collecte non autorisée, aucune
dépense, aucun trading réel.

Revue R02 intégrée : cadre 51352c0a (F-1 à F-6), population 9585e8d9, règles de fenêtre (message
14:33Z), D-C1 et critère PURGE 8a6e2721, cadre de l'hypothèse « non signé » d70251db, définition du
signal d277c6c6. Compteur d'essais à ce jour : N = 148.

## 1. Démontré / hypothétique

Démontré sur P0 (vérifié par R02) : coût aller-retour instantané de 4 à 5,4 % du capital plus 2,05 %
de loyer perdu ; rendement net négatif dans les 30 cellules état × horizon de la population « créateur
signé » (63817ac9) et dans les 50 cellules de la population « tous rejouables » (f583d747) ; aucun
tiers d'aucun des 34 signaux de sélection n'est positif à l'entrée de référence (f583d747) ; après
l'instant d'achat ce sont les acteurs déjà présents qui vendent (flux par cohortes, instrument conforme
3b16e5f7, identité de réserve vérifiée).

Hypothétique : M-1 la dérive disparaît une fois le stock des premiers acheteurs revendu ; M-2 une
grosse vente sur une courbe profonde crée un écart que la demande restante comble ; M-3 la course à
la migration crée une pression acheteuse en fin de courbe ; M-4 un pool encore actif longtemps après
sa création a dépassé la phase de revente ; M-5 les pools dont le créateur déclaré ne signe pas la
création (lancés par un programme tiers) reçoivent un afflux d'acheteurs dans les premières secondes.

## 2. Cadre commun

- Données : pack W1 de la collecte officielle (export_pools, même format que P0), lu après le verdict
  officiel W1 ancré par R02, par un adaptateur audité (identité sur P0). W1 ne contient AUCUN swap CPMM.
- Fenêtre W1 (R02) : décision ET atterrissage de l'achat dans la plage d'évaluation
  [467 678 545 ; 469 291 345) ; l'échauffement [467 275 745 ; 467 678 545) ne sert que d'historique
  causal ; la sortie doit atterrir avant la fin de la fenêtre, sinon le point est écarté et compté ;
  population = pools exportés, les « skipped » sont comptés hors champ.
- Population : tous les pools rejouables ; grappe = créateur déclaré, sinon payeur de la transaction
  de création (`cluster_key`). Sensibilité : créateur signé seulement.
- Une position par pool et par hypothèse : la PREMIÈRE occurrence du déclencheur.
- Décision à un événement réel, transaction vue entière, passé seul ; achat de 0,1 SOL atterrissant
  après 4 slots ; vente à l'horloge à l'horizon fixé, atterrissant après la latence d'horloge gelée ;
  valorisation v4sim 0.2 mode M-P.
- Rendement : (valeur − mise − 2 frais de transaction − loyer perdu) / (capital + loyer). Courbe
  achevée avant l'atterrissage de la vente : −1. Achat refusé : pas de position.
- Univers de tokens : SPL et Token-2022 de la liste stricte, loyer de la classe ; classes lues dans la
  transaction de création, recensement ancré avant l'évaluation ; classe refusée ou illisible : pool
  exclu et compté. Vue « SPL seuls » publiée ; un verdict positif ne vaut « exécutable » que si elle
  passe aussi le critère principal ou si la route Token-2022 est activée.
- Définitions (F-4), chacune testée dans le code : prix spot = réserve de cotation effective /
  réserve de base effective ; « vieux d'au moins 10 s » : block_time ≤ t − 10 ; « SOL réels » :
  real_quote ; « tokens en circulation » : real_base.
- Limite (F-2) : les transferts de tokens sont invisibles ; aucune règle ci-dessous ne dépend de la
  détention par portefeuille.

## 3. Hypothèses

### 3.1 Écrites AVANT toute lecture des tables de cohortes (v0.1, 697bbdc9)

| Id | Mécanisme | Déclencheur (premier événement entier qui satisfait tout) | Sortie |
|---|---|---|---|
| HW1-1 REPLI | M-2 | l'événement est une VENTE ; real_quote après elle ≥ 5 SOL ; prix spot ≤ 90 % du prix laissé par le dernier événement vieux d'au moins 10 s (prix de lancement s'il n'y en a pas) | 25 s |
| HW1-3 FIN DE COURBE | M-3 | premier franchissement à la hausse de 65 % de progression (`progress:650000`) | 60 s |
| HW1-4 SURVIVANT | M-4 | premier événement entier d'âge ≥ 600 s, à 30 s près (`age:600`) | 120 s |

### 3.2 Modifiée APRÈS lecture — provenance : anomalie des cohortes P0 exploration + train, lue le 11/11 (limite F-2)

| Id | Mécanisme | Déclencheur | Sortie |
|---|---|---|---|
| HW1-2 PURGE | M-1 | l'événement est un ACHAT ; âge du pool ≥ 30 s ; le maximum passé de real_quote a atteint au moins 2 SOL ; real_base juste avant cet achat ≤ 25 % de son maximum passé | 60 s |

Le critère de la v0.1 (part détenue par le créateur et les premiers acheteurs ≤ 5 %) est abandonné : la
détention par portefeuille est faussée par les transferts. Le critère d'état de courbe mesure la même
idée (la plupart des tokens achetés ont été revendus) sans dépendre des portefeuilles. Une HW1-2
REJETÉE ne réfute pas M-1 à elle seule.

### 3.3 EXPLORATOIRE ISSUE DE P0 — provenance : séparation signés / non signés du tableau 1d39ca85, lue le 11/11

| Id | Mécanisme | Déclencheur | Sortie |
|---|---|---|---|
| HW1-5 NON SIGNÉ | M-5 | étiquette `age:0` (premier événement entier, âge ≤ 30 s) d'un pool dont le créateur déclaré par l'instruction de création LaunchLab n'est PAS signataire de la transaction de création | 10 s |

- Définition validée par R02 sur les comptes seuls (d277c6c6) : 101 pools sur 242 en découverte, dont 99
  créés par appel interne d'un même programme lanceur (3KguFi7Y…, publié comme description, jamais
  comme condition). Créateur illisible : pool exclu et compté. La vérification Ed25519 n'entre pas
  dans la définition.
- Ce qui a été vu sur P0 (R02) : à 10 s, rendement net moyen +2,78 % sur 96 positions ; +0,18 % sans
  les 5 meilleurs pools ; moyenne tronquée à 5 % : +1,22 % ; à 25 s sans les 5 meilleurs : −0,49 % ;
  médiane négative ; intervalle contenant 0. La sortie à 10 s a été choisie APRÈS cette observation :
  c'est une provenance, pas une justification.
- 95 décisions sur 96 se prennent sur la transaction de création elle-même : détecter, décider et
  atterrir en 4 slots n'est pas démontré en réel.
- **Succès peu probable d'après P0.**

## 4. Critères, fixés d'avance

Famille de Holm : les hypothèses ÉVALUABLES parmi HW1-1 à HW1-5 ; m est fixé après les effectifs et la
part de migrées, avant toute valeur ; les non évaluables sont listées à part.

- Critère principal (toutes) : borne basse de l'intervalle à 95 % du rendement moyen > 0
  (rééchantillonnage par grappes, 10 000 tirages, graine fixe), p unilatéral corrigé par Holm, seuil 0,05.
- Références : écart apparié par pool au placebo (âge aléatoire, règle gelée) au même horizon ;
  absence de trading (0).
- NON ÉVALUABLE : moins de 30 positions ou de 20 grappes ; ou plus de 10 % de positions migrées.
- Pour le mot « rentable » : critères économiques v1 de R02 (4e42b108) tels quels — R-1 (≥ 200
  positions closes et ≥ 100 créateurs), R-2, P-1 à P-6 ; les stress ne sont calculés que si le
  critère principal passe.
- Verdicts : NON ÉVALUABLE / REJETÉE / EXPLORATOIRE POSITIVE (critère principal atteint, un autre
  critère manque : nouvelle confirmation indépendante requise) / CONFIRMÉE SUR W1 (reconfirmation sur
  W2 exigée avant tout usage).
- Conditions supplémentaires OBLIGATOIRES pour HW1-5 (R02 d70251db), sinon « EXPLORATOIRE NON
  CONFIRMÉE » : (i) rendement moyen à 25 s > 0 ; (ii) moyenne tronquée à 5 % > 0 ; (iii) moyenne > 0
  sans les 5 meilleurs pools et sans la plus grosse grappe ; (iv) deux tiers chronologiques sur trois
  positifs ; (v) aucun pool > 25 % du P&L positif ; (vi) moyenne > 0 avec une latence de 10 slots ;
  (vii) médiane publiée ; (viii) R-1 pour « rentable ». Sensibilité pré-déclarée : grappe = payeur de
  la transaction de création ; si son intervalle contredit le principal : NON CONCLUANT.
- Sensibilités publiées pour toutes, sans effet sur un verdict : SPL seuls ; loyer récupéré (non
  exécutable aujourd'hui) ; latence 1 et 10 slots ; horizons voisins ; créateur signé seulement.
- Comptage : N passe de 148 à 153 à la répétition P0, puis à 158 sur W1.

## 5. Ordre des opérations (F-1)

1. Code des déclencheurs et du calcul de confirmation, tests, audit R02.
2. Sur P0 visible : EFFECTIFS et part de migrées seulement, aucune valeur. Une hypothèse « fin de
   courbe » dont la part de migrées mesurée dépasse 10 % est inscrite d'avance « non évaluable sur W1
   sans CPMM », hors famille.
3. GEL : R02 ancre cette fiche et l'empreinte du code.
4. Répétition P0 en valeurs (+1 dans N par hypothèse), sans aucune modification ensuite.
5. Après le verdict officiel W1 ancré : adaptateur audité, recensement des classes ancré, une seule
   passe.

## 6. Gelées mais NON ÉVALUABLES sur W1 sans collecte CPMM (aucune collecte autorisée à ce jour)

| Id | Règle | Ce qui manque |
|---|---|---|
| HW1-M1 TRAVERSÉE | entrée HW1-3, position conservée à travers la migration, vendue sur le pool CPMM 300 s après son premier swap (protocole CPMM v1.2, borne côté vendeur) | transactions CPMM des pools migrés |
| HW1-M2 APRÈS MIGRATION | achat de 0,1 SOL sur le pool CPMM 60 s après son premier swap, vente 300 s plus tard ; frais du pool lus sur la chaîne, loyer compris | transactions CPMM des pools migrés |

## 7. Puissance attendue sur W1 (4 800 à 10 000 pools ; fréquences de P0 découverte, 242 pools)

| Hypothèse | Fréquence sur P0 | Positions attendues sur W1 | Lecture |
|---|---|---|---|
| HW1-1 REPLI | 25 % des pools franchissent 20 % de progression (≈ 5 SOL) ; part avec repli inconnue | quelques centaines | R-1 possible |
| HW1-2 PURGE | inconnue (effectifs mesurés à l'étape 2) | inconnue | à constater |
| HW1-3 FIN DE COURBE | sous le plancher sur P0 | quelques dizaines | au mieux exploratoire |
| HW1-4 SURVIVANT | 32 pools sur 242 actifs à 300 s ; 600 s sous le plancher | une à quelques centaines | limite |
| HW1-5 NON SIGNÉ | 96 positions sur 242 pools (40 %) | 1 900 à 4 000 | R-1 atteint ; succès peu probable |

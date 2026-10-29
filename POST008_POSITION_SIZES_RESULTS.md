# Après008 — tailles cohérentes, coûts et supervision interne

28 octobre2026. Code publié `249c7b6637d7c0cdf980b029474e4b0a576f237c`, arbre
testé `a5a4ccb99119ee38a6604f3f96cb0ba00c40f3ba`, local `6ce9906`.
Premier checkpoint `446d2623`. PR22 ouverte, sans fusion, ordre, signature ou dépense.
**Aucune collecte de marché**, aucun contrôle006/007/008 relancé, aucune base
utilisateur ou configuration secrète ouverte. Les preuves antérieures restent intactes.

## Résultat fonctionnel P3

`position_model.evaluate_position` effectue un achat entier puis la vente du même
lot sur les réserves contrefactuelles issues de cet achat. Frais arrondis au
plafond, sorties au plancher, uint64, fundraising, migration, stock et réserves
réellement dépensables contrôlés. Les frais historiques réservés ne sont pas
dépensés et les nouveaux frais sont exclus du solde conservateur. Ce modèle de
réserves n'est pas une certification du solde physique après transaction.

Quatre objets restent séparés : octets/état du bank observé, modèle avec notre
achat, devis du fournisseur, transactions exécutées. Le dernier reste vide.
Un refus sur le bank sans achat n'interdit plus mathématiquement la vente du lot
sur le bank après achat. Les erreurs ou limites conservent leur raison, sans
réduction automatique de taille ni liquidité inventée. Aucun ledger n'est crédité.

L'étude réutilise les huit banks candidat déjà conservés dans007/008 : quatre
mints, deux sessions, quatre tailles, **32 cas de modèle admissibles**. Six banks
ont une identité PDA qualifiée; les deux autres sont les observations du même
token dont la plateforme reste inconnue. Les états répétés ne sont pas des essais
indépendants. Deux estimations sur le bank observé sont calculables pour le lot
0,05SOL de007 à ses deux horizons; ce ne sont pas de nouveaux devis ni des ventes.
Les décisions sont évaluées à leur disponibilité **historique**;
ces données ne sont pas présentées comme fraîches aujourd'hui.

## Coûts et tailles : résultat mesuré du modèle

Friction de retour immédiat sans autre activité, avant coûts additionnels :

| Entrée SOL | Frais de courbe1,25% par swap : perte SOL | Frais5,75% : perte SOL |
| --- | ---: | ---: |
|0,05|0,001242189|0,005584689|
|0,10|0,002484376|0,011169376|
|0,25|0,006210939|0,027923439|
|1,00|0,024843751|0,111693751|

Ce sont des frais calculés depuis des taux observés, jamais des frais payés.
La friction relative reste proche de2,484%/11,169%. L'impact temporaire de notre
achat est en partie inversé par la revente immédiate dans cette hypothèse sans
activité intermédiaire; il ne faut pas en déduire un coût d'exécution futur nul.

Exemple exact pour le premier mint008, frais5,75% et décimales6 :

| Entrée SOL | Quantité projetée, unités atomiques | Revente immédiate du modèle SOL |
| --- | ---: | ---: |
|0,05|1645139871588|0,044415311|
|0,10|3285256942077|0,088830624|
|0,25|8175700326128|0,222076561|
|1,00|31973987104815|0,888306249|

Les32 lignes exactes sont dans `validation/position_size_study/positions.csv`.
Les coûts propres réseau/priorité/échecs restent UNKNOWN. Les totaux additionnels
0/15000/1000000lamports sont des **hypothèses**, y compris zéro. Ils décrivent des
coûts irréversibles supplémentaires; rent immobilisé/remboursable et financement
effectif restent inconnus. Aucun coût de swap déjà inclus n'est redéduit.

Avec l'hypothèse0,001SOL additionnel, une entrée0,05SOL perd0,002242189SOL à
faibles frais ou0,006584689SOL à frais élevés. À1SOL, pertes0,025843751 et
0,112693751SOL. Réduire la taille réduit le montant perdu mais accroît le poids
relatif des coûts fixes. Aucune taille n'est retenue ni réglage actif remplacé.

## Sensibilité des réserves et équilibre

Achats tiers hypothétiques0/0,1/0,5/1SOL après notre achat : recalcul entier des
réserves, quantités et frais de chaque flux, sans importer un bank futur observé.
Ventes tierces de50%/100% du stock initialement circulant : elles ne peuvent pas
emprunter notre propre lot. Sur les pools008 sans circulation, ces scénarios de
vente restent non applicables. Sur007, vendre tout ce stock après notre achat1SOL
ramène la revente propre à0,971692620SOL, contre0,975156249 sans cette vente tierce.

Seuils d'achat tiers nécessaires à l'équilibre sous **0,001SOL de coûts supposés** :

| Entrée SOL | Pool007, frais1,25% : flux tiers SOL | Premier pool008, frais5,75% : flux tiers SOL |
| --- | ---: | ---: |
|0,05|0,693622025|2,342356749|
|0,10|0,541624111|2,175086586|
|0,25|0,452355278|2,085545437|
|1,00|0,420585910|2,104146535|

Recherche bornée à10SOL hypothétiques et au domaine admissible avant migration.
Les96 seuils (8banks×4tailles×3coûts) ont été revérifiés : le seuil donne un net
conditionnel≥0 et un lamport de flux en moins donne un net<0. Ce sont des conditions
mathématiques, aucune prévision de demande ni preuve d'un flux futur.

## Cohorte et P4

Critères prospectifs publiés dans `P3_ACTIVE_COHORT_PROTOCOL.md` et le JSON associé :
univers100lignes conservé, six premiers candidats SOL uniques examinés, activité
réelle positive, capacité estimée de vente du lot entier0,10SOL, identité/supply/
permissions, deux candidats au maximum, suivi15s/slot supérieur, budget GLOBAL
20requêtes/60s incluant créations, frais de référence, refus et arrêts. Cette taille
est une hypothèse de recherche, pas une nouvelle allocation active.

Application rétrospective aux anciennes données008 :100lignes conservées,
48hors périmètre SOL,46hors préfixe, six examens; trois banks sans circulation,
trois snapshots non acquis. **Zéro sélection**, aucune nouvelle observation.
Les données manquantes ne sont pas remplacées. Le protocole reste préparé,
non exécuté; chaque futur départ doit geler code/heure et apporter une information
nouvelle. Le même fournisseur sans horloge source ne résout pas cette preuve.

Les trois variantes existantes consomment le même supplément causal de coûts :
32modèles,96associations variante/taille. Les24 intentions de variante restent
UNKNOWN faute de features créateur/wallet/momentum dans ces banques. Les tests
synthétiques valident le branchement et l'absence d'anticipation; aucun signal
réel fabriqué ni gagnant. Les24 anciens bras de fixture sont rejoués avec un
rapport **octet pour octet identique** à la preuve antérieure (SHA42b99d7e…).

## Supervision P5 et validation

Les wrappers existants de `main.run` observent les résultats RPC déjà sollicités,
l'abonnement, les notifications et les déconnexions WebSocket. Aucun ping/appel
supplémentaire. Âges civil/monotone, couverture du scanner et panne persistante
contrôlés; inspecter un état ne renouvelle pas son horodatage. Le rapport PAPER
expose ces vrais états internes avec le même ledger.

Endurance1000cycles,1000jambes,1000doublons ignorés,10sauvegardes/reprises,
750refus de phase et10préflights après reprise refusés sans sources fraîches,
4021invariants, reliquat0. Les callbacks internes utilisent des transports factices.
Temps **virtuel**83h20min plus1s; aucune disponibilité réelle24h/24 revendiquée.
Frais/produits/P&L de cette fixture sont synthétiques, pas des résultats de marché.

Régression finale : **1724 passed,1 skipped,242 subtests,7,56s**, warnings en erreur,
stderr0.77tests supplémentaires depuis1647. Tests sur copie sans réseau/.env/base
utilisateur. Le test ignoré requiert la base utilisateur absente. Reçu :
`validation/POST008_SIZE_FINAL_VALIDATION.json`.

## Preuves et conditions restantes

Rapport complet compressé+manifest sous `validation/position_size_study/`, résumé
`P3_POSITION_SIZE_SUMMARY.json`,96vérifications `P3_POSITION_BREAKEVEN_CHECKS.json`,
cohorte rétrospective, supplément P4, endurance et baseline conservée sous
`validation/`. Les sources restent ancrées dans les archives historiques privées.

**Cycles économiques strictement qualifiés :0. P&L net de marché :inconnu.**
P3 reste OUVERT : horaires/slots de devis non fournis, création et identité encore
incomplètes selon le cas, coûts propres et cash/rent non établis, aucun transfert
acquis ni sortie future contenant l'effet réel de notre entrée, corpus sans
indépendance/statistique suffisante. Les modèles améliorés ne comblent pas ces
preuves. P4/P5 restent PARTIELLEMENT VALIDÉS.

Prochaine acquisition utile : nouveaux cas à circulation/capacité attestées,
preuve de source/chronologie et coûts applicables ou bornes justifiées, avec
inventaire entier, mêmes frais et refus conservés. Aucun nouveau passage réseau
n'est nécessaire pour rejouer cette livraison :

```sh
python -B tools/compare_position_sizes.py --output work/position-sizes-new.json
python -B -m bot.offline_endurance --output work/endurance-new --cycles 1000
```

Conservation vérifiée: les quatre artefacts de l'étude ont été réellement
retéléchargés depuis `12e164fb783621d7fbc4284be7b9e1c7e51f54db` dans un répertoire
neuf. Archive/manifest/CSV/résumé rapprochés; les558754octets du rapport complet
sont identiques au recalcul hors réseau depuis les banks ancrés,32lignesCSV
vérifiées. Reçu: `validation/POSITION_SIZE_REMOTE_RESTORE.json`.

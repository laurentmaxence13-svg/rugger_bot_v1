# Cohorte active — critères préparés après008, aucune collecte exécutée

28 octobre 2026. `bot/p3/cohort.py` est un sélecteur **hors réseau** et
`benchmarks/p3_active_cohort_v1/criteria.json` fige ses critères. Ce document ne
constitue ni un contrôle exécuté, ni une commande de collecte. Un éventuel run
exige un plan horodaté lié au commit exact publié, une vérification des accès
gratuits/quota et de l'adaptateur, puis publication avant son premier appel.
Aucun appel006/007/008 ne doit être répété.

## Question nouvelle

008 observait des banks sans circulation : la vente fournisseur du lot projeté
ne pouvait pas intégrer notre achat hypothétique absent de ces banks. La prochaine
question instrumentale est la disponibilité d'une vente de quantité pertinente
**sur un marché déjà actif**, en gardant séparé le modèle après notre achat.
L'inactivité est ici une exclusion de cohorte, pas une preuve de rug ni une
preuve d'invendabilité après notre achat. Ce filtre n'est pas une modification
de la stratégie agressive ou des seuils de production.

## Univers et sélection figés avant résultat

1. Une lecture publique `sort=new`,100 lignes maximum, ordre reçu conservé.
   Chaque ligne, hors scope, doublon, absence, refus ou cas non atteint reste
   dans l'univers et reçoit une raison. Les champs d'un résultat vendeur futur
   ne participent pas à la sélection.
2. Les six premiers mints/pools uniques structurellement valides et cotés SOL
   forment le préfixe à examiner. Aucun remplacement après consultation d'une
   quote ou d'un résultat économique. Une ligne non SOL ne consomme pas le
   préfixe SOL. Les lignes après le préfixe restent explicitement non examinées.
3. Une lecture groupée des racines puis une lecture groupée des graphes, au plus
   42 comptes. Les sous-analyses doivent pointer sur les mêmes octets ordonnés
   et `context.slot` conservés ; `minContextSlot` impose une borne minimale,
   jamais un contexte identique à celui d'un autre fournisseur.
4. Activité : `real_a>0` **et** `real_b>0` dans le bank observé. La première
   mesure désigne les tokens déjà introduits dans la circulation de la courbe,
   pas la supply totale du mint. Liquidité virtuelle et fonds réservés aux frais
   ne deviennent pas des SOL effectivement disponibles.
5. Taille de recherche préfixée **0,10 SOL**, sans remplacement de la taille
   active du bot. Le modèle exact donne sa propre quantité Q, puis vérifie une
   estimation de vente de **Q entier** contre le bank observé, sans y insérer
   notre achat. `Q>real_a`, dépassement de réserve réellement dépensable, migration,
   autorité/permission/supply incohérente ou identité inconnue excluent la sélection
   et conservent leurs raisons. Le modèle distinct après notre achat reste affiché.
6. Les deux premiers cas satisfaisant activité, capacité et identité sont figés
   avant tout résultat fournisseur. Les six examens et les100 lignes originales
   restent les dénominateurs ; aucune substitution par les seuls cas gagnants.
   Deux tokens d'un créateur ne constituent pas deux essais indépendants.

Le sélecteur vérifie la disponibilité locale du snapshot avant décision et un
âge du reçu de5s au plus. **Cela ne certifie pas l'âge de la donnée source.**
Heure/slot fournisseur, blockTime et disponibilité locale restent trois preuves
distinctes. L'API de sélection ne peut pas authentifier elle-même l'acquisition
du bank : le journal ancré et ses octets restent indispensables.

## Budget global maximum, y compris erreurs et arrêts

| Lecture | Maximum |
| --- | ---: |
| Découverte100 lignes |1|
| Six pools racines groupés |1|
| Graphe initial groupé + blockTime |2|
| Deux achats0,10SOL + deux ventes initiales de Q |4|
| Graphe de suivi + blockTime |2|
| Deux ventes de Q au suivi |2|
| Deux pages de signatures et deux corps de création correspondants |4|
| Une page et un corps de transaction de référence des frais |2|
| Deux quarts Q//4 préfixés, uniquement après refus logique initial |2|
| **Total GLOBAL** |**20**|

Toutes les sources partagent60s monotones, compteur et deadline uniques, sans
probe/retry/fallback additionnel. Sous6 candidats, sous2 actifs ou données
manquantes : les appels inutiles ne sont pas remplacés par une nouvelle recherche.
Le suivi exige au moins15s depuis le premier bank et un slot strictement plus
récent ; les valeurs Q et Q//4 sont fixées avant leur demande.

Les pages création sont bornées à1000 signatures par pool ; un unique corps est
lu seulement si son identité peut correspondre à une création documentée dans
la page reçue. La création peut rester UNKNOWN : aucune pagination supplémentaire,
aucun ancien swap renommé création. La référence de frais n'est pas le coût de
notre transaction hypothétique. Les quarts ne liquident pas comptablement le lot.

Premier HTTP non2xx, transport/timeout ou corps invalide : reçu conservé puis
arrêt global, sans continuation par changement de fournisseur. Les refus logiques
HTTP200 sont conservés et permettent seulement la suite préfixée. Aucun quart
après429. Budget ou délai épuisé : positions/cas non atteints restent inconnus.

## Fraîcheur, provenance et coûts

Sources publiques envisagées : index LaunchLab Raydium, RPC Solana actuellement
intégré et API Raydium compute quote-only, listés dans le JSON de critères. Leurs
contrats et limites sont documentés dans `P3_SOURCE_ACCESS_METHOD.md`.

- `getMultipleAccounts` donne le contexte du bank et ses octets. `getBlockTime`
  est une estimation de production, pas l'horloge du calculateur de quotes.
- La réponse de quote doit conserver son corps et toutes les métadonnées source
  effectivement fournies. Si elle ne fournit toujours pas de temps/slot exploitable,
  cette collecte ne résoudra pas ce critère de qualification.
- Les frais de courbe sont calculés par le modèle entier sur le même état. Les
  frais de route inclus dans un output ne sont pas déduits une seconde fois.
- Le `meta.fee` d'une autre transaction prouve son propre coût, sans démontrer
  le nôtre. Priorité, création ATA, dépôt rent, échec et remboursement doivent
  avoir provenance et hypothèses séparées. Aucun wallet/état ATA n'est présumé.
- Aucun build/sign/send/simulate, clé privée, transaction réelle ou dépense.
  Sans coûts propres ou bornes économiquement justifiées, le P&L net reste inconnu.

Une collecte ne doit donc partir que si son adaptateur peut produire une
information nouvelle et ses champs manquants sont annoncés avant départ. La
publication des critères ne rend pas P3 automatiquement validé.

## Validation hors réseau

`tests/test_p3_cohort.py` :12 tests réussis, sans réseau. Ils vérifient la
conservation de toutes les lignes, refus, doublons, identité inconnue, limites du
préfixe, absence d'anticipation, capacité de Q entier et distinction entre un bank
sans circulation et son modèle après achat. Trois banks synthétiques représentant
la contrainte008 sont tous exclus sans requête ni cycle qualifié ; ce test ne
constitue aucune nouvelle observation de marché. Les critères ne sélectionnent
aucune taille gagnante depuis trois tokens et ne changent aucun paramètre actif.

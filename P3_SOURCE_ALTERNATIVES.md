# Alternatives de sources pour une campagne LaunchLab native SOL

27 octobre 2026 (Europe/Paris). Étude de documentation et de code officiels,
sans appel RPC, API de marché, portefeuille ou inscription par cette revue.
Les probes réels restent du ressort de l'intégration. **Aucun GO économique
ni classement de rentabilité n'est déduit de la disponibilité d'une API.**

## Résultat immédiatement exploitable

La référence OpenAPI officielle
[List mints with sorting](https://docs.raydium.io/api-reference/launch-mint-v1-endpoints/discovery/list-mints-with-sorting.md)
a répondu HTTP 200 et décrit exactement :

```text
GET https://launch-mint-v1.raydium.io/get/list?sort=new
security: []
sort requis : marketCap | new | lastTrade | hotToken
```

Le [Mint API overview](https://docs.raydium.io/api-reference/launch-mint-v1/overview)
précise que les lectures ne demandent pas d'authentification ; la création
requiert une signature de portefeuille puis un ray-token et est hors périmètre.
La documentation reçue ne donne ni schéma détaillé de réponse, ni pagination
certifiée pour cette route. Ne pas ajouter des paramètres supposés.

Cette liste fournit une piste de découverte plus ciblée qu'une page de
signatures du programme, qui contient aussi swaps et transactions échouées.
Elle n'est **pas** une preuve on-chain de création, une archive complète ou une
source de prix exécutable. Conserver l'ordre et la réponse reçue, puis vérifier
chaque identité mint/pool via transaction/comptes RPC. Ne pas sélectionner les
mints selon marketCap/hotToken après avoir observé leurs prix : ce serait un
filtre de survivance ou de performance, pas le corpus préenregistré.

## Comparaison des solutions

| Source | Accès/coût établi | Rôle utile | Limites et alternative |
|---|---|---|---|
| RPC/WS public Solana | Les accès anonymes antérieurs sont documentés dans P3_DATA_SOURCES.md ; aucun SLA ni gratuité durable à charge de production | Notifications du programme, transaction brute, statut/slot, rattrapage par signatures et snapshots de comptes | Partagé/rate-limité ; une page récente de signatures ne mesure pas la couverture. Associer WS, file durable et ancre/backfill, conserver échecs/gaps. |
| Raydium LaunchLab Mint API, sort=new | OpenAPI security:[] ; lecture anonyme explicitement documentée | Découverte de mints/pools, point de comparaison avec le flux RPC | Indexation/cache et univers non certifiés ; pas d'état atomique des réserves. Route exacte découverte ci-dessus à prober par l'intégration. |
| Raydium API v3 / History | Hôtes et fonctions documentés sur REST API surface ; aucune nouvelle souscription | Métadonnées de pools, configs, agrégats d'historique et identités d'appoint | Cache possible ; OHLC et trade history ne constituent pas une archive de ce qui était connu à chaque décision. |
| Raydium Trade API GET compute | Documentation officielle HTTP 200 ; accès anonyme aux lectures, probes antérieurs réussis | Quote à taille donnée, route et frais de hops, min-output et price impact | La quote est une estimation ; pas un fill ou une promesse de vente future. L'absence d'heure/slot fournisseur reste une inconnue. |
| Helius Free | Page de prix officielle : 0 USD/mois, 1M crédits, 10 RPC req/s et LaserStream WSS standard affichés | Piste de RPC/WS avec un accès de projet identifié si un binding existe ou est ultérieurement activé | La PR#19 n'avait pas de clé injectée ; aucun nouvel accès n'est créé ici. Plan gratuit documentaire ne prouve ni droit à chaque endpoint ni rétention historique. |
| Helius payant | Developer 49 USD/mois, Business 499, Professional 999 affichés au contrôle | Capacité/produits différents à évaluer si un besoin mesuré l'impose | Aucun plan activé ou dépense autorisée. Ne pas confondre débit annoncé, crédits, archive et preuve économique. |
| Jupiter | Piste documentée précédemment : sans clé à 0,5 RPS ; plan Free 0 USD/1 RPS, non activé | Seconde route de comparaison si le token/protocole est réellement pris en charge | Support des tout nouveaux tokens LaunchLab et coût de l'endpoint retenu à tester ; pas un index de l'univers des créations. |
| DexScreener | Prix indicatifs et paires accessibles dans les probes antérieurs | Observation secondaire après indexation, rapprochement mint/pool | Prix affiché et liquidité ne prouvent pas une sortie ; absence de source timestamp et délai d'indexation. priceNative n'est SOL que si la devise de quote est vérifiée. |

Une offre gratuite nécessitant un compte/clé n'est pas un accès déjà utilisable.
Réutiliser un binding existant après contrôle des noms/présence et de l'opération,
sans lire ou afficher une clé. Aucune extraction d'authentification du proxy n'est
nécessaire pour la découverte publique Raydium. L'authentification de Forum,
la création de mint et les routes de construction/soumission restent exclues.

## État de pool vérifiable et natif SOL

Les fichiers officiels du SDK Raydium V2 consultés sont
[layout.ts](https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/src/raydium/launchpad/layout.ts)
et [launchpad.ts](https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/src/raydium/launchpad/launchpad.ts).
Leur branche master est mutable ; les empreintes de la version lue sont ci-dessous.
Ce n'est pas une certification de toutes les versions du programme.

Le layout LaunchpadPool inclut notamment configId, platformId, mintA/mintB,
vaultA/vaultB, creator, mintProgramFlag, virtualA/B, realA/B, totalFundRaisingB,
frais et vesting. LaunchpadConfig porte curveType et tradeFeeRate.
PlatformConfig porte feeRate, creatorFeeRate et transferFeeExtensionAuth.
Les calculs buyExactIn/sellExactIn du SDK prennent les taux protocole, plateforme,
créateur, referral/share, les TransferFeeConfig A/B et le slot. Un spot ou un
coût forfaitaire ne reproduit donc pas à lui seul le produit d'une vente.

Parcours proposé pour une lecture cohérente :

1. Découvrir mint/pool par l'index, puis vérifier la création et l'identité par RPC.
2. Lire le pool pour découvrir ses références de config/plateforme/vaults/mints.
3. Relire le graphe de comptes retenu dans un **même getMultipleAccounts**
   avec context.slot et commitment fixé, après la découverte. Vérifier owners,
   identités, version/discriminator attendu et cohérence des vaults.
4. Conserver les octets et slots reçus, l'heure locale de réception et la
   disponibilité, puis appliquer le modèle de courbe supporté avec entiers et
   frais dans leurs devises. Une configuration inconnue ne devient pas zéro frais.
5. Vérifier explicitement mintB = wrapped SOL avant d'interpréter sa quantité
   atomique comme lamports. Une quote USD/USDC ne doit pas être renommée SOL.
   Le P&L natif SOL évite un FX inutile, sans retirer les contrôles de frais,
   solde, taille, inventaire, fraîcheur ou sortie.

Le SDK lui-même expose des lectures pools puis configs séparées. Ce schéma
n'établit pas une atomicité entre ces réponses : pour une campagne PIT, conserver
chaque context.slot et faire la relecture groupée finale. minContextSlot est une
borne de contexte, pas une demande d'état historique exact à ce slot.
getBlockTime est une estimation de l'heure de bloc et ne remplace jamais l'heure
à laquelle un état est devenu connu localement.

## Frais, vendabilité et inconnues bloquantes

Avant de qualifier une projection native SOL, lire et vérifier les deux mints,
leurs programmes, comptes de vault et politiques de transfert. Le SDK vérifie
Token-2022 et charge TransferFeeConfig des deux côtés lorsque pertinent.
Il ne faut pas porter un quoteur SPL classique vers Token-2022 en supposant
qu'aucun frais ou contrôle supplémentaire n'existe.

Pour le premier périmètre certifié, déclarer la liste des programmes/extensions
supportés. Autorité freeze, état gelé, non-transférabilité, hook de transfert,
permanent delegate, frais modifiables, autorité/ownership incohérents ou extension
inconnue doivent produire BLOCK/UNKNOWN suivant une politique préenregistrée,
pas une affirmation de fraude. Ces cas ne prouvent pas tous une invendabilité,
mais empêchent de garantir une projection de sortie sans analyse adaptée.

Distinguer les frais déjà inclus dans le montant de quote, ceux du token,
ceux de réseau/priorité, le coût éventuel des comptes et les tentatives échouées.
Les frais de devises différentes ne s'additionnent pas sans conversion vérifiée.
Un min-output positif, une réserve observée ou un volume passé ne garantit pas
la possibilité de vendre plus tard ; migration, épuisement/retrait de liquidité,
congestion, permissions et route absente restent des scénarios à enregistrer.

La collecte peut rester intégralement en lecture seule. Des transactions
publiques déjà exécutées peuvent fournir des observations de frais/balances pour
calibrer un modèle, sans signer ou soumettre une transaction utilisateur.
Une telle calibration ne prouve pas le fill d'un ordre PAPER contrefactuel.

## Recommandation de campagne limitée

Préenregistrer programme, commitment, fenêtre UTC, budget/débit, découverte
sort=new et politique de capture de chaque mint avant le premier appel.
La paire RPC/WS + index Raydium est une comparaison de deux surfaces observées,
pas une preuve automatique d'exhaustivité indépendante. Conserver tout écart
de découverte, les erreurs de chaîne, doublons, absences et gaps non rattrapés.

GO données d'un candidat exige identité vérifiée, snapshot de comptes cohérent,
courbe/programmes supportés, montants/frais connus dans la devise correcte et
information localement disponible avant la décision. UNKNOWN bloque la
qualification, sans faire disparaître le candidat du dénominateur.
Le rapport doit séparer capture du corpus, qualité par candidat, projection
exécutable estimée et résultat réellement exécuté. Les deux derniers ne sont
jamais interchangeables.

## Preuves documentaires de cette revue

Dix GET HTTPS publics, TLS normal, sans clé/compte : tous HTTP 200.
Aucun appel aux hôtes d'API de marché, RPC, WS, création ou transaction.
Les snapshots locaux sont sous
`/workspace/.cloud-env/rugger_bot_v1/source_research/`.

| Source officielle | Empreinte SHA256 du contenu consulté |
|---|---|
| REST API surface | 95966c44568e8e2edff229a0e20c14f6de76cf40eb41a39dd8730787c8d5d706 |
| Trade API | 89576fdb235e788e13a3a6115801ed3898c0fd666f6cf251cf68e91aeba410be |
| SDK api/url.ts | ee55cf04100fc6d3ded23e56f1f96b246679344d31408abca0b40b811545d99f |
| SDK launchpad/layout.ts | a422af7572b3b0f567ff7ad39f4b099eaf8a551257a77f89a61a3fe603ec2256 |
| SDK launchpad/launchpad.ts | 656d77856b0f3917013277cc06c0c46c5be65a76c42cabaf672455d259126d2a |
| Helius pricing | de270ff8ef208e9056a6d22cd0e436aa3c372ee05ec9c4bb503d08042a4b28ac |

Autres sources consultées : [SDK api.ts](https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/src/api/api.ts),
[Mint API overview](https://docs.raydium.io/api-reference/launch-mint-v1/overview),
[index officiel](https://docs.raydium.io/llms.txt), et OpenAPI list-mints cité plus haut.
[Helius pricing](https://www.helius.dev/pricing) affiche les montants et quotas
ci-dessus au contrôle ; tarifs et droits peuvent évoluer. La page générale
Raydium avertit de caches de 5–60 secondes et d'écarts possibles de slots.
Le conseil de quote stable environ 30 s de Trade API n'est pas une promesse de
marché disponible pendant 30 s.

Les droits de conservation/redistribution et la rétention historique ne sont
pas intégralement audités. Le code public du SDK et l'accès public à une route
ne confèrent pas automatiquement une licence de toute archive de données.
Aucune inscription, souscription, dépense ou activation financière effectuée.

# Sources de données P3 : accès, coûts et limites vérifiés

26 octobre 2026. Référence de départ : `9e4b5a788bf955e0afb9ab96818f17042c448b66`.
Ce relevé distingue documentation consultée, accès ponctuel observé et droits
non établis. Un HTTP 200 ne certifie ni un droit de redistribution, ni une
gratuité durable, ni la fraîcheur ou l'exécutabilité d'une cotation.

## Accès effectivement disponible

Les contrôles de présence effectués par l'intégration n'ont trouvé aucune clé
Helius, Birdeye, Jupiter ou Raydium injectée, ni RPC personnalisé. Aucun fichier
`.env` n'a été ouvert, aucune inscription ni souscription effectuée. Les appels
ci-dessous sont publics, sans clé, portefeuille ou soumission de transaction.

| Source | Observation ponctuelle de l'intégration | Ce qui manque encore |
|---|---|---|
| Solana RPC public, `api.mainnet-beta.solana.com`, POST `getSlot` | HTTP 200 ; slot 461841129 ; environ 416 ms | Test de `getSlot` seulement : ne prouve pas rétention historique, disponibilité de chaque transaction, continuité WS ou couverture des créations LaunchLab. |
| Raydium, `transaction-v1.raydium.io/compute/swap-base-in` | GET HTTP 200 ; réponse `success=true`, entrée exacte 1 000 000 000 lamports SOL, sortie cotée USDC ; environ 909 ms | Pas de timestamp de prix ou de slot de contexte dans la réponse observée, pas de profondeur complète ni de frais réseau garantis. La route n'est pas un fill et ne garantit pas une revente future. |
| DexScreener, `/token-pairs/v1/solana/<WSOL>` | GET HTTP 200 ; 30 paires WSOL avec prix USD ; environ 242 ms | Le timestamp de prix fournisseur n'est pas connu dans cette observation ; pas de preuve d'achat/vente à la taille voulue. |
| Jupiter | Documentation publique consultée ; aucun endpoint marché appelé par cette revue | Quotas et politique de coût propres à l'endpoint retenu, schéma de quote, droits d'archivage et fonctionnement effectif restent à contrôler avant ajout comme fournisseur. |
| Pyth Hermes | Découverte des feeds HTTP 200 sans clé ; lecture du dernier prix HTTP 401 | Identité SOL/USD trouvée, mais aucun prix obtenu avec les accès présents. Une clé précise, un plan gratuit ou payant ne se déduit pas du seul 401. |

Les durées mesurent ces requêtes isolées depuis le cloud, pas des P50/P95/P99,
un SLA ou une latence d'exécution. Les réponses et empreintes des trois probes
initiaux sont conservées par l'intégration dans
`/workspace/.cloud-env/rugger_bot_v1/p3_access/access-checks.json`.
Une sortie USDC ne doit pas être renommée USD : la parité USDC/USD n'a pas été
observée ou garantie par ces contrôles.

## Documentation officielle consultée

### Solana : RPC public et limites

[Clusters and Public RPC Endpoints](https://solana.com/docs/references/clusters),
HTTP 200. La page déclare les endpoints publics disponibles aux utilisateurs et
développeurs, mais précise : « The public RPC endpoints are not intended for
production applications. » Elle avertit aussi que les limites publiées peuvent
ne pas être à jour et que les services peuvent bloquer une IP.

La section Mainnet affiche 100 requêtes par 10 secondes/IP, 40 pour une même
méthode RPC par 10 secondes/IP, 40 connexions simultanées/IP et 100 MB par
30 secondes. Ce sont des **indications documentaires, pas un quota garanti**.
La page liste actuellement `https://api.mainnet.solana.com`, tandis que le probe
a porté sur l'alias `api.mainnet-beta.solana.com` : ne pas confondre le test
d'accès de l'un avec une certification contractuelle de l'autre.

Le document décrit 403 comme blocage et 429 comme dépassement de limite ;
`Retry-After` doit être respecté. Les lectures publiques testées n'ont demandé
ni compte ni SOL ; les frais d'une transaction réelle sont un autre sujet.
Une collecte prolongée fiable ne peut pas être présumée à partir de cet accès.

### Raydium : accès anonyme, cache et quote

La page d'accueil officielle [docs.raydium.io](https://docs.raydium.io/) et sa
page [REST API surface](https://docs.raydium.io/sdk-api/rest-api) ont répondu
HTTP 200. Cette dernière répertorie le host `transaction-v1.raydium.io` et
indique : « No auth — every service except Forum. Hit them anonymously over
HTTPS. » Les interfaces Forum/signature de portefeuille ne font pas partie du
périmètre de collecte.

Le document décrit une limitation progressive par IP derrière Cloudflare,
HTTP 429 et `Retry-After`. Il recommande aux intégrateurs dépassant durablement
120 requêtes/minute sur `transaction-v1` d'exploiter leur propre moteur de
quotes/routes ; ce conseil n'est pas une garantie de 120 requêtes autorisées.
Il indique des caches de 5–60 secondes pour de nombreuses lectures API v3,
une divergence possible de 1–2 slots et recommande de relire les comptes via
RPC pour un état de pool fiable. Le conseil de validité d'environ 30 secondes
pour une quote embarquée ne remplace ni son horodatage effectif ni la simulation
d'une exécution.

L'ancienne URL `/raydium/traders/trade-api` et le chemin supposé
`/raydium/for-developers/trade-api` ont retourné 404. La nouvelle navigation
officielle référence `/sdk-api/trade-api` ; cette page de détail n'a pas été
consultée par la présente revue. Le schéma de réponse précis est donc à vérifier
contre sa référence et les payloads observés, pas à déduire des anciens chemins.
La mention MIT sur le site concerne la documentation ; elle n'établit pas à
elle seule une licence des données ou une gratuité contractuelle de l'API.

Les montants de frais d'une route sont en unités atomiques de leur `feeMint`.
Il est incorrect d'additionner des frais SOL et des frais d'un autre token sans
conversion point-in-time vérifiée, ou de facturer deux fois un frais déjà inclus
dans la sortie de la quote. L'absence de frais réseau dans la réponse est une
inconnue, pas un zéro observé.

### DexScreener : observation de marché, pas exécution

[API Reference](https://docs.dexscreener.com/api/reference), HTTP 200 avec
contenu Markdown. La référence décrit notamment `priceNative`, `priceUsd`,
liquidité et routes de paires. Les limites de 60 requêtes/minute sont visibles
pour plusieurs routes de profils/publicité ; **le quota de `token-pairs` n'est
pas exposé dans le texte reçu**, qui renvoie vers une spécification distincte.
Un quota de 300/minute pour cette route n'est donc pas revendiqué ici.

L'accès sans authentification du probe est démontré, mais cette lecture ne
fournit pas de contrat tarifaire durable, d'archive point-in-time complète ou
de licence de redistribution. Le prix USD et la liquidité sont des observations
indicatives ; ils ne remplacent pas une quote des deux côtés pour le montant
PAPER choisi. La fraîcheur réelle fournisseur reste inconnue si seule l'heure
locale de réception est enregistrée.

### Jupiter : une piste gratuite documentée, non activée

L'ancien lien `https://dev.jup.ag/docs/api-setup` a redirigé vers
[Get Started with the Developer Platform](https://developers.jup.ag/docs/portal/setup),
HTTP 200. Le texte indique un accès immédiat sans inscription à `api.jup.ag`,
limité à **0,5 requête/seconde sans clé**. Le tableau affiche un plan **Free à
0 USD, 1 requête/seconde**, et renvoie vers les détails de crédits et coûts par
endpoint. La présence d'un plan gratuit ne permet pas de déclarer tous les
endpoints gratuits sans vérifier leur contrat propre.

Aucun compte ni clé n'a été créé et aucun endpoint Jupiter n'a été interrogé
pour ce relevé. Les offres payantes affichées ne sont pas activées. Cette piste
ne justifie ni une nouvelle dépendance ni un fournisseur supplémentaire dans
la présente PR sans besoin démontré.

### Pyth : distinguer découverte Hermes, accès au prix et offre Pro

Une lecture supplémentaire de l'intégration a obtenu HTTP 200 sur la découverte
publique [Hermes](https://hermes.pyth.network/v2/price_feeds?query=SOL%2FUSD&asset_type=crypto),
sans clé ou compte. La réponse identifie exactement `Crypto.SOL/USD`, devise de
cotation USD, pour le feed
`ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d`.
Cette découverte fournit une identité et une devise, **pas un prix**.

La lecture GET `/v2/updates/price/latest?ids[]=<feed>` a ensuite retourné
**HTTP 401 sans authentification**. Aucun prix, `publish_time` ou intervalle
de confiance n'a été obtenu. Les variables PYTH_API_KEY et HERMES_API_KEY sont
absentes selon le contrôle de présence de l'intégration ; aucune valeur n'a été
lue et aucune exigence secrète n'a été ajoutée pour cette piste. Le 401 constate
un accès inutilisable dans ce contexte : il ne prouve ni qu'une clé déterminée
suffirait, ni qu'un abonnement payant serait nécessaire. Aucun nouvel essai
authentifié, compte ou plan n'a été activé.

Le lien historique
[Fetch Price Updates](https://docs.pyth.network/price-feeds/core/fetch-price-updates)
a répondu HTTP 200, mais son contenu local porte le titre **REST API | Pyth
Developer Hub** et décrit **Pyth Pro**, base `pyth-lazer.dourolabs.app`.
Il précise que POST `/v1/latest_price` et `/v1/price` exigent une clé Pro Bearer.
Ce document ne mentionne ni Hermes, ni gratuité, ni quota public, ni licence de
données : il ne justifie donc pas un droit ou un plan gratuit Hermes. Aucun
endpoint Pro authentifié n'a été appelé et aucune offre n'a été souscrite.

Une future observation d'oracle SOL/USD horodatée pourrait lever l'absence de
temps source de l'indicateur DexScreener, après validation de l'identité, des
unités, de l'exposant, de la confiance, de l'âge et de la disponibilité locale.
Le temps de publication fournisseur ne doit jamais remplacer l'heure de
connaissance locale pour un replay as-of. Une référence d'oracle ne prouverait
pas un échange SOL/USD réalisable, le coût de la route, la fraîcheur d'une quote
Raydium ou un droit illimité d'archivage/redistribution. Les limites de débit et
conditions d'utilisation Hermes restent à vérifier ; cette piste non résolue
n'est pas un prérequis supplémentaire aux outils de préparation de la PR.

## Droits d'usage et coût : ce qui est établi

Les interfaces publiques documentées et les trois requêtes anonymes réussies
établissent un accès technique ponctuel sans nouvelle dépense observée. Elles
n'établissent pas un droit illimité d'extraction, de conservation ou de
redistribution commerciale. Les conditions de service détaillées, licences de
données, rétention historique et éventuelles restrictions d'usage automatisé
n'ont pas été intégralement auditées : **INCONNU / À VÉRIFIER avant collecte
soutenue ou redistribution**. Aucun contournement de quotas ou d'accès ne fait
partie du protocole.

Pour le prototype interne, conserver le minimum nécessaire : identités
publiques, réponses de cotation, unités, erreurs, provenance et temps de
connaissance. Ne pas aspirer des images ou métadonnées tierces sans besoin,
ne pas republier les archives brutes sur la base du seul caractère public de
l'endpoint et ne pas inscrire de secrets dans les traces. Les limites de
charge locales restent plus conservatrices que les plafonds documentaires.

## Conditions avant un GO P3 économique

1. Vérifier les conditions applicables aux endpoints effectivement retenus et
   fixer le budget de requêtes, la rétention et les droits d'usage ; rester sans
   abonnement ou dépense tant qu'ils ne sont pas autorisés.
2. Mesurer la disponibilité réelle des transactions LaunchLab et déclarer les
   trous, limites de pagination, refus, échecs et cotations absentes. Aucun
   pourcentage de couverture du marché n'est déduit d'un simple `getSlot`.
3. Associer chaque quote achat/vente à sa taille, ses unités, sa route, ses
   inconnues et son temps de connaissance. Source/slot absents restent absents ;
   achat et revente cotés à présent ne prouvent pas une sortie future.
4. Disposer de frais complets et d'une valorisation SOL cohérente. La conversion
   USD exige deux cours SOL/USD horodatés et connus aux instants concernés ;
   un cours indicatif sans date de source ou une parité USDC/USD supposée ne
   remplit pas ce contrat.
5. Constituer un corpus réel indépendant suffisamment informatif, sans
   sélectionner seulement les tokens survivants/cotés, puis appliquer le
   protocole quantitatif figé. Les tests techniques ne donnent pas ce GO.

**État : accès public ponctuel démontré ; qualité économique et droits de
collecte/redistribution à compléter ; rentabilité INSUFFICIENT DATA.** Aucun
ordre, construction/signature de transaction, portefeuille ou paiement n'a été
utilisé par cette revue documentaire.

## Recontrôle documentaire du 27 octobre 2026

Les pages officielles [REST API surface](https://docs.raydium.io/sdk-api/rest-api)
et [Trade API](https://docs.raydium.io/sdk-api/trade-api) ont été relues via
l’outil Web, sans appel de marché. Trade API documente le GET de devis, les refus
logiques HTTP 200/success=false et 120 devis/minute/IP avec Retry-After sur 429.
REST confirme l’accès anonyme hors Forum et les limites progressives par IP.
Ces indications ne garantissent pas la disponibilité ou un quota réservé.
La page Trade API décrit CPMM/CLMM/AMM v4 ; elle ne constitue pas une preuve
de support de tout pool LaunchLab avant migration. La cause des deux refus
historiques reste inconnue faute de corps conservés ; aucune augmentation de
slippage ni réduction de montant n’a été effectuée pour obtenir une réponse positive.

Ces pages consultées n’établissent pas des conditions complètes de conservation
des nouvelles réponses. La prochaine collecte attend un contrôle des conditions
applicables, de la gratuité/quota disponible et du transport courant. Aucun accès
API marché, abonnement, compte ou droit supplémentaire activé par ce recontrôle.

## Contrôle effectif du 27 octobre — complément à la revue documentaire

La [section officielle License / REST and Trade APIs](https://docs.raydium.io/resources/license)
précise l’usage raisonnable des services publics par les intégrateurs. La décision
opérationnelle limitée au replay interne minimal est détaillée dans
`P3_SHORT_CONTROL_ACCESS.md` ; aucune interdiction n’est inférée de la seule absence
de licence explicite des données. Aucun droit général de redistribution n’en découle.

Le contrôle unique v3 préenregistré a effectivement utilisé 19 tentatives en
26,034 secondes, sans clé ni portefeuille : transport anonyme observé fonctionnel,
deux créations et quatre snapshots conservés. Les deux refus de vente HTTP200
ont le message fournisseur INSUFFICIENT_LIQUIDITY. Leur archivage puis restauration
depuis GitHub et replay sont démontrés dans `validation/P3_RETENTION_REMOTE_RESTORE.json`.
Cela ne démontre ni quota durable, ni support de tous tokens, ni rentabilité.

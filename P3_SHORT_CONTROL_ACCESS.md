# Accès documentaire actuel — contrôle P3 court

27 octobre 2026, Europe/Paris. Sources officielles relues via outil Web ; aucun
endpoint de marché interrogé pour cette note et aucun secret lu.

## Conclusion opérationnelle

Les sources consultées établissent un usage développeur anonyme des lectures
Raydium/Solana et ne révèlent pas d'interdiction de conserver les réponses minimales
nécessaires au replay interne. Il est raisonnable de réaliser **un contrôle unique
préenregistré, interne, sans portefeuille, au plus 20 tentatives et 60 secondes**,
sous réserve du transport effectivement fonctionnel et d'arrêt immédiat sur refus
ou throttling. L'absence d'une licence explicite des données ne constitue pas à
elle seule un obstacle juridique démontré à ce contrôle.

Cette conclusion est une **inférence opérationnelle limitée**, et non une garantie
juridique ou un droit de redistribution publique/commerciale. Elle n'autorise ni
corpus prolongé ni copie d'images ou contenus tiers sans nécessité scientifique.

## Preuves pertinentes

1. [Raydium — License, REST and Trade APIs](https://docs.raydium.io/resources/license)
   distingue les services API des licences du code. Leur usage relève de conditions
   implicites des endpoints : limites raisonnables, pas d'abus, pas de garantie ;
   les services sont présentés comme un bien public pour les intégrateurs. Les
   usages commerciaux lourds doivent être coordonnés. Cette section décrit
   explicitement api-v3/transaction-v1. Elle ne fournit pas de licence générale de
   redistribution de toute donnée tierce. La licence CC-BY des pages documentaires
   ne doit pas être appliquée par analogie aux réponses API.

2. [REST API surface](https://docs.raydium.io/sdk-api/rest-api) documente les services
   publics, l'accès anonyme et les limites progressives par IP ; HTTP 429 signale
   une limite et Retry-After doit être respecté. Des lectures sont cachées et des
   écarts de slots sont possibles. Une réponse accessible ne certifie pas sa fraîcheur.
   Le contrôle doit rester strictement en GET de découverte/devis et méthodes RPC
   de lecture : jamais transaction/build, signature, auth-wallet ou envoi.

3. [Trade API](https://docs.raydium.io/sdk-api/trade-api) décrit les devis GET et
   **120 devis/minute/IP** (60 constructions/minute, hors périmètre autorisé).
   Les refus logiques peuvent être HTTP 200/success=false ; ils doivent être gardés
   comme refus avec leur corps assaini. Au plus quatre devis sur deux candidats est
   très inférieur au plafond documentaire, sans garantie d'un quota réservé.
   La page décrit le routage CPMM/CLMM/AMM v4 ; elle ne prouve pas que chaque pool
   LaunchLab avant migration dispose d'une route.

4. [LaunchLab Mint API overview](https://docs.raydium.io/api-reference/launch-mint-v1/overview)
   établit explicitement l'accès sans authentification aux **lectures** ; les
   écritures exigent ray-token après signature et sont exclues. Aucun quota chiffré
   propre à GET /get/list n'est annoncé dans cette page. Une unique découverte,
   sans répétition ni pagination élargie, reste cohérente avec l'usage documenté ;
   appliquer le premier 429/403 comme arrêt plutôt qu'inventer un quota.

5. [Solana — Clusters and Public RPC Endpoints](https://solana.com/docs/references/clusters)
   rend les endpoints publics accessibles aux utilisateurs et développeurs.
   Mainnet est permissionless ; le service est partagé et sans garantie. Limites
   indicatives : 100 requêtes/10 s/IP, 40 pour une même méthode/10 s/IP,
   40 connexions simultanées ; elles peuvent évoluer. Un plafond global de
   20 tentatives séquentielles reste sous ces indications. Aucune transaction
   n'est envoyée, donc aucune dépense SOL n'est engagée par ce contrôle de lecture.
   403 = blocage ; 429 = ralentir/Retry-After, ici arrêt sans retry.

6. [Solana — Interacting with Solana](https://solana.com/docs/payments/interacting-with-solana)
   autorise explicitement les endpoints publics limités pour développement/tests,
   en déconseillant la production. Les lectures de comptes/transactions retournent
   des faits du ledger public ; conserver leur réponse et leur provenance n'est
   pas la même opération que republier des images ou textes off-chain des créateurs.

## Conservation proportionnée et garde-fous

Conserver dans le dépôt privé demandé : clés publiques, bytes de comptes publics,
transactions sélectionnées, état des erreurs/refus, montants, ordre des comptes,
source/slot/horloges et corps assainis nécessaires au replay. Ne suivre aucune URI
métadonnée, ni télécharger images, profils, réseaux sociaux, clés ou wallets.
Marquer les réponses manquantes et vérifier export/hash/replay sans DB source.
Ni la licence d'un programme, ni le caractère public du ledger ne donne un droit
général de redistribuer les contenus descriptifs de tiers présents dans un index.

Le budget de contrôle doit compter les éventuels probes de transport comme des
requêtes effectives (ou les préenregistrer séparément), éviter toute boucle de
probes, ne créer aucun compte/API key et n'activer aucune offre payante. Un 200
ne prouve que l'accès à cet instant. Le quota restant partagé ne peut être garanti
par la documentation ; il faut enregistrer les réponses et arrêter sur limitation.

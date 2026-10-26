# Préparation des données réelles P3 — rapport de disponibilité

Référence main : `9e4b5a788bf955e0afb9ab96818f17042c448b66`.
Branche : `feat/p3-point-in-time-data`.
**Outillage de préparation testé ; évaluation économique P3 : NO-GO.**
**Rentabilité : INSUFFICIENT DATA.**

## Réalisations

- Journal SQLite neuf, append-only, versions/marqueur et refus du ledger historique.
  Source, réception, barrière d'ingestion, disponibilité as-of, provenance,
  doublons, rejets, absences et gaps sont distincts.
- Collecteur RPC borné et explicitement activé, destinations/méthodes en liste
  fermée. Aucune construction, signature, simulation de transaction ou soumission.
- Devis Raydium à taille exacte avec chemin, frais par devise, quantité attendue/
  minimum, slippage demandé, price impact, latence, 429 et échecs ; achat persisté
  avant la requête de vente. Liquidité/profondeur et coûts non fournis restent null.
- Calculs nouveaux en lamports/Decimal, conversion FX entrée/sortie causale,
  frais additionnels et tentatives échouées, refus des coûts/FX inconnus.
  Toutes les sorties sont des projections non exécutées.
- Aucun fichier du ledger, schéma historique, règle de stratégie ou test précédent
  modifié ; les performances passées gardent leur convention historique.

Voir [P3_CAPTURE_PROTOCOL.md](P3_CAPTURE_PROTOCOL.md) pour le protocole cible,
les unités, les bornes et les conditions de GO, et
[P3_DATA_SOURCES.md](P3_DATA_SOURCES.md) pour les sources documentaires et droits.

## Accès réellement contrôlés

Configuration consultée : réseau unrestricted, aucune exigence secrète enregistrée.
Variables HELIUS_API_KEY, BIRDEYE_API_KEY, JUPITER_API_KEY, RAYDIUM_API_KEY,
RPC_URL et SOLANA_RPC_URL absentes ; aucun .env ouvert.
Aucune inscription, offre payante, clé privée ou portefeuille n'a été utilisé.

Trois probes initiaux anonymes, tous HTTP 200 :
RPC public getSlot ; Raydium compute/swap-base-in pour 1 SOL→USDC ;
DexScreener SOL priceUsd (30 paires retournées).
Durées ponctuelles observées : environ 416 / 909 / 242 ms respectivement.
Ce ne sont ni P50/P95/P99 représentatifs, ni mesures jusqu'à une exécution.

La documentation officielle Raydium actuelle autorise l'accès anonyme aux services
hors Forum et avertit du cache et des écarts de slots. Solana publie des limites
non garanties et déconseille le RPC public pour la production. Jupiter documente
un accès sans clé à 0,5 RPS et un plan Free à 0 USD avec clé, non activé ici.
Les quotas, droits d'archivage/redistribution et coûts d'une campagne durable
restent à vérifier pour le périmètre retenu. Un HTTP 200 n'est pas une licence.

Un contrôle FX complémentaire a trouvé les métadonnées exactes Crypto.SOL/USD
sur Hermes (HTTP 200), mais la requête latest-price a répondu **HTTP 401** :
aucun prix horodaté n'a été obtenu. PYTH_API_KEY et HERMES_API_KEY sont absentes,
aucun nouvel accès n'a été créé ou activé. La documentation legacy consultée
redirige vers REST API Pro avec authentification ; elle ne prouve pas une offre
gratuite Hermes pour cet appel. Ce résultat ne permet pas d'affirmer qu'une clé
particulière suffirait ni qu'un abonnement serait nécessaire. Cette piste ne
résout donc pas le FX avec les accès actuels et n'est pas intégrée par défaut.

Aucun abonnement ni coût financier nouveau engagé. Des services publics gratuits
ne constituent pas une garantie de disponibilité gratuite à volume de production ;
stocker un corpus long, obtenir des données historiques/licenciées ou une capacité
RPC privée peut nécessiter un budget soumis à autorisation.

## Petit échantillon réel de préparation

Un appel borné du nouveau CLI, maximum 8 requêtes, a effectivement utilisé
**6 requêtes** et conservé **14 observations live** dans un journal local séparé :

| Élément | Observation |
|---|---|
| Page RPC | 5 signatures récentes du programme LaunchLab, jusqu'à 2 corps demandés |
| Transactions échouées en chaîne | 4, conservées sans inventer de création |
| Transaction réussie récupérée | 1, refus structurel no_verified_launch_instruction |
| Créations LaunchLab vérifiées | **0** dans cet échantillon |
| Devis achat/vente | 2 disponibles, cible USDC fixée pour le smoke test de transport |
| Taille demandée | 1 000 000 000 lamports ; quantité attendue achetée = quantité demandée à la vente |
| Position acquise / ordre envoyé | Aucune |
| FX SOL/USD | Observation indicative, sans heure fournisseur |
| Gaps | 1 bootstrap ouvert ; couverture du marché inconnue |

Ce jeu ne démontre donc ni une cotation exécutable de nouveau token LaunchLab,
ni un corpus représentatif. Le devis USDC n'a pas été choisi après un résultat
favorable ; c'est le diagnostic annoncé du transport. Le devis de vente actuel
n'est pas une vente future. Les deux cotations manquent d'heure source et de
context slot, de profondeur exécutable et de coûts réseau/priorité/ATA complets.

Le validateur readonly a relu le journal fermé sans modifier son hash.
La conversion FX stricte refuse l'observation sans heure source ; le calcul
net refuse les frais inconnus. Aucun P&L tiré de ces quotes n'est présenté.

Résumé et ancrages : `validation/P3_READINESS_RESULTS.json`.
Le journal, les réponses API et logs restent locaux sous
`/workspace/.cloud-env/rugger_bot_v1/p3_access/` : aucune base n'est poussée sur
GitHub et aucun corpus utilisateur n'est exporté. L'horodatage stocké est une
barrière précommit après verrou ; attendre le retour d'append avant une décision.
Il ne certifie pas l'instant exact de durabilité disque. La chaîne de hashes
est une détection relative à l'ancrage, pas une signature de la source.

## Disponibles / manquants / qualité

| Donnée | État actuel | Usage autorisé par la preuve |
|---|---|---|
| Signatures, slot et statut RPC | Disponibles sur petit échantillon public | Provenance de ce reçu ; pas couverture exhaustive |
| Payload de transaction | 1 corps réel obtenu ; fixtures multi-créations testées | Vérification structurelle ; aucune création live capturée dans ce run |
| Rejets, échecs, manquants, non-cotés | Format et composants testés, statuts distincts | Éviter leur disparition des futurs corpus |
| Source/réception/disponibilité | Contrat journal testé, blockTime estimé et réception locale | As-of local conservateur ; pas ordre exact intra-slot ni preuve de slot universel |
| Devis aller-retour 1 SOL | Estimations réelles de routes USDC | Tester capture de montants et erreurs ; pas prix de fill |
| Réserves/profondeur à taille exacte | Manquantes pour ces réponses | NO-GO exécutabilité ; funding et TVL ne les remplacent pas |
| Frais complets / comptes / priorité / échecs | Détails de hops présents, coût total inconnu | Ne pas calculer un net économique à zéro frais |
| SOL/USD point-in-time strict | Prix indicatif reçu, heure fournisseur absente | Affichage/diagnostic seulement ; conversion stricte refusée |
| État token / autorités / holders complets | Pas collecté dans ce composant | Aucun candidat autorisé par défaut |
| Univers indépendant, backfill complet, historique des disparitions | Manquants | Couverture et biais de survivance non estimables |
| Échantillon indépendant / stratégie rentable | Manquant | INSUFFICIENT DATA ; aucune activation |

## Vérifications exécutées

**875 passed, 1 skipped, 242 subtests passed**, warnings en erreur, code 0 et
stderr vide, Linux/Python 3.12.14. Le skip historique concerne la base utilisateur
absente, distincte du nouveau journal P3. Les **176 nouveaux tests** couvrent
capture/temps as-of, contention, refus du ledger, intégrité, formats/erreurs HTTP,
liens des deux quotes, SOL/USD, arrondis et frais. Aucun test n'accède au réseau.

Les revues croisées ont reproduit puis corrigé :
formes FX inattendues, statut/message transaction incomplet et barrière d'ingestion
prise avant attente du verrou. Les deux tests de contention échouaient avant
déplacement de l'horloge après BEGIN IMMEDIATE.

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B /workspace/.cloud-env/rugger_bot_v1/check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Hors cloud, exécuter le harness existant dans une copie jetable de sources/fixtures
sans .git/.env/données utilisateur, comme décrit dans P1_CLOUD_VALIDATION.md.
Importer les nouveaux modules ne lance ni réseau ni lecture dotenv.

## Décision et prochaine étape

**GO pour la préparation logicielle et les contrôles publics bornés décrits.**
**NO-GO pour l'évaluation économique P3 et pour toute qualification de trading réel.**

Avant un GO P3, il faut une campagne préenregistrée avec accès/droits et budget
acceptés, univers de référence et gaps maîtrisés, nouvelles créations effectivement
observées, prix/états de pool disponibles à la décision, frais complets, limites
de risque et devise/FX cohérents. Prévoir un échantillon final indépendant et une
précision statistique recherchée avant d'examiner les résultats. Les sorties
indisponibles et refus ne doivent pas être retirés du dénominateur.

La prochaine priorité est de choisir et vérifier une source gratuite ou un accès
déjà autorisé donnant l'état de pool horodaté et les coûts nécessaires, puis de
mesurer la couverture d'une collecte limitée préenregistrée. L'API publique qui
répond aujourd'hui ne résout pas à elle seule ces inconnues. Aucune dépense ni
activation financière n'est implicitement demandée par ce rapport.

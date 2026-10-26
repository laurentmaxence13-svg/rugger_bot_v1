# Protocole de préparation des données P3

Référence : main `9e4b5a788bf955e0afb9ab96818f17042c448b66`.
Mode PAPER ONLY, sans ordre, portefeuille, signature ou soumission.
Le code de préparation est séparé dans `bot/p3/` ; aucune table historique
`paper_*`, règle, stratégie ou performance passée n'est migrée.

## Univers et informations disponibles à chaque instant

L'univers cible est toute création LaunchLab vérifiée dans un périmètre de slots
et une période préenregistrés. Le corpus doit conserver les observations reçues,
pas seulement les tokens encore cotés ou les candidats retenus :
transactions échouées, payloads absents/invalides, créations multiples,
non-datés, refus de risque, non-évalués, devis manquants et exclusions de quota.

Le collecteur fourni est un **échantillonneur RPC borné**, pas une capture
exhaustive ni un remplacement du scanner P1. Il garde toute signature de sa page,
y compris les transactions qu'il ne récupère pas, et ouvre systématiquement un
gap de bootstrap sans référence indépendante. Son checkpoint marque la fin
de l'échantillon, jamais une couverture complète du marché.

Pour une future campagne P3, fixer avant collecte :
programme/commitment, bornes de slots, cadence et budget, référence indépendante,
algorithme de backfill et checkpoints, politique uniforme de devis pour tous les
créateurs/mints, limites de données et règles d'exclusion. Une déconnexion, une
page tronquée, un 429 ou un budget épuisé reste un gap ouvert jusqu'à preuve
explicite de rattrapage. L'absence d'événement ne prouve jamais l'absence de marché.

Chaque création a son mint, sa signature et son pool. Les décisions de la collecte
préparatoire restent not_evaluated/entry_permitted=false ; elles ne simulent pas
la matrice de risque avec des permissions/holders/exécutions encore inconnus.
Les rejets structurels et échecs de chaîne sont distingués des refus d'une
stratégie effectivement évaluée. Un candidat non coté reçoit not_attempted
lorsqu'il est hors de l'échantillon de devis, sans fabriquer un échec fournisseur.

## Journal et horloges

| Champ | Sens |
|---|---|
| source_time_ms | Heure de source connue uniquement ; blockTime de chaîne est une estimation en secondes convertie en ms, pas l'heure de réception. |
| source_slot | Slot effectivement fourni par la source ; les incohérences signature/transaction sont refusées. |
| received_at_ms | Fin de réception locale de l'information ; un ancien événement découvert maintenant reste découvert maintenant. |
| stored_at_ms | Barrière d'ingestion locale après acquisition du verrou SQLite, avant commit ; ce n'est pas l'instant exact de durabilité disque. |
| available_at_ms | Maximum conservateur de réception, barrière d'ingestion et disponibilité précédente ; aucun import/replay ne rétrodatera la connaissance. |
| requested_at_ms / latency_ms | Début de requête UTC et durée monotone ; les changements d'horloge ne deviennent pas des latences financières. |
| provenance | live, synthetic ou historical_replay ; ne pas mélanger ces catégories dans une validation économique. |

Une décision consommatrice doit attendre le retour réussi de append, donc le
commit, et enregistrer sa propre heure réelle de décision après cette barrière.
Le journal ne certifie pas l'instant exact de fsync au timestamp stored_at_ms.
Les sources absentes, futures ou invalides restent inconnues avec leur diagnostic,
sans fallback vers réception. La requête as-of utilise available_at_ms.

Le journal est un fichier neuf dédié avec marqueur/version, chaîne de hashes et
triggers anti-UPDATE/DELETE. Un ledger historique ou schéma étranger est refusé
avant écriture. Les doublons de réception restent des observations distinctes ;
leur payload peut avoir le même hash. La chaîne détecte les altérations
relativement à un ancrage retenu : elle ne signe ni n'authentifie la source et ne
résiste pas à la réécriture complète par un administrateur. Exporter le hash de
tête et le hash du fichier fermé dans le manifeste d'une campagne.

Le validateur readonly s'applique à un journal fermé en mode SQLite DELETE
par défaut ; il ne prétend pas suivre un writer WAL actif. Les bases utilisateur
ne sont ni copiées ni téléversées. Les corps de réponse contenant du matériel
d'authentification sont refusés sans afficher les valeurs ; garder catégorie
d'échec et digest, pas URL authentifiée ni clé.

## Devis à taille PAPER et inconnues explicites

Notionnel d'essai : **1 SOL = 1 000 000 000 lamports**, hors frais additionnels
encore inconnus. Slippage demandé : **100 bps**, paramètre de devis, pas réglage
de stratégie active ni constat d'un slippage réalisé.

Seul GET compute/swap-base-in est appelé : entrée exacte SOL→token puis devis
token→SOL pour la quantité attendue du premier devis. Persister l'achat avant
de demander la vente, afin qu'une panne de vente ne l'efface pas. Conserver :
montants attendus/minimaux, mint de chaque hop, frais par devise et unité brute,
price impact fourni, timestamps/latence, 429/Retry-After et erreurs catégorisées.

La quantité attendue n'est pas une quantité réellement acquise ni garantie par
le minimum de slippage. Le devis de vente observé maintenant ne prouve pas la
revente future. Sans état horodaté des pools et simulation/exécutabilité à taille
effective, ces réponses sont des **estimations de routes à taille donnée**.

Les réserves/profondeur, âge fournisseur, context slot et coûts réseau/priorité/
création de compte restent null lorsqu'absents. Ne pas déduire la profondeur du
funding LaunchLab, convertir silencieusement feeRate en bps ou compter deux fois
les frais de pool déjà inclus dans les montants. Une réponse HTTP 200 n'est pas
un fill et ne suffit pas au GO économique.

Les requêtes sont anonymes, sans transaction construite/signée. L'enveloppe réseau
borne les destinations, méthodes RPC, paramètres et nombre de tentatives ; aucune
redirection, clé ou nouvelle offre payante n'est activée. sendTransaction,
requestAirdrop, simulateTransaction et les endpoints de construction sont refusés.

## Comptabilité nouvelle, sans réécriture historique

La référence économique est SOL et les montants natifs sont des entiers lamports.
Le round-trip natif utilise entrée SOL, inventaire token exactement vendu, sortie
SOL et frais supplémentaires explicites non déjà inclus. Les tentatives échouées
sont des charges séparées ; le cash fourni précède toutes les charges comptées.
Frais inconnus, vente partielle ou sortie absente empêchent le calcul, au lieu
d'inventer zéro coût/perte. Réserver le budget et tous les frais connus avant entrée.

Si l'analyse part de prix token/USD :
`R_SOL=(P_tokenUSD_sortie/P_tokenUSD_entrée)*(FX_SOLUSD_entrée/FX_SOLUSD_sortie)-1`.
Exiger deux snapshots SOL/USD connus à chaque décision, heure source connue,
fraîcheur prédéfinie et disponibilité locale antérieure. USDC n'est pas assimilé
automatiquement à USD. Arrondir les produits de sortie au lamport inférieur et
conserver le détail ; aucun float financier ni correction rétroactive du ledger.

Le prix SOL/USD affiché par DexScreener peut être enregistré comme observation
indicative, mais son heure fournisseur est inconnue dans l'API contrôlée : il ne
satisfait pas cette validation FX stricte. Le calcul natif SOL ne nécessite pas de
conversion USD, sans résoudre pour autant les frais/exécutions manquants.
Toutes les sorties comptables nouvelles restent des projections non exécutées.

## Exécution bornée et validation

```sh
python -B -m bot.p3.collect collect --network --db /tmp/rugger-p3-capture.sqlite --output /tmp/rugger-p3-quality.json --max-requests 8 --signature-limit 5 --max-transactions 2 --quote-mint EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
python -B -m bot.p3.collect validate --db /tmp/rugger-p3-capture.sqlite --output /tmp/rugger-p3-validated.json
```

La cible USDC de cette commande est un **smoke test de transport** choisi avant
l'observation, pas un memecoin LaunchLab ou un signal. Une campagne sur créations
réelles doit appliquer sa politique de devis à l'univers complet préenregistré.
collect exige --network, au plus 20 requêtes configurables et un délai de 40 s.
Importer un module ou démarrer les tests n'effectue aucune collecte réseau.

## Conditions avant GO P3 d'évaluation économique

1. Accès et droits d'usage/rétention convenant à la campagne, quotas compatibles,
   coût total et limites de budget acceptés ; pas de dépense implicite.
2. Corpus point-in-time de l'univers déclaré, référence indépendante, gaps
   expliqués/rattrapés, rejets et absences conservés ; biais de survivance mesurés.
3. Devis/pools horodatés, inventaire et frais à taille effective, autorisations du
   token et sorties indisponibles traitées ; fraîcheur non déduite du seul reçu.
4. Devise/FX cohérents et règles de risque/solde applicables à toutes les décisions,
   ledger P3 neuf rapproché, sans réétiqueter les performances indicatives passées.
5. Protocole économique indépendant figé avant évaluation : train/validation/test,
   groupes/purge, coûts/délais/échecs, critères d'arrêt et précision statistique
   recherchée. Aucune taille de corpus arbitraire ne démontre la rentabilité.

Cette PR prépare les outils et les preuves d'accès. Un petit échantillon public
ne satisfait pas ces conditions : **P3 économique NO-GO / INSUFFICIENT DATA**.

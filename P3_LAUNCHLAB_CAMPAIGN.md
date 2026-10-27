# Collecte LaunchLab native SOL préenregistrée

27 octobre 2026 (Europe/Paris). Base : main
`966076c1a8b9a5d83bea74fe53fdad1056ade6dc`, fusion PR #19.
Le protocole et son plan JSON sont commités **avant** la collecte décrite ici.
Ce contrôle d'instrumentation ne constitue pas une expérience de rentabilité.

## Périmètre fixé

Plan : [plan.json](benchmarks/p3_launchlab_native_v1/plan.json).
Un seul passage, aucun remplacement opportuniste d'un candidat échoué.
Lectures anonymes gratuites, TLS normal, aucun compte ou portefeuille utilisé.
Ce plan v1 est figé au commit `1302609` ; ses résultats ne sont pas réétiquetés.

- Découverte : une requête officielle Raydium `get/list`, `sort=new`.
  Conserver dans l'ordre les 100 premières lignes, leurs identités/claims
  assainis et empreintes, les doublons et exclusions. Une réponse supérieure
  à cette limite ouvre un gap explicite. Les métadonnées/URL externes ne sont
  ni suivies ni utilisées comme preuve.
- Sélection : deux premiers mints uniques avec identités publiques valides et
  quote WSOL ; aucun filtre de prix, volume ou performance. Une ligne rejetée
  demeure au dénominateur. L'univers indépendant des créations reste inconnu.
- Taille de devis : 1 SOL, slippage demandé 100 bps. Ces bornes instrumentales
  ne changent aucune allocation ni stratégie du moteur PAPER existant.
- Budget : 20 tentatives HTTP transport au maximum, 60 secondes ; pas de retry,
  redirection, cookie ou netrc. Un 429/échec est conservé sans contournement.
  Le chemin complet nominal utilise au plus 19 requêtes.
- Création : une page de 20 signatures par pool ; télécharger la plus ancienne
  signature réussie de la page. Vérifier signature/slot, succès et instruction
  LaunchLab reconnue, puis concordance mint/pool. Conserver les autres lignes,
  échecs et transactions non téléchargées. La recherche bornée n'établit pas
  qu'une création est inexistante si elle reste introuvable.
- État initial : lire le pool pour découvrir ses références, puis relire
  pool/config/plateforme/deux mints/deux vaults dans **un** getMultipleAccounts.
  Commitment confirmed ; conserver context.slot, octets base64 et identités.
  minContextSlot est une borne inférieure, pas une sélection historique exacte.
- Enregistrer/commiter les octets avant toute analyse. L'horodatage du journal
  est une barrière d'ingestion précommit ; la décision attend le retour de commit.
  Conserver réception, disponibilité et analyse séparément.
- Lire getBlockTime du contexte comme **estimation** d'heure source. Son absence
  n'est jamais remplacée par l'heure de réception. Aucun certificat de précision
  de l'horloge RPC/index n'est déduit de cette lecture.
- Relire le graphe après au moins 15 secondes depuis la dernière réception
  initiale. Exiger des slots croissants pour admettre deux périodes ; sinon
  conserver le défaut temporel. La fenêtre globale reste bornée.
- Demander un devis Raydium compute d'achat à taille exacte. Si disponible et
  enregistré, demander la vente de sa quantité de sortie **estimée**. Aucune
  quantité n'est acquise ; une vente future reste inconnue. Si achat indisponible,
  conserver la vente non tentée avec son motif.

## Prix, frais et sortie

Le nouveau lecteur pur `bot/p3/launchlab.py` vérifie owners, longueurs, liens,
mint/vault SPL classique, états/autorités et backing WSOL réel après réserve
native. Pour la courbe constante supportée : entiers, frais curve arrondis vers
le haut, sorties vers le bas, taux protocole/plateforme/créateur et share explicite
de zéro pour une route sans affiliate. Les montants restent en lamports SOL et
unités atomiques du token : aucun FX USD n'est nécessaire à ce diagnostic.

La projection locale de revente utilise l'état **contrefactuel après son propre
achat hypothétique**, sans autre activité. Elle n'est ni un état de marché observé
plus tard, ni un devis garanti, ni un P&L net. Réserves virtuelles, fonds réels
et soldes réellement disponibles sont distingués. Migration/frontière de vente,
vault insuffisant, sortie nulle, freeze/mint authority ou Token-2022 non pris en
charge bloquent la projection ou la qualification selon le motif conservé.

Discriminators de comptes et PDA d'autorité ne sont pas certifiés par les layouts
SDK seuls : identité partielle, qualification bloquée. Un pin observé sur le même
compte ne peut pas servir de validation indépendante. Les hashes du code SDK lu
sont exposés dans chaque analyse. Frais réseau/priorité/ATA, tentatives échouées,
hooks/extensions et sortie future ne deviennent jamais zéro par défaut.
Les frais d'une transaction publique de création sont une observation de cette
création, pas les frais de notre ordre hypothétique.

Les devis API conservent source timestamp/slot manquants, liquidité inconnue,
latence et erreurs. Ils ne prouvent ni le fill d'un achat ni la vendabilité future.
Les contrôles financiers et le ledger historiques ne sont pas modifiés.

## Mesures et critères GO/NO-GO

Le rapport donnera : lignes reçues/retenues, sélectionnées, créations vérifiées
sur sélectionnées, périodes cohérentes reçues, quotes tentées/disponibles, statuts
HTTP/RPC, latences, rejets, transactions échouées/non téléchargées et gaps ouverts.
Le ratio sur l'index ne sera pas nommé couverture du marché. Celle-ci reste
`null` tant que manque une référence indépendante et un rattrapage sans gaps.

`bot/p3/readiness.py` distingue GO de collecte instrumentale et GO technique
d'admission à une future évaluation PAPER. Il exige pour cette dernière :

1. Plan identifié/enregistré avant lecture ; budgets respectés ; journal et ancre
   retenue vérifiés ; toutes les identités sélectionnées comptabilisées.
2. Référence indépendante complète et zéro gap non résolu dans la fenêtre admise.
3. Créations et comptes/PDA/discriminators vérifiés, programmes/permissions de
   transfert supportés, quote réellement native SOL et liquidité de sortie vérifiée.
4. Au moins deux périodes espacées de 15 s, slots croissants, ordre
   réception ≤ ingestion ≤ analyse et observation antérieure à la décision.
5. Âge source à réception **et à analyse** ≤5 s pour chaque période ; horloge
   source bornée. Ces 5 s sont un plafond d'instrumentation fixé, pas un optimum.
6. Frais complets et borne de coûts réseau connus, observation de sortie disponible.
   Toute donnée inconnue ou mal typée bloque l'admission.

Un GO technique n'est pas un seuil statistique ni une preuve d'espérance positive.
Le verdict économique demeure **INSUFFICIENT DATA**, y compris en présence d'un
GO de données. Une évaluation prospective indépendante devra encore figer sa
durée, ses dénominateurs, ses coûts pessimistes, son échantillon de validation et
sa règle d'arrêt avant d'estimer un résultat.

## Reproduction et conservation

Commande opt-in (nouveaux chemins dédiés, sortie/ancre/plan distincts) :

```sh
python -B -m bot.p3.campaign --network \
  --plan benchmarks/p3_launchlab_native_v1/plan.json \
  --db /tmp/p3-new-run/capture.sqlite --output /tmp/p3-new-run/report.json
```

Le plan n'est pas modifié après réception des résultats. Le collecteur refuse un
journal existant ou non vide. Les réponses RPC brutes et la base restent locales ;
seuls plan, résumé assaini et ancre/digests sont versionnés. L'ancre détecte aussi
une troncature relative au suffixe retenu ; elle n'est pas une signature externe.
Une réexécution future nécessite un nouveau plan/version enregistré avant lecture.

## Évolution explicite après contrôle de source

Le [rapport](P3_LAUNCHLAB_VALIDATION.md) distingue le primaire de ses diagnostics
préenregistrés ultérieurs : une création réelle retrouvée hors page initiale,
transactions version 1 observées, et un second pool indisponible par timeout.
Le [plan v2](benchmarks/p3_launchlab_native_v1/next_plan.json) est préparé mais
**non exécuté** : mêmes limites 2 candidats / 20 tentatives / 60 s / 15 s de suivi,
page de 1 000 signatures maximum et maxSupportedTransactionVersion=1 explicite.
Le chemin nominal reste au plus 19 requêtes ; aucune extension cachée ni retry.
Les paramètres v1 (20 signatures/version0) restent interprétés comme à l'origine.
Les futurs snapshots enregistrent l'ordre `requested_addresses` pour le replay.

Les comparaisons de sources/coûts/droits sont dans
[P3_SOURCE_ALTERNATIVES.md](P3_SOURCE_ALTERNATIVES.md). L'accès public ne garantit
ni un SLA ni un droit général de redistribution commerciale ; aucune archive brute
n'est redistribuée. Aucun abonnement ou service payant n'est activé.

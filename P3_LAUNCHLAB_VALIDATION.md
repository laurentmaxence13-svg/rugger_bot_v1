# Validation de la découverte LaunchLab et préparation prospective P3

27 octobre 2026, Europe/Paris. **L'API officielle fournit une piste exploitable :
une création a été vérifiée par transaction, mint, pool et créateur. Elle ne
fournit pas encore un corpus économiquement admissible. P3 reste NO-GO /
INSUFFICIENT DATA.** Aucune transaction utilisateur, signature, position acquise,
dépense ou souscription n'a eu lieu.

## Base et validation logicielle

Dernier main récupéré : `966076c1a8b9a5d83bea74fe53fdad1056ade6dc`,
fusion de la [PR #19](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/19).
Ses seuls fichiers suivis ont été extraits dans une copie jetable sans `.env`,
Git ou base utilisateur. Résultat reproduit : **880 passed, 1 skipped,
242 subtests passed**, warnings en erreur, stderr vide, code 0.

Les corrections de revue netrc/retry/receipts sont conservées. Aucun correctif
P1/P2 ni paramètre de stratégie n'est réécrit. Ledger et performances historiques
inchangés. Les seules modifications à l'ancien code P3 sont deux nouveaux types
d'événements de journal, sans migration DDL, et une correction documentaire
sur la session anonyme des quotes.

La suite de livraison contient les régressions du lecteur natif, de l'admission
temporelle et de la campagne. Commande sur copie isolée sans réseau :

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B \
  /workspace/.cloud-env/rugger_bot_v1/check.py \
  -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Résultat de livraison : **1 304 passed, 1 skipped, 242 subtests passed**,
warnings en erreur, code 0, stderr vide. Les 424 nouveaux cas couvrent lecteur
natif (52), admission temporelle (268) et campagne/transport/replay (104).
Les résultats détaillés figurent dans PROJECT_STATUS.md et result.json.
Le test ignoré historique concerne uniquement la base utilisateur absente.
Python 3.12.14, aiohttp 3.14.5. Aucune dépendance ajoutée.
Référence code de livraison : `612ed2cdb5331506200412dbbc34a22c65e67a95` ;
[PR #20](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/20) ouverte.
La mise à jour de ces références ne change aucun fichier Python testé.

## Collecte primaire, fixée avant observation

Code et plan figés/poussés : `13026092ea9621e537259b76b217f0bfcf2607d0`,
avant le premier départ réseau. Plan canonique SHA256 :
`89796f78c57f603954e052f142263c52c9dbdb7dae0af5c59897d414b3e09c02`.
Départ observé : 27 octobre, **07:09:05.724 CET** (06:09 UTC),
durée monotone 18 869 ms. Protocole :
[P3_LAUNCHLAB_CAMPAIGN.md](P3_LAUNCHLAB_CAMPAIGN.md).

| Mesure primaire | Résultat conservé |
|---|---|
| Tentatives transport | 19 / 20 ; 15 reçus RPC/index et 4 devis serveur |
| Journal | 185 événements ; ancre vérifiée après fermeture/réouverture |
| Index sort=new | HTTP 200 ; 100 lignes reçues/retenues |
| Sélection | 2 / 100, indices 0 et 2 ; 58 hors SOL, 40 hors échantillon borné |
| Rejets de collecte | 98 conservés ; ce ne sont pas des refus anti-rug |
| Pages de signatures | 40 lignes ; 25 échecs chaîne, 13 non téléchargées, 2 transactions manquantes |
| Créations vérifiées dans cette campagne | **0 / 2**, inchangé après diagnostics |
| Graphes de comptes | 4 réponses cohérentes : 2 périodes pour chacun des 2 pools |
| Devis API | 2 achats disponibles ; 1 vente disponible, 1 refus fournisseur |
| Projections locales | 0 : extensions Token-2022 non certifiées |
| Gaps | 3 ouverts : univers sans référence indépendante et 2 créations non retrouvées |
| Couverture de toutes créations du marché | **Inconnue**, jamais 100 % |

Les deux dates createAt précèdent la réception du sondage de 71,329 s et
515,329 s. Il s'agit de l'âge observé des tokens à ce sondage, pas d'une mesure
du seul délai d'indexation. Cette collecte de réponses est prospective ; elle
ne démontre ni détection à la naissance ni capture exhaustive des créations.

## Diagnostics séparés et preuve d'une création réelle

Les résultats primaires ont été figés. Deux diagnostics d'ingénierie ont ensuite
été préenregistrés/commités/poussés séparément, sans remplacer les candidats,
faire de sélection économique ou recalculer leurs performances.

1. [Plan version](benchmarks/p3_launchlab_native_v1/transaction_diagnostic_plan.json),
   commit `6e0ceeb`. Trois lectures. Le RPC explique précisément `-32015` :
   transaction version **1**, maxSupportedTransactionVersion **1** requis.
   Les deux signatures initialement manquantes deviennent disponibles avec ce
   paramètre. Elles sont des appels d'agrégateur sans instruction de création
   reconnue dans la réponse ; elles ne sont pas promues en créations.
2. [Plan recherche de création](benchmarks/p3_launchlab_native_v1/creation_lookup_plan.json),
   commit `379ed36`. Trois tentatives sur quatre autorisées. Une page de 1 000
   signatures maximum pour les **mêmes** pools, plus la plus ancienne réussite
   de chaque page disponible. Premier pool : 753 signatures, dont 649 échouées.
   La transaction la plus ancienne disponible est une vraie création LaunchLab.
   Second pool : transport/timeout après 8 034 ms ; HTTP et code RPC inconnus.
   Aucun retry, aucun 429 affirmé, aucun candidat de remplacement.

Preuve publique vérifiée indépendamment depuis les octets RPC conservés :

- Mint : `uhnBg2De8nv5yT9BCdJTrGbZ3b72Q9tVfx8CZkGSs1T`.
- Pool : `G3jmqVEjXGWBgKqGfnLTHJjNMz4kgjmQVXF9JupAyyVM`.
- Création : [mCVKa7…qbPGz](https://solscan.io/tx/mCVKa7XRGCpDfAL3zF19LXpHehbTtyC2th6oh1Hi1wmXAxhJdfLofXaUnUo5cR1ACp8nmMkTKgvZb2WBD1qbPGz).
- Slot **461963207**, version 0, meta.err null, signature de réponse concordante,
  instruction de création du programme LaunchLab reconnue par le parser strict.
- Créateur : `6KyfUHkfytBjh8ejhTvfrtRYiyWJKRv2QWQnkdtHpdFQ`, concordant avec
  l'index et le pool. createAt = blockTime × 1 000 = **1793081275000**.
- Frais de cette création publique : **170 000 lamports**. Ce n'est pas le
  coût de notre achat/vente hypothétique et n'est pas utilisé comme tel.

Total des lectures de marché de ces trois contrôles : **25 tentatives**
(19 + 3 + 3), distinguées des lectures documentaires et de l'exploration antérieure.
Les diagnostics étendent une vérification de source, pas l'échantillon primaire
ni un test de stratégie. Une preuve sur un candidat n'établit pas la couverture.

## États, frais et possibilités de sortie

Les quatre snapshots relisent ensemble pool/config/plateforme/mints/vaults avec
context.slot confirmé et minContextSlot. Les slots augmentent ; observations
espacées de plus de 15 s ; persistance réussie avant analyse. getBlockTime fournit
une estimation source, jamais un timestamp de publication certifié. Âges estimés
à réception : 921–1 432 ms ; cela ne certifie pas la précision de l'horloge source.

Pour les deux pools, les layouts SDK épinglés indiquent courbe 0, taux protocole
2 500 ppm, plateforme 10 000 ppm, créateur 0 : **1,25 % de frais de courbe**,
hors autres coûts/extensions. Les deux mints/vaults base relèvent de Token-2022.
Les extensions ne sont pas certifiées par ce lecteur : aucun devis local n'est
admis malgré la disponibilité des octets. Cela ne prouve pas une invendabilité.

La réserve réelle quote du premier pool passe de **8,732075506 SOL** à
**3,011541136 SOL** entre périodes. Celle du second vaut **1 lamport** ; son
vault quote contient 20 868 751 lamports, dont 20 868 750 de frais protocole
décodés. Ses quelque 30 SOL virtuels ne sont donc pas une profondeur de sortie.
Discriminators de comptes et PDA d'autorité restent à certifier indépendamment.

La Trade API a fourni, pour le premier mint, un achat théorique à 1 SOL puis une
vente théorique des **20 662 674 493 249** unités atomiques estimées, cotée
**927 845 229 lamports**. Le second achat est coté mais sa vente est refusée.
Les routes retournées correspondent aux pools découverts. Aucun token n'est
acquis ; l'état après notre achat n'a jamais existé. **Ces nombres ne sont pas
un rendement de round-trip, un fill ou une preuve de sortie future.**

Latences des quatre devis : environ 205–687 ms. Timestamp/slot fournisseur,
profondeur exécutable, frais réseau/priorité/ATA et coûts d'échec restent inconnus.
Les frais de route déjà indiqués ne doivent pas être déduits une deuxième fois.
Une vente refusée ne prouve pas à elle seule un token invendable.

## Corrections pour la prochaine collecte

Le [plan suivant](benchmarks/p3_launchlab_native_v1/next_plan.json) est **non exécuté**.
Protocole v2 explicite : page bornée à 1 000 signatures et max version 1,
sans retry automatique ni élargissement caché de budget ; toujours 20 tentatives /
60 s / 2 candidats, au plus 19 appels nominaux. Le plan v1 et son interprétation
restent inchangés. Une page pleine n'est pas une archive complète.

Les prochains snapshots conservent aussi `requested_addresses` dans l'ordre exact
de la requête : le JSON canonique trie les clés du dictionnaire de rôles. Pour
rejouer le primaire, utiliser l'ordre `ACCOUNT_ROLES` du code `1302609`, et non
l'ordre des clés rechargées. Les quatre graphes ont été reconstruits et vérifiés
ainsi. Une régression ferme/réouvre le journal et reproduit l'analyse depuis
l'ordre explicite conservé. Aucun enregistrement primaire n'est réécrit.

## Blocages et conditions d'admission

**GO de collecte instrumentale ; NO-GO d'admission économique PAPER.** Le gate
exige les critères mesurables du protocole : zéro gap dans la fenêtre admise,
référence indépendante complète, créations/identités/PDA certifiés, permissions
et extensions connues, deux périodes ordonnées, frais totaux et sortie disponibles,
âge source à réception et décision ≤5 s avec horloge bornée. UNKNOWN bloque.

Les prochaines étapes sont précisément : lecteur Token-2022 audité et tests de
transfert/freeze/fees/hooks ; pins de comptes et PDA depuis une source indépendante ;
WS + backfill borné avec couverture mesurée ; quotes avec contexte source et coûts
d'exécution bornés ; observations de sortie ultérieures pour la quantité définie
avant résultat. Une référence index/RPC partiellement commune ne prouve pas à elle
seule l'exhaustivité. Aucun GO de données ne démontre une rentabilité.

Les accès anonymes Raydium/public RPC sont déjà utilisables, sans SLA. Helius Free
à 0 USD/mois nécessiterait un accès de projet absent ; aucune clé ni inscription
activée. Les alternatives payantes documentées (49/499/999 USD mensuels Helius)
ne sont ni nécessaires démontrées ni autorisées ici. Tarifs/droits peuvent changer.
Voir [P3_SOURCE_ALTERNATIVES.md](P3_SOURCE_ALTERNATIVES.md) pour les sources,
quotas et limites de conservation/redistribution. **Dépense engagée : zéro.**

## Artefacts et limites de preuve

[result.json](benchmarks/p3_launchlab_native_v1/result.json) contient les résumés,
identités publiques sélectionnées, empreintes, paramètres, timings, quotes,
analyses, verdicts et les trois ancrages. Les bases et réponses brutes restent
locales sous `/workspace/.cloud-env/rugger_bot_v1/p3_campaign/` ; aucune DB distante.
Le journal haché vérifie son intégrité relative aux ancrages Git retenus, pas une
authenticité cryptographique du fournisseur ni une précision d'horloge absolue.

Les trois ancrages ont été vérifiés par une revue indépendante, en lecture seule,
ainsi que la création, les frais décodés et les quatre graphes. Les plans et RPC
publics permettent une vérification actuelle des identités ; ils ne permettent
pas de recréer à l'avenir les mêmes banques de comptes historiques. Le replay
exact des observations nécessite les octets locaux retenus. Rollback logiciel :
retour au main `966076c`, sans modification/recalcul d'un ledger historique.

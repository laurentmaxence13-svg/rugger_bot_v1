# Validation P3 après fusion de la PR #20

27 octobre 2026, Europe/Paris. **Collecte v2 exécutée, deux créations vérifiées,
preuves disponibles restaurées depuis GitHub. P3 économique reste NO-GO /
INSUFFICIENT DATA.** Aucun ordre, portefeuille financé, paiement, abonnement ou
changement de seuil de stratégie.

## Revue et code exécuté

La PR #20 initiale `b30356b` a reproduit **1 304 passed, 1 skipped,
242 subtests passed**, warnings en erreur, code 0, stderr vide. Des revues
séparées ont examiné réseau, finances/provenance et conservation.

Trois défauts effectivement reproduits ont été corrigés avant fusion : deadline
transport monotone, reçus d'annulation RPC/index/quote, enveloppe RPC strictement
2.0/id entier. Après cinq régressions causales : **1 309 passed, 1 skipped,
242 subtests passed**. Voir [P3_PR20_REVIEW.md](P3_PR20_REVIEW.md).

La [PR #20](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/20) est
fusionnée sans contournement de protection au commit
`8167264931af3a22dcce32e9d1a821d275b51307`. La collecte v2 utilise ce main,
avant les nouveaux lecteurs de cette PR.

Plan inchangé : [next_plan.json](benchmarks/p3_launchlab_native_v1/next_plan.json),
SHA256 `49498f4b0f9326840b085f84cb14039648de860836e51a0dde8fd4f314425090`.
Son champ source_main reste sa base historique `966076c` ; le code réellement
utilisé est attesté séparément, sans réécrire le plan.

## Résultats v2, conservés séparément

Départ **08:17:49.768 CET**, durée monotone **25 909 ms**. Pas de retry,
remplacement de candidat ou requête supplémentaire de marché.

| Mesure | Résultat |
|---|---|
| Budget | **19/20 tentatives, 25,9/60 s** |
| Découverte officielle sort=new | 100 lignes retenues, 2 candidats, 98 exclusions de collecte |
| Créations vérifiées | **2/2**, signature/slot/succès/instruction/mint/pool/créateur concordants |
| États cohérents | **4**, deux périodes par pool, slots croissants |
| Devis API | 2 achats disponibles à 1 SOL ; **0/2 ventes** disponibles, refus fournisseur HTTP 200 |
| Pages de transactions | 33 lignes, 31 non téléchargées ; aucun échec chaîne dans ces pages |
| Journal | 182 événements, ancre vérifiée |
| Gaps | **1** : référence indépendante de l'univers absente |
| Couverture de toutes créations | **Inconnue** ; 2/100 est une fraction de sondage |

Périodes espacées de 24,083 s et 15,340 s, persistance avant analyse.
getBlockTime donne une estimation source : âge à réception 489–1 245 ms.
Cela ne certifie pas l'horloge fournisseur ni le timestamp/slot des devis API.
Les deux frais de création publics de 40 000 lamports ne sont pas les frais de
nos trades hypothétiques. Les résultats précédents restent inchangés, notamment
le primaire v1 à 0/2 créations et son diagnostic séparé à une création.

## Corrections ciblées après collecte

Les réanalyses sont postérieures, jamais des informations prétendument connues
à une ancienne décision. Profil `legacy` conservé par défaut ; nouveau profil
explicite `published_metadata_v1`, sans activation automatique dans le collecteur
v2 figé. Les quatre analyses v2 historiques se reproduisent exactement depuis
les archives distantes avec leur interprétation initiale.

**Token-2022 :** seuls mints sans extension ou avec MetadataPointer 18 /
TokenMetadata 19 et vaults de base 165 octets sont supportés. Padding/type/TLV/
Borsh/liens/autorités vérifiés ; aucun texte/URI retourné ou suivi. Frais de
transfert, hooks, extensions inconnues, freeze et permissions dangereuses restent
bloquants. WSOL canonique doit toujours relever de Tokenkeg.

**Identités :** discriminators et seeds tirés de l'IDL officiel indépendant du
layout SDK : raydium-io/raydium-idl, commit
`e7e0c96fe77bcf6a020b84a44c47a722aac8e359`, fichier
`raydium_launchpad/raydium_launchpad.json`, SHA256
`963189409945069409f32e345d4adf2892e0b3ca1be504372577fe34a23c6cdb`.
PDA pool/config index zéro/vaults/autorité dérivées avec bump canonique ; calcul
Edwards contre-revu par oracle indépendant. Aucune clé de portefeuille créée.

La plateforme n'expose pas son administrateur initial. Son fee wallet n'est
qu'un candidat : il certifie la PDA **uniquement sur égalité exacte du hash
canonique**, sans supposer ce wallet administrateur. Sinon UNKNOWN ; index de
config non nul également UNKNOWN dans ce périmètre. Pas de certification du
binaire déployé.

| Candidat | Réanalyse des deux périodes |
|---|---|
| `21PBT…Adpk` | Token-2022 metadata-only, mint/freeze authority absentes ; arithmétique conditionnelle possible ; **5/6 PDA**, plateforme UNKNOWN. |
| `BNbNt…iTFm` | SPL classique ; **6/6 PDA** dont plateforme par hash ; pricing bloqué par supply **999 020 457 494 200** contre **1 000 000 000 000 000** déclarée par le pool. |

Une réconciliation par événements tels que burns peut être nécessaire, mais
aucune cause de la différence de supply n'est prouvée. Le contrôle est conservé.

**Sortie différée :** le vérificateur pur reprend la quantité du devis d'achat
fixée avant le followup et son état ultérieur observé. Ni réserves virtuelles ni
frais accumulés ne financent la sortie ; aucun achat hypothétique ajouté à cet
état, aucune écriture de P&L.

- Premier candidat : **33 724 510 353 232** unités atomiques théoriques dépassent
  les **7 509 219 938 216** unités outstanding observées ; estimation indisponible.
- Second candidat : état non qualifié à cause de la supply ; estimation refusée.

Ces refus ne prouvent pas une invendabilité après achat réel : cet achat aurait
changé les réserves et n'a jamais eu lieu. Une inversion de courbe après son
propre achat hypothétique est une autre estimation, pas une observation future.
Aucun de ces calculs n'est un fill ou un rendement.

## Conservation durable et autorisée des preuves disponibles

**5 journaux / 397 événements / 199 105 octets gzip**, exportés en JSONL
déterministe dans le dépôt GitHub **privé** avec le seul accès existant, pour
l'archivage interne demandé. Aucune SQLite, `.env`, clé ou donnée du ledger
PAPER envoyée ; aucun stockage ou service payant ajouté.

Commit distant `f2a43d8437ffcc89168f04174b3fa7482649e14e` relu via blobs GitHub
dans un répertoire neuf, pas depuis Git/DB locaux. SHA des blobs, tailles,
SHA256 compressés/décompressés et chaînes originales vérifiés. Accès aux DB
locales désactivé pendant le replay. Index et ancrages :
[evidence/p3/index.json](evidence/p3/index.json). Preuve :
[P3_EVIDENCE_RESTORE.json](validation/P3_EVIDENCE_RESTORE.json).
Résultats et réanalyses : [P3_V2_DATA_RESULTS.json](validation/P3_V2_DATA_RESULTS.json).

Replay hors réseau après récupération du dépôt privé :

```python
import json
from pathlib import Path
from bot.p3.evidence import verify_bundle
for anchor in json.loads(Path("evidence/p3/index.json").read_text())["bundles"]:
    proof = verify_bundle(Path("evidence/p3") / anchor["run_id"],
                          expected_tail=anchor["tail_hash"])
    assert proof["records"] == anchor["records"]
```

**Durabilité démontrée ; corpus brut complet non démontré.** Certains corps
index/pages/devis avaient déjà été remplacés par normalisations/digests. Ils
restent manquants, explicitement déclarés ; un digest ne recrée pas une réponse.
La nouvelle collecte conserve les entrées exactes utilisées pour la sélection,
les pages bornées et les réponses quote assainies nécessaires au replay ; refus
de preuve interdit => manque explicite. Correction testée synthétiquement, sans
nouvelle campagne revendiquée.

Les archives survivent au workspace tant que le dépôt privé/commits sont
conservés ; pas d'engagement de rétention illimitée. La chaîne prouve l'intégrité
relative aux ancrages Git, pas l'authenticité du fournisseur. L'accès anonyme ne
confère pas un droit général de redistribution publique/commerciale. Droits et
quotas de rétention soutenue restent à établir avant corpus prolongé.
L'export/push n'est pas automatique pendant la collecte : avant une durée accrue,
il faut fixer et vérifier les checkpoints, exports par lots et reprise après
interruption. Cette campagne bornée est déjà archivée et restaurée.

## Conditions encore nécessaires au PAPER interprétable

| Critère | État / preuve requise |
|---|---|
| Transport, créations, états | Budget validé, 2/2 créations et 4 snapshots ; aucune exhaustivité inférée. |
| Permissions | Sous-ensemble metadata-only validé ; autres types toujours refusés. |
| Certification complète | Seed admin première plateforme et supply seconde à réconcilier. |
| Couverture/gaps | Référence indépendante sur fenêtre/slots fixes et rattrapage sans gaps manquants. |
| Fraîcheur | Timestamp/slot du devis et borne de l'horloge source manquants. |
| Frais complets | Courbe **1,25 %** connue ; réseau/priorité/ATA/comptes/échecs inconnus. Ne pas redéduire des frais déjà inclus dans une quote. |
| Sortie prospective | Aucune vente API disponible ni estimation ultérieure qualifiée ; quantité/inventaire/impact de sa propre entrée à valider. |
| Capital SOL | Arithmétique et réservations exactes conservées ; aucun débit/réinitialisation ni rendement déduit de ces devis. |
| Replay complet | Archives restaurées ; nouveau contrôle court préenregistré nécessaire pour valider les nouvelles rétentions avant durée accrue. |
| Économie | Deux candidats insuffisants ; protocole/arrêt/corpus/coûts pessimistes/validation indépendante à figer avant espérance. |

Pas de campagne prolongée, entrée PAPER qualifiée ou activation réelle.
**GO collecte instrumentale limitée ; NO-GO économique / INSUFFICIENT DATA.**

Validation finale : **1 342 passed, 1 skipped, 242 subtests passed**, warnings en
erreur, stderr vide, code 0 ; 33 cas ciblés de plus que le main revu. Code testé :
`de1e4b3d10b01a8bf9bd6003aaf8b8798a837ee5`. Aucune dépendance ajoutée, aucun
module de stratégie ou ledger modifié.
Livraison : [PR #21](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/21)
ouverte pour revue ; cette mise à jour de suivi ne change aucun code testé.

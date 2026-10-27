# Rugger Bot V1 — reprise autonome depuis Git

État du 27 octobre 2026 (Europe/Paris). Lire ce document et `AGENTS.md` avant
`PROJECT_STATUS.md`, puis uniquement les sources utiles à la priorité courante.
L’historique de discussion n’est pas nécessaire à cette reprise.

## Objectif et périmètre autorisé

Qualifier un éventuel avantage économique net en SOL à partir de données réelles,
prospectives et reproductibles, exclusivement PAPER. Corrections, tests isolés,
branches, commits et PR sont autorisés sans relance après chaque étape. Corriger
les défauts reproduits et poursuivre les dépendances accessibles. Ne pas optimiser
sur la validation ni changer les seuils pour obtenir un résultat positif.

Aucun ordre, signature, transaction blockchain, portefeuille financé, passage au
réel ou dépense. Aucune lecture de secrets `.env`, export de base privée, migration
du ledger utilisateur, nouveau service payant ou collecte prolongée. Une courte
collecte exige droits, gratuité, quota disponible, protocole préalable et limites
vérifiés. L’accès technique à une clé ou un endpoint ne suffit pas. Conserver le
capital configuré (historiquement 10 SOL) ; aucune remise à zéro ni conversion EUR.

## Références et livraison non fusionnée

- Dernière PR fusionnée vérifiée : #21, `7ddddb9f73339242fbcb5b9bf10fa329c82fa700`.
- Branche de reprise : `fix/p3-exit-evidence-continuation`.
- [PR #22](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/22) ouverte,
  **non fusionnée**. Les nouvelles capacités ne sont pas encore dans `main`.
- Code publié : `4f0fec80f7c62ae74778a04ae8b564a0104091e4`.
  Arbre Git testé : `539f716e04666c126ee0c30b628d22417625951a`.
- Commit local de validation : `e69b175faaa8cf864e2a29c14fc956511f57bae2`,
  même arbre que le code publié. Les commits diffèrent car publication via API
  GitHub ; le transport Git direct a échoué. Le suivi documentaire vient ensuite.
- Reprise locale initialement propre, un worktree, aucun stash ni objet orphelin
  signalé ; aucune PR ouverte trouvée avant #22. La référence locale origin/main
  était ancienne ; `main` distant a été vérifié via GitHub au commit de #21.
- `P3_PR21_REVIEW.md` absent du dépôt local et du `main` distant ; aucune variante
  locale récupérée de `bot/p3/collect.py`. **Ancienne session et état non publié
  non récupérés**. La reprise porte sur le code et les preuves conservés dans Git.

## Progrès vérifiés et fichiers

- `bot/p3/quotes.py` : rejet tardif => montants/route/frais inutilisables effacés,
  corps assaini conservé pour diagnostic.
- `bot/p3/collect.py`, `campaign.py` : reçu d’annulation achat/vente avant propagation ;
  refus de corps dangereux => métadonnées temporelles/statut conservés sans ce corps.
- `bot/p3/launchlab.py` : profil opt-in `published_metadata_v1` conserve les faits
  mint/vault et l’écart supply avant rejet. Le profil historique `legacy` garde
  ses résultats ; aucun garde de supply ou d’identité affaibli.
- `tools/offline_check.py` rend le lanceur isolé indépendant du chemin de cette VM.
- `tools/verify_p3_evidence.py`, `tools/diagnose_p3_archived_exits.py` et
  `tools/verify_p3_accounting.py` fournissent replay, diagnostic et oracle indépendant.
- `P3_CONTINUATION_VALIDATION.md` : causes, validation, limites et prochaine étape.

## Validation exécutée dans cette session

Python 3.12.14, pytest 9.1.1. Référence #21 sur copie Git isolée :
**1 342 passed, 1 skipped, 242 subtests passed**. Ancien code + six régressions :
**6 failed**, comme attendu avant correction. Après correction :
**1 348 passed, 1 skipped, 242 subtests passed**, warnings en erreur, stderr vide.
Le skip correspond à une base utilisateur volontairement absente.
Revue croisée ciblée des changements et des invariants : aucun bloquant identifié.

| Périmètre | Qualification actuelle |
| --- | --- |
| Corrections quote/annulation/rejet et conservation future | TESTÉ SYNTHÉTIQUEMENT |
| 5 archives, 397 événements, intégrité vs ancres Git | VALIDÉ SUR REPLAY |
| 4 analyses historiques v2 | VALIDÉ SUR REPLAY, résultats identiques |
| Calculs comptables : 1 000 cas + 1 009 rejets et frontière sous-lamport | TESTÉ SYNTHÉTIQUEMENT |
| Nouvelle collecte réelle, nouvelles sorties, fonctionnement continu | NON VALIDÉ dans cette session |

Artefacts : `validation/P3_OFFLINE_REPLAY.json`, `P3_ACCOUNTING_ORACLE.json`,
`P3_ARCHIVED_EXIT_DIAGNOSTICS.json` et `P3_CONTINUATION_TESTS.json`.
Le replay local ne renouvelle pas la preuve historique de restauration distante.

## Résultats économiques et inconnues

**NO-GO / INSUFFICIENT DATA**. Aucun profit net ni fill certifié. Dix corps de devis
historiques fournisseur manquent ; les deux refus de vente v2 sont HTTP 200 /
provider_rejected mais leur cause précise est inconnue. Ne pas inventer une route
absente, un rejet Token-2022 ou un défaut fournisseur à partir du digest.

- `21PBT…Adpk` : plateforme UNKNOWN ; sa quantité de sortie issue du devis dépasse
  l’inventaire outstanding de l’état ultérieur sans notre achat. Ce refus de calcul
  ne démontre pas une impossibilité après un véritable achat.
- `BNbNt…iTFm` : supply mint `999020457494200` contre pool `1000000000000000`,
  écart `-979542505800` aux deux slots `461982938` et `461983014` de réponses
  cohérentes. Cause burn ou autre mécanisme non établie ; pricing reste bloqué.
- Temps/slot fournisseur des devis, frais réseau/ATA/priorité/échecs, couverture
  indépendante et sorties ultérieures qualifiées restent manquants.
- Les frais déjà inclus dans une quote ne sont pas soustraits une seconde fois.
  Coûts inconnus et sorties absentes ne deviennent pas zéro ; USD exige FX causal.

## Commandes de reprise

Après récupération de la branche #22 dans un environnement Python avec les
`requirements.txt` et pytest installés (aucun accès marché requis) :

```sh
git status --short
git log -3 --oneline
python -B tools/offline_check.py
python -B tools/verify_p3_evidence.py
python -B tools/diagnose_p3_archived_exits.py
python -B tools/verify_p3_accounting.py
```

Le lanceur copie les seules sources/tests/fixtures suivis ou nouveaux non ignorés,
sans `.git`, `.env` ni DB ; il bloque le réseau et les lectures dotenv. Pour cibler :
`python -B tools/offline_check.py -q tests/test_p3_collection.py -p no:cacheprovider -W error`.
Interpréteur utilisé ici : `/workspace/.cloud-env/rugger_bot_v1/venv/bin/python`.

## Priorité suivante et limites externes

1. Vérifier les conditions applicables de conservation des nouveaux corps, quotas
   gratuits et transport anonyme ; les pages officielles relues ne suffisent pas
   à établir toutes ces conditions. Transport Git direct : erreur proxy puis HTTP
   503 ; connecteur GitHub utilisable pour cette livraison. Aucun appel marché fait.
2. Préenregistrer le contrôle court décrit dans `P3_CONTINUATION_VALIDATION.md`,
   avec identité/horodatage/empreinte propres ; ne pas modifier les anciens plans.
3. Vérifier corps réels, refus et replay après fermeture/export avant corpus accru.
4. En fonction des preuves : identité plateforme et supply, effet d’entrée/sortie
   contrefactuelle, coûts complets. Recherche économique seulement après admission.

Ne pas fusionner automatiquement #22. Préserver les commits de branche ; avant
fusion le rollback consiste à conserver `main` #21, après fusion utiliser une PR de
revert explicite. Mettre ce document et `PROJECT_STATUS.md` à jour à chaque livraison.
Aucune collecte ou tâche de fond ne continue après la fin de cette session.

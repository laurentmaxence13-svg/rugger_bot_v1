# Revue indépendante de la PR #20 avant fusion

27 octobre 2026, Europe/Paris. Référence examinée :
`b30356bdd0758de53fdc51248d1c105bed0aa97b`.

Les **1 304 tests réussis, 1 ignoré, 242 sous-tests réussis** annoncés ont
été reproduits sur copie isolée, warnings en erreur, code 0 et stderr vide.
Les revues réseau, financière/provenance et durabilité ont été séparées.

## Défauts effectivement reproduits et corrigés

| Défaut | Preuve hors réseau | Correction |
|---|---|---|
| Requête annulée sans reçu | Une annulation pendant JSON laissait une tentative transport et zéro reçu. | Reçu RPC/index/quote conservé avant propagation de CancelledError. |
| Minuterie coopérative seule | Du traitement synchrone pouvait retarder la minuterie asyncio et laisser partir une requête après le budget temporel. | Deadline monotone vérifiée après résolution du proxy, juste avant dispatch ; timeout borné au temps restant, arrondi aiohttp désactivé. |
| Enveloppe RPC ambiguë | id=True était accepté comme id=1 ; jsonrpc n'était pas vérifié. | Protocole 2.0 et identifiant entier exact requis. |

Cinq tests ciblés couvrent les causes, pas une augmentation artificielle du
corpus. La suite complète de la PR corrigée, excluant les futurs modules
non suivis, donne **1 309 réussis, 1 ignoré, 242 sous-tests réussis**,
warnings en erreur, code 0 et stderr vide.

Les plans préenregistrés, tailles, seuils et budgets sont inchangés.
La deadline empêche de nouveaux envois après la fenêtre ; une finalisation locale
synchrone peut terminer plus tard et doit rester comptée dans elapsed_ms/NO-GO.

## Invariants et preuves revus

- Arithmétique SOL entière, ceil des frais et floor des sorties : oracle
  indépendant Fraction/cash sur 1 000 scénarios synthétiques cohérents.
- Réservations de capital, frais uniques et sorties partielles : contrôles
  existants maintenus ; aucune écriture dans le ledger historique.
- Quatre analyses reproduites depuis les octets conservés ; création diagnostique
  vérifiée par signature/slot/succès/mint/pool/créateur. Le primaire reste 0/2.
- Sessions anonymes sans netrc/cookies ; hôtes et méthodes en lecture seule
  strictement limités, TLS conservé, redirections/retries automatiques désactivés.
- Chaînes de journal et ancrages vérifiés ; aucune projection présentée comme
  exécution, sortie future garantie ou performance réalisée.

## Limites de données, distinctes d'un blocage de fusion logicielle

P3 économique reste **NO-GO / INSUFFICIENT DATA**. Les modules sont de la
préparation PAPER ONLY : extensions/PDA, couverture indépendante, source clock,
frais complets et observation de sortie ultérieure restent à établir.

Les journaux étaient uniquement locaux au Cloud. Ils contiennent les comptes
et transactions disponibles, mais seulement des normalisations/digests pour
certains index, pages de signatures et devis. Un export durable ne recréera pas
les corps déjà absents. Leur complétude doit être déclarée séparément.

**Verdict : fusion admissible après les corrections ci-dessus**, puis exécution
unique du plan v2 existant, avec ses limites intactes. Pas d'ordre réel, portefeuille,
souscription, nouvelle dépense ou changement de stratégie autorisé par cette revue.

Logs locaux : `/workspace/.cloud-env/rugger_bot_v1/pr20_review/`.

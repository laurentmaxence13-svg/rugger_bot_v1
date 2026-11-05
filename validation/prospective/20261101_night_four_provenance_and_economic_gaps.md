# Audit PAPER — preuves et limites (1 novembre 2026)

## Provenance de la cohorte (archives historiques)

- Workflow GitHub Actions **41276949437**, terminé avec succès sur le commit `b187e27c3bb3f5ba2aa3e8fa57c43b539ff7e960`. Les **122 tests ciblés** du workflow ont réussi.
- Les trois campagnes publiques archivées **41256274821**, **41257191511**, **41266654485** contiennent **362 signatures d'événements distinctes** et **1 identité de créateur prospectif annoncée**.
- La preuve de créateurs Raydium archivée **41260115617** comporte **2 créateurs signés** ; la jointure avec le créateur prospectif n'a trouvé **aucun chevauchement** d'identité, signature ou pool. Cela donne **3 identités publiques distinctes**, pas 3 acteurs économiques indépendants prouvés.
- **0 nouvelle preuve Ed25519 rejouée indépendamment dans cette jointure** ; **0 cycle économique Master/référence qualifié**, **0 ordre financier**.
- Rapport et artefact : GitHub Actions run `41276949437`, artifact `13071354566`. L'audit est réexécutable hors réseau à partir des archives identifiées.

## Corrections de la présente session

- Le registre de cohorte recalcule la construction canonique de chaque gel pré-résultat : un hash SHA-256 recalculé sur des horloges impossibles ou sur une attestation de moteur falsifiée ne suffit plus à rendre le gel admissible.
- La trace des deux moteurs doit correspondre à l'empreinte des caractéristiques figées, aux actions réellement déclarées, à l'identité de source et aux périmètres d'admission. Une trace structurellement cohérente reste **une déclaration**, et non une preuve externe d'exécution des moteurs.
- Les horloges de disponibilité historiques non positives et les historiques mélangeant mint/pool/créateur sont refusés avant évaluation des deux moteurs.
- Les divergences d'entrée Master/référence et leurs capitaux PAPER hypothétiques sont dénombrés sans ignorer les positions non résolues.
- En présence de `U` comparaisons censurées et d'une somme connue `K`, l'audit expose le **seuil de sensibilité** `floor(-K/U)+1` lamports de différence moyenne inconnue nécessaire pour que le total conditionnel soit strictement positif. Il ne remplace jamais les inconnues par zéro et ne prétend pas borner les frais inconnus.

## Critères non satisfaits

1. Protocole prospectif futur uniquement : `validation/prospective/20261101_public_creator_holdout_protocol.json` ; date d'entrée en vigueur **2026-11-01 07:00 Europe/Paris**. Les trois campagnes historiques ne doivent pas être requalifiées comme validation prospective de ce protocole.
2. Il manque au moins **50 créateurs authentifiés dans le holdout**, une preuve de couverture exhaustive des créations indépendantes et un ancrage externe du gel de décision.
3. Il manque **50 cycles économiquement qualifiés**, des cotations exact-lot horodatées et authentifiées, une prise en compte exhaustive des frais et des sorties impossibles ou ouvertes.
4. Le comparateur produit des **intents PAPER** et des projections conditionnelles, **pas des transactions exécutées**. Aucun avantage net Master n'est démontré, et le verrou LIVE ne doit pas être modifié.

## Prochaine acquisition admissible

Après l'entrée en vigueur du protocole, lancer **un seul** workflow de collecte Helius borné `helius-prospective-campaign.yml` (4 fenêtres de 60 s, 40 requêtes Helius en plafond), conserver les artefacts, vérifier les signatures et regrouper par créateur, puis figer les deux intentions avant S2. Si les horloges, les coûts ou les quotes manquent, conserver chaque cas dans le dénominateur comme censuré et **ne pas calculer de profit réalisé**.

Les références de workflow sont des observations archivées. Les modifications de cette session doivent être vérifiées par la régression et l'audit sur leur commit exact avant d'être présentées comme validées.

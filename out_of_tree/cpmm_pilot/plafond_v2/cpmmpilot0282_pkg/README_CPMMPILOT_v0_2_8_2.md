# cpmmpilot 0.2.8.2 — plafond v2 de la collecte G2-3 (PROJET, rien de gelé)

RUGGER 01, 26/11/2026. Plan de R02 du 26/11 à 13:48Z (point 1), et décision de R04 de 13:54Z : R01 en est le seul
auteur. Ce paquet est une copie de cpmmpilot 0.2.8.1, extraite de 7ce025c et versionnée à part : rien n'est modifié en
place.

## Ce qui change

Seuls deux fichiers de code changent, à auditer par diff contre 7ce025c :
- `budget.G23_CAP` : 32 340 → 88 200, soit 98 % de 90 000, le plafond v2 de l'additif du propriétaire.
- `rpc.ADDENDUM_TEXT_SHA256` : vaut `None` (EN ATTENTE). Une fois inscrite, cette empreinte s'ajoute à
  `AUTHORIZED_TEXT_SHA256`. Le texte de base 3d6999ec reste dans l'ensemble ; rien d'autre n'y est ajouté.
  `NOT_COVERING` est inchangé.

Le fichier de tests change aussi :
- le test du plafond devient 88 200, avec l'arrêt dur exact : 88 190 + 10 accepté, 88 191 + 10 refusé avant l'appel ;
- le test de l'ensemble autorisé tient compte de l'additif une fois inscrit ;
- `test_the_addendum_is_inscribed` ÉCHOUE VOLONTAIREMENT tant que l'additif n'est pas signé et vérifié par R02.

## Tests

56 réussis, plus l'échec volontaire.

## Publication de l'inscription

Elle ne changera que la ligne `ADDENDUM_TEXT_SHA256`. Elle ajoutera aussi `AUTORISATION_G23_ADDENDUM.txt`, que R03 crée
à l'octet près depuis le message du propriétaire, après la vérification de R02 à la source.

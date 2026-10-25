# P1.5 — Cohérence des cotations PAPER

Référence vérifiée : `main` à `f24b574a873d2affb127ad59d6f91550103dd3aa`.
Branche : `fix/p1-paper-quote-consistency`. Aucun commit, push ou fusion.

## Cause démontrée par le code

`MarketQuote` transporte prix, liquidité, source, funding et métriques optionnelles.
P1.4 persistait ces champs avec INSERT OR IGNORE. En cas de collision de clé
`(mint,timestamp)`, `_record_quote` conservait le premier prix mais poursuivait
avec la nouvelle cotation : ouverture, peak/last_price, TP/SL et P&L pouvaient
donc utiliser un prix absent de la série persistée.

Dans `paper_engine.collect_once`, `price_history` charge la série stockée ;
`build_features` lui ajoute la cotation courante et `decide` calcule la décision.
`record_decision` précédait `record_quote` : corriger uniquement ce dernier
aurait laissé des décisions fondées sur une observation rejetée.

Les deux chemins actifs de comptabilisation sont `paper_trader.run -> record_quote`
et `paper_engine.collect_once -> record_quote`. Les copies bot/bot et tests/tests
ne sont pas modifiées. Les calculs TP/SL, coût, taille de position, P&L et capital
restent ceux de la référence.

## Invariant et politique

Pour chaque clé `(mint,timestamp)`, la première observation persistée est la
référence immuable. Aucun traitement financier ou décision shadow_final nouveau
ne peut utiliser une observation contradictoire avec cette référence.

- Première observation : comportement habituel, insertion et traitement.
- Répétition identique : aucun retraitement financier, aucune nouvelle décision.
- Répétition contradictoire : observation rejetée, alerte console et compteur ;
  historique, décision existante, position et capital conservés.
- Autre seconde : nouvelle observation traitée normalement.

La comparaison porte sur toutes les colonnes de cotation persistées, selon la
normalisation P1.4 existante. NULL n'est pas zéro. Source inconnue n'est pas une
source DEX ou LaunchLab ; l'ancienne ligne n'est pas enrichie implicitement.
Funding, liquidité, profondeur et slippage ne sont pas fusionnés. Aucune date
fournisseur n'est inventée. Les contrôles de prix invalides restent prioritaires
dans record_quote et peuvent lever ValueError avant un comptage de conflit.

Le rejet évite de reconstruire une cotation canonique depuis une ancienne ligne
incomplète. Il implique qu'une première observation collectée sans entrée ne
peut pas être rejouée pour ouvrir une position après changement de modèle,
d'autorisation ou d'allocation : une nouvelle observation est nécessaire.

## Transactions et mesure

`skip_recorded_quote` partage la représentation de stockage `_price_values` avec
`_record_quote`. Dans le moteur, le contrôle est effectué après l'enrichissement
asynchrone mais avant features/decide/record_decision, sous la même transaction
que record_quote. Aucun await n'est ajouté dans ce bloc. Le contexte existant
utilise BEGIN IMMEDIATE ou un savepoint si l'appelant possède une transaction.
Une erreur SQLite est propagée ; décisions et écritures financières du bloc
sont annulées ensemble. Les transactions appartenant à l'appelant sont conservées.
`_record_quote` protège également un appel direct sans verrou préalable.

L'insertion d'une nouvelle cotation utilise INSERT simple : une violation SQLite
inattendue n'est plus ignorée. Le verrou empêche deux écrivains de traiter une
nouvelle clé simultanément. Les seuils de risque ne changent pas.

Migration additive, par setup, sans réécriture de paper_prices :

```sql
CREATE TABLE IF NOT EXISTS paper_quote_conflicts (
  mint TEXT NOT NULL,
  timestamp INTEGER NOT NULL,
  rejected_observations INTEGER NOT NULL,
  differing_fields_json TEXT NOT NULL,
  PRIMARY KEY(mint,timestamp)
);
```

Le compteur s'incrémente par tentative contradictoire, sans stocker le nouveau
prix ni modifier la cotation retenue. differing_fields_json décrit le dernier
conflit de cette clé. Les répétitions identiques ne sont pas comptées.
paper_report.quote_provenance expose conflicting_quote_keys et
rejected_conflicting_observations. Les compteurs sont zéro si la table n'existe
pas ; conflict_history_complete reste false, car les conflits antérieurs à ce
correctif sont inconnus. Ce sont des observations rejetées, pas des trades rejetés.

## Validation reproduite sur copie isolée

Python 3.13.15 ; sources et fixtures suivies copiées sans .env, secrets ou DB
réelle. Aucun scanner, bot réel, RPC, WebSocket ou DexScreener réel lancé.

Commande, avec PYTHONDONTWRITEBYTECODE=1 :

```text
python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider
```

| Étape | Résultat exact |
| --- | --- |
| Référence initiale | 188 passed, 1 skipped, 174 subtests passed in 6.01s |
| Premier passage du correctif sur tests existants | 1 failed, 187 passed, 1 skipped, 174 subtests passed in 5.44s |
| Correctif avec 14 nouveaux tests et fixture adaptée | 202 passed, 1 skipped, 187 subtests passed in 6.29s |
| Validation finale, 17 nouveaux tests | 205 passed, 1 skipped, 187 subtests passed in 6.14s |

L'échec intermédiaire était le test du capital libre : il modifiait l'allocation
de 60 % à 40 % en rejouant la même observation. La seconde tentative de sa
fixture est maintenant à 161 au lieu de 160 ; les assertions sur 6 SOL engagés,
10 SOL de capital et 10 SOL engagés après la seconde tentative sont conservées.
Un nouveau test vérifie explicitement que le rejeu identique ne crée pas d'entrée.

Les nouveaux tests couvrent collisions identiques/prix/source/métadonnées,
NULL/zéro, historique sans provenance, TP/SL, position ouverte, nouvelle entrée,
PnL/capital et absence de double PnL, décisions shadow_final, concurrence de
deux connexions pour record_quote et pour le moteur, erreurs d'entrée/capital/
compteur, rollback de l'appelant et rapport sans table de conflits.

Une comparaison séparée a exécuté les modules originaux extraits du commit de
référence puis les modules corrigés, sur six scénarios sans collision : sources
inconnue/DEX/LaunchLab, prix 1 à 160 puis 2 ou 0,5 à 161. Les quatre tables
paper_prices, paper_decisions, paper_trades et paper_portfolio et les métriques
de performance ont été sérialisées ensemble. Les fichiers avant/après sont
identiques (SHA-256 :
`6A233B610AF7BE19A4065F63758C3B6A0FDD2B0F769B19049BEED3BFB6EEFD34`).
Les capitaux finaux sont 10,98 et 9,48 SOL pour chaque source : P&L +0,98 et
-0,52 SOL avec position de 1 SOL et coûts de 2 %. Les scores différents entre
DEX et courbe, préexistants, restent inchangés.

Exemple de collision : entrée à 1 USD à 160, puis prix 2 USD à la même seconde.
Avant : TP possible à 2 USD, capital 10,98 SOL alors que la ligne stockée vaut 1.
Après : seconde observation rejetée, position ouverte et capital 10 SOL.
Une cotation à 2 USD à 161 peut ensuite déclencher normalement le TP.

git diff --check passe. Les tests P1.3 et P1.4 restent inclus.

## Limites

- Les collisions à la seconde sont rejetées, même si le marché a réellement
  changé ; une nouvelle seconde est nécessaire pour traiter le nouveau prix.
- Idempotence financière et des décisions : les statuts opérationnels de
  collecte peuvent encore être actualisés avant le contrôle du doublon.
- Aucun conflit historique n'est reconstitué ; les incohérences financières
  préexistantes ne sont pas réparées.
- Le journal suit les tentatives et les derniers champs divergents, pas tous
  les payloads reçus. Un rollback de l'appelant annule aussi ses compteurs.
- SQLite peut refuser une écriture occupée ; l'erreur est propagée sans
  simulation partielle. La transaction synchrone peut retarder les autres tâches.
- Pas de nouvelle garantie de fraîcheur, d'exhaustivité, d'exécutabilité ou
  de rentabilité ; aucun changement général de stratégie.

## Fichiers et rollback précis

Fichiers modifiés/créés :

- bot/analyser/paper_trader.py
- bot/analyser/paper_engine.py
- tests/test_paper_capital_reservation.py
- tests/test_paper_quote_consistency.py (nouveau)
- P1_5_PAPER_QUOTE_CONSISTENCY.md (nouveau)

Sans modifications ultérieures à préserver :

```powershell
git restore --source=f24b574a873d2affb127ad59d6f91550103dd3aa -- bot/analyser/paper_trader.py bot/analyser/paper_engine.py tests/test_paper_capital_reservation.py
Remove-Item -LiteralPath tests/test_paper_quote_consistency.py
Remove-Item -LiteralPath P1_5_PAPER_QUOTE_CONSISTENCY.md
```

Si une DB est migrée ultérieurement, conserver paper_quote_conflicts : l'ancien
code l'ignore. Ne pas restaurer une ancienne DB qui ferait perdre de nouvelles
observations. Le rollback réintroduit le comportement P1.4 des collisions ; il
ne répare ni n'annule les trades déjà enregistrés. Aucune DB réelle n'a été
migrée pendant cette intervention. Capital initial maintenu à 10 SOL.

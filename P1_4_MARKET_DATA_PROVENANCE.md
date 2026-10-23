# P1.4 — Provenance et qualité des cotations

Référence : `main`, commit `f47217e3d846f3fdb86647bca5b317b5f206a650`.
Branche : `fix/p1-market-data-provenance`. PAPER ONLY.

## Diagnostic démontré par le code

- `paper_trader._market_quote_from_pair` parse les réponses DexScreener ;
  `fetch_quote(..., include_metrics=True)` conserve le MarketQuote enrichi.
  Les deux boucles actives, paper_trader et paper_engine, utilisent cette option.
- `launchlab_onchain.fetch_onchain_quote` calcule un prix USD de courbe et
  un funding USD à partir de real_b et du taux de conversion existant.
- `paper_engine.collect_once` essaie la courbe puis le marché en repli.
- `record_quote` / `_record_quote` persistaient les prix et métriques, mais
  perdaient quote_source et funding_usd. `paper_report` ne les mesurait pas.
- Le code ne récupère aucune date fournisseur de cotation. `pairCreatedAt`
  date la création de la paire ; le slot RPC n'est pas une date de prix.

## Schéma et conventions

`setup` ajoute si nécessaire, avec ALTER TABLE ADD COLUMN :

| Colonne paper_prices | Type | Convention |
| --- | --- | --- |
| quote_source | TEXT nullable | `dex_market` pour le parseur DexScreener ; `launchlab_curve` pour la courbe ; NULL si non renseigné |
| funding_usd | REAL nullable | funding de courbe en USD ; zéro connu distinct de NULL |

Aucune réécriture de ligne historique, aucun remplissage rétrospectif, aucune
modification de la clé primaire `(mint,timestamp)`. Migration additive et
idempotente exécutée par setup ; elle n'a été appliquée ici qu'aux DB synthétiques.
La déclaration CREATE historique est conservée ; setup ajoute les colonnes aux
bases neuves comme aux anciennes.

`timestamp` reste la date de collecte locale en secondes Unix. Aucune colonne
de date fournisseur n'est ajoutée, faute de donnée réelle disponible dans les
collecteurs. Une MarketQuote construite sans source explicite et un tuple
historique ont désormais une source inconnue ; le parseur DexScreener attribue
explicitement `dex_market`. Le contrat des trois premières valeurs est conservé.
Un funding négatif, NaN ou infini devient NULL dans les seules métadonnées
persistées ; il n'est pas remplacé par zéro. Les validations de prix existantes
restent en place.

Le prix LaunchLab est calculé depuis la courbe, le prix DEX est observé chez
DexScreener. Le champ historique liquidity_usd reste inchangé, y compris sa
valeur funding pour une courbe : les consommateurs existants ne sont pas
réinterprétés dans cette correction. funding n'est ni une liquidité DEX ni une
profondeur exécutable. depth_usd et slippage_bps_est gardent leurs définitions
et estimations existantes, sans garantie d'exécution.

## Rapport et doublons

`paper_report.quote_provenance` ajoute des compteurs par source (NULL et chaîne
vide regroupés sous `unknown`), funding connu/inconnu et proportion connue.
Sur historique vide, les compteurs et la proportion sont zéro. La date
fournisseur est inconnue pour toutes les lignes ; l'âge fournisseur est NULL,
le nombre d'âges mesurables est zéro. Aucune fraîcheur n'est affirmée.

INSERT OR IGNORE conserve la première cotation à mint/timestamp identiques.
Les colonnes persistées sont comparées lors d'un doublon ; une contradiction
produit une alerte console sans afficher les valeurs. Pas d'enrichissement
rétrospectif silencieux. Comme auparavant, le traitement PAPER peut utiliser
la nouvelle observation même si l'historique garde la première : cette limite
est conservée pour ne pas modifier les décisions. L'alerte n'est pas un journal
durable de conflits.

## Validation reproduite sur copie isolée

Python 3.13.15, sans .env ni DB réelle, sans installation ou bot réel.
Commande : `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider`,
avec PYTHONDONTWRITEBYTECODE=1.

- Avant : **175 passed, 1 skipped, 161 subtests passed** (5.32 s).
- Après : **188 passed, 1 skipped, 174 subtests passed** (5.42 s).
- 13 nouveaux tests : chemins LaunchLab/DexScreener simulés, absence de
  métadonnées, NULL/zéro, ancienne DB copiée, migration répétée et conservation
  de l'original, doublons identiques/contradictoires, funding/prix non finis,
  couverture vide et mixte, comptabilité et décisions.
- Le test de décisions shadow_final passe aussi sur les deux modules originaux
  extraits du commit de référence : **1 passed** (0.23 s). Le scénario conserve
  les scores préexistants 50 (marché/inconnu) et 48 (courbe), avec entrée autorisée.
  L'hypothèse initiale du test selon laquelle les sources auraient le même score
  était incorrecte ; aucune règle de stratégie n'a été modifiée pour la satisfaire.
- Les tests P1.3 précédents restent inclus. git diff --check passe.

Limites : source déclarée par le collecteur, sans preuve d'exhaustivité ni de
fraîcheur ; taux SOL/USD et cohérence temporelle multi-requêtes non améliorés ;
pas de nouvelle mesure de profondeur exécutable. La comparaison synthétique ne
prouve pas l'équivalence sur tous les marchés ni une rentabilité.

## Fichiers et rollback

Fichiers : bot/analyser/paper_trader.py, bot/analyser/paper_engine.py,
tests/test_market_data_provenance.py et ce document.

Sans autre modification ultérieure, restaurer uniquement les deux modules depuis
le commit de référence :

```powershell
git restore --source=f47217e3d846f3fdb86647bca5b317b5f206a650 -- bot/analyser/paper_trader.py bot/analyser/paper_engine.py
Remove-Item -LiteralPath tests/test_market_data_provenance.py
Remove-Item -LiteralPath P1_4_MARKET_DATA_PROVENANCE.md
```

Si une DB a ensuite été migrée, conserver les deux colonnes supplémentaires :
l'ancien code les ignore. Ne pas supprimer de colonnes ou restaurer une ancienne
DB au prix de nouvelles observations. Aucun changement de DB réelle n'a été
effectué pendant cette intervention. Aucun commit, push ou fusion.

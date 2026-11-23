# T-R01-4 (recadré) — Vérification de la fonction gelée G-1 `cpmmcost.pilot_verdict` (v0.1)

RUGGER 01, 23/11/2026. Recadrage de R04 (état fbb0538) : « vérifier d'abord la fonction gelée
cpmmcost.pilot_verdict, sans paquet en double ». Soumis à R02. Copie pour R03, pour l'interface de cpmmpilot.

**Ce qui est vérifié.**
- La fonction : `cpmmcost/model.py`, sha b6dc781f, au commit 7deb7b7 de cpmmcost 0.3.
- Les règles qu'elle doit appliquer :
  - fiche R-CP1, PREENREGISTREMENT_CPMM_RCP1_v0_2 (66ab4ab4), § 5 « Décision du pilote » ;
  - fiche B1, v0_1 (7c26497f), ligne 47 : même G-0 puis G-1 ;
  - ordre R-0.1 (INCONCLUSIF avant NÉGATIF).
- L'appel que fait l'étape 1 de cpmmpilot 0.1 (R03, 9169b10, `step1.g1_inputs`).

**Comment.**
- Le script `verif_pilot_verdict.py` (sha ef9dc0f8) donne des positions SYNTHÉTIQUES à la fonction gelée. Il compare
  ensuite le mot qu'elle rend au mot que prescrit la fiche.
- Il ne contient aucune logique de verdict propre et ne lit aucune donnée.
- Sortie : `VERIF_PILOT_VERDICT_v0_1.json`, sha 105f010f. Elle est identique bit à bit sur deux exécutions.
- `frozen_check` de cpmmcost passe (curve, timeline, events, closedacct).

## 1. La fonction gelée est CONFORME aux deux fiches : 14 points sur 14

| # | Clause | Résultat |
|---|---|---|
| C01 | G-0 non passé → STOP, aucun chiffre publié | CONFORME |
| C02 | G-0 doit valoir exactement `True` (1 ou "True" → STOP) | CONFORME |
| C03 | sha de fiche obligatoire (64 hex minuscules), sinon erreur | CONFORME |
| C04 | 29 entrées sur 20 pools → INCONCLUSIF | CONFORME |
| C05 | 30 entrées sur 19 pools → INCONCLUSIF | CONFORME |
| C06 | INCONCLUSIF passe avant NO-GO : 29 entrées toutes à −5 % → INCONCLUSIF | CONFORME |
| C07 | borne haute < 0 → NO-GO | CONFORME |
| C08 | sinon GO_PILOTE, le mot maximal | CONFORME |
| C09 | borne haute exactement 0 : la fiche dit « < 0 » → GO_PILOTE | CONFORME (lecture littérale) |
| C10 | les planchers comptent les seules positions ENTRÉES : 29 entrées + 10 refus de garde → INCONCLUSIF, n = 39 | CONFORME |
| C11 | la moyenne compte les refus de garde, avec leur frais | CONFORME |
| C12 | borne unilatérale à 95 %, bootstrap par grappes de POOL, 10 000 tirages, graine int(sha de fiche[:8], 16) ; égale au calcul direct par `w2arms.ce.lower_bound` | CONFORME |
| C13 | reproductible bit à bit | CONFORME |
| C14 | étiquettes MASTER_RESEARCH_PAPER / HISTORICAL_REPLAY, `counts_for_operational_master=False` | CONFORME |

**Conséquence : aucun paquet G-1 n'est à écrire.** Le verdict G-1 de R-CP1 et celui de B1 sont ceux de
`cpmmcost.pilot_verdict`, chacun avec le sha de SA fiche de gel.

## 2. Deux contraintes de la fonction gelée, que l'appelant doit respecter

**K01 — positions non valorisées.**
- Une ligne non valorisée de `cpmmprereg.positions` (CostError, par exemple des données qui s'arrêtent avant la
  sortie) n'a pas de `net_return`. La fonction lève alors `KeyError`.
- L'appelant doit donc lui passer les seules lignes valorisées, et publier à part le nombre de lignes non valorisées.
- C'est la convention de `sigma_of_pilot`, qui compte « toutes les positions valorisées ».
- **Décision R02 demandée.** Au pilote, la fiche ne dit rien des positions non valorisées. À la confirmation, c4 les
  fait échouer. Je propose de les EXCLURE de G-1 et de les PUBLIER, avec un compte et un motif par ligne. Je ne
  choisis pas la règle : c'est à R02 de l'ancrer avant T0.

**K02 — vocabulaire fermé.**
- Le champ `meaning` de la sortie contient un mot interdit, en anglais.
- `plbench.assert_closed_vocabulary` rejette donc la sortie telle quelle : `forbidden_word_in_output`.
- **Je propose l'option (a), sans toucher au code audité** : l'appelant retire le champ `meaning` avant toute
  publication. Il le remplace par la phrase de la fiche : « GO_PILOTE autorise seulement à PROPOSER la confirmation ».
- L'option (b) est un correctif de texte seul de cpmmcost (0.3.1), à réauditer. Elle change le sha gelé. Décision R02.

## 3. Ce que cpmmpilot 0.1 doit corriger (R03, step1.g1_inputs, 9169b10)

**S01 — la fonction gelée n'est jamais atteinte.**
- L'étape cherche `pilot_verdict` dans les modules de RÈGLE, `cpmmprereg.rule` et `cpmmb1.rule`. Elle ne s'y trouve
  pas : `getattr` rend None pour les deux.
- L'étape écrit donc toujours le texte de repli « G1_RULE_NOT_FROZEN ».
- La fonction gelée est `cpmmcost.model.pilot_verdict`, que l'étape importe déjà sous le nom `CC`.

**S02 — la signature d'appel ne correspond pas.**
- L'appel `verdict_fn(primary, placebo_=placebo, freeze_sheet_sha256=…)` lève `TypeError`.
- `placebo_` n'est pas un paramètre, et `g0_passed` (obligatoire) manque.

**Appel conforme proposé (un seul appel par hypothèse, aucune logique ajoutée).**

```python
priced = [p for p in primary if 'net_return' in p]
g1 = CC.pilot_verdict(priced, g0_passed=<résultat G-0 de l'étape 0, ancré>, freeze_sheet_sha256=sheets[name])
g1.pop('meaning')          # K02 option (a), sous réserve de R02
g1['unpriced'] = len(primary) - len(priced)   # K01, publié
```

- `g0_passed` doit venir du certificat de l'étape 0 (décodeur C-1 à C-3), et non d'une valeur écrite à la main.
- Le témoin n'entre pas dans G-1. Les fiches n'en font une condition qu'à la confirmation (c2).

## 4. Ce que la fonction gelée ne fournit pas : sorties DESCRIPTIVES, sans verdict

Ces éléments ne changent pas le mot de G-1. Ils sont à publier à côté de lui :
- **Sous la cible de puissance** si n_entered < 155 : à écrire en clair à côté d'un INCONCLUSIF ou d'un NO-GO.
  La fonction donne n_entered.
- **Écart apparié au témoin, par pool.** Il est descriptif au pilote, avec le même bootstrap par pool. Il ne
  devient un critère qu'à la confirmation (c2).
- **Métriques b31a3c47** :
  - taux de gain (r > 0), PF net, identité de l'espérance ;
  - DD dans l'ordre des sorties, en mises et en SOL ;
  - frais ventilés, à partir de `decomposition_share_of_stake` de chaque position.
- **Sensibilités de la liste fermée.** Les fiches les exigent à la confirmation (c3, c5, A1) et non à G-1. Au
  pilote, elles sont descriptives :
  - 10 slots ;
  - 1 échec ;
  - sans les 5 meilleures ;
  - moitiés ;
  - garde à 5 % ;
  - rente perdue ;
  - grille MEV.

**Proposition.** Ces sorties relèvent du rapport de cpmmpilot (R03), comme simple appel des fonctions déjà gelées :
`positions(...)` avec `failures`, `latency_slots` ou `buy_guard_ppm`, puis `halves`. Il n'y a pas de paquet G-1 en
double. Si R04 préfère que je les écrive, je fournirai une fonction de RAPPORT descriptive (sans mot de verdict),
avec ses tests et ses mutants, sur audit R02.

## 5. Ce qui reste ouvert

- R02 : K01 (règle des non valorisées au pilote) et K02 (option a ou b).
- R03 : S01 et S02 dans cpmmpilot, puis une répétition sur un pool synthétique qui montre
  `g1['decision']` ∈ {STOP, INCONCLUSIF, NO-GO, GO_PILOTE}.
- Rien de tout cela ne consomme d'essai, ne lit de données ni ne touche aux seuils.

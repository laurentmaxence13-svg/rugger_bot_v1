# Lecture historique 005 — burns observés, réconciliation incomplète

Préenregistrement : `b993823c36b67c3fe298709758b7b61d49b9a943`.
Plan : `229e6f5b795dc2f8022079cdb9d8adba63b7abeb7de4d4501607945e66881684`.
Exécution unique : **5/5 getTransaction, 3 852/20 000 ms**, aucun retry, aucune
page supplémentaire ni cotation. Aucune requête réseau après ce contrôle.

Les cinq signatures fixées avant lecture ont été reçues et conservées. Trois
transactions sont des transferts de tokens. Deux contiennent un `burnChecked`
SPL Token classique réussi, sans autre mutation SPL dans la transaction :

| Slot | Burn, unités atomiques | Solde du compte token avant → après |
|---|---:|---:|
| 461979692 | 14 960 820 821 | 14 960 820 821 → 0 |
| 461981360 | 14 425 454 354 | 14 425 454 354 → 0 |

Les signatures complètes sont dans `validation/P3_MINT_HISTORY_005_QUALIFICATION.json`. Les deux burns visent
le mint BNbNt…iTFm et le même compte token public `6nVJP…959eL`.
Contre-vérification indépendante : la baisse exacte des soldes `preTokenBalances`
et `postTokenBalances` égale l'amount parsé pour chaque transaction, sans recours
aux nombres flottants `uiAmount`.

**Nouveau résultat : le mécanisme de burn est réellement observé**, pour un total
de **29 386 275 175 unités atomiques**. Mais le déficit historique à expliquer
est **979 542 505 800** ; il reste **950 156 230 625 unités atomiques non expliquées**.
Aucune réconciliation complète ni levée du garde supply n'est justifiée.

Parmi les signatures éligibles connues du contrôle 004, **21 corps de transaction**
restent non téléchargés. Une autre transaction au slot de création était hors
sélection à cause de sa borne basse stricte. La page RPC unique n'est pas une
preuve indépendante d'exhaustivité. Les burns peuvent aussi se produire comme
instructions internes dans des transactions référençant le pool : le contrôle
005 ne couvre pas tous les corps de telles transactions.

Journal dédié fermé, exporté puis restauré : **12 événements**, gzip **5 871 octets**,
ancre `1c1812f6f41acc37a6d0a3e66ba4a335ef2666667bf4ab670c5afc443b1bdcce`.
Aucun SQLite exporté, aucun ordre, aucun portefeuille, aucun garde modifié.

Reproduction de la qualification, sans réseau :

```sh
python -B tools/verify_p3_historical_burns.py
```

Verdict économique : **INSUFFICIENT DATA**. Pas de budget réseau supplémentaire
pour cette session ; les signatures manquantes sont conservées pour une reprise
préenregistrée ultérieure, sans modifier rétrospectivement les sélections 004/005.

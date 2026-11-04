# T-REG S-003 / T-0008 — décodage exhaustif des trades des 3 pools SOL complets

Tâche T-REG `T-0008` (issue #111), type `implement`, agent R01, relecteur R02.
Scénario `treg-scenario-S-003`, autorisé dans le chat du propriétaire
(référence `08ed4480…d1f5`). Aucune exécution du Master, aucune transaction,
aucun appel réseau, aucun fournisseur.

## Entrée (certifiée par R03, T-0007, issue #110)

- Commit : `4f2875d943f970983ee6198cc35931c3f31d380d`
- Chemin : `tests/fixtures/launchlab_sol_pools/` (`MANIFEST.json` et 3 archives `*.json.gz`)
- Digest combiné : SHA-256 de la sortie de `sha256sum` sur les 4 fichiers triés par nom.
  Recalculé indépendamment par R01 avant le travail ; doit être identique à la
  valeur `dataset.sha256` publiée par R03.

## Traitement

`validation/treg_s003/decode_pool_trades.py` applique les décodeurs déjà présents
sur ce commit (`bot.market.launchlab_events` : `extract_trade_events`,
`check_trade`, `implied_fee_rate_ppm`) à **chaque** transaction stockée des
3 archives. Il ne modifie aucun code du bot et n'ajoute aucune dépendance.

```bash
python -B validation/treg_s003/decode_pool_trades.py > validation/treg_s003/pool_trade_checks.jsonl
sha256sum validation/treg_s003/pool_trade_checks.jsonl
```

Code de sortie 0 seulement si chaque pool passe tous les contrôles ci-dessous.

## Contrôles par pool

| Pool | Signatures (MANIFEST) | Signatures réussies = transactions stockées | Trades décodés (MANIFEST) | Courbe exacte | Taux de frais = MANIFEST |
|---|---|---|---|---|---|
| `5pZ6Md…` | 38 (38) | 11 = 11 | 11 (11) | 11/11 | 11/11, 10000 ppm |
| `C7F9Kb…` | 133 (133) | 101 = 101 | 100 (100) | 100/100 | 100/100, 12500 ppm |
| `DVP426…` | 2 (2) | 2 = 2 | 2 (2) | 2/2 | 2/2, 18000 ppm |

Total : 113 trades (74 achats, 39 ventes) ; 0 échec du contrôle exact de courbe ;
0 écart de taux de frais.

Constat sur les données : la liste `signatures` d'une archive inclut les
transactions échouées (`err` non nul : 27 pour `5pZ6Md…`, 32 pour `C7F9Kb…`). Les
archives ne stockent que les transactions réussies. Le contrôle compare donc les
transactions stockées aux signatures réussies, et non au total.

## Sortie

- `validation/treg_s003/pool_trade_checks.jsonl` : 116 lignes, soit 113 trades et
  3 résumés de pool.
- SHA-256 : `879556eb20bce49b287d84a1e9ec1e98a3d464098484b7c0e13d09ff2b825bb4`,
  identique sur deux exécutions successives (sortie déterministe).

Ces chiffres valident les décodeurs sur des transactions historiques archivées.
Ils ne constituent **ni** un résultat de trading, **ni** une preuve de rentabilité,
**ni** un PAPER BUY/SELL du Master.

## Tests

```bash
python -B -m pytest -q tests/test_launchlab_*.py -p no:cacheprovider -W error
```

Résultat : `53 passed`, 0 échec (Python 3.13.18).

## Ce que R02 doit auditer

1. Le commit soumis ne modifie que `validation/treg_s003/` et descend de `4f2875d`.
2. Le digest combiné des 4 fichiers au commit `4f2875d` est égal à la valeur certifiée par T-0007.
3. Le script, exécuté au commit soumis et sans réseau, reproduit exactement `879556eb…`.
4. Les tests ci-dessus passent.
5. Les réveils de T-0007 et T-0008 sont journalisés dans le registre et acceptés par `accept-pointer`.

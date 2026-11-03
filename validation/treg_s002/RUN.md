# T-REG S-002 / T-0005 — décodage hors ligne des 7 transactions LaunchLab

Tâche T-REG `T-0005` (issue #108), type `implement`, agent R01, relecteur R02.
Scénario `treg-scenario-S-002`, autorisé dans le chat du propriétaire
(référence de mandat `bb16843c…7ba`). Aucune exécution du Master, aucune
transaction, aucun appel réseau, aucun fournisseur.

## Entrée (certifiée par R03, T-0004, issue #107)

- Commit : `4f2875d943f970983ee6198cc35931c3f31d380d`
- Chemin : `tests/fixtures/launchlab_trades/` (7 fichiers JSON `getTransaction`)
- Digest combiné : `eed8ddf85745bdeee7a1f9df73a386f8d8254c5ac7d998bc80eff8ff7755bfc3`
  = `sha256` de la sortie de `sha256sum *.json` exécuté dans ce dossier.
  R01 l'a recalculé indépendamment avant de commencer : identique.

## Traitement

`validation/treg_s002/decode_trade_events.py` applique les décodeurs déjà
présents sur ce commit (`bot.market.launchlab_events`) :
`extract_trade_events`, `check_trade` (contrôle exact de la courbe) et
`implied_fee_rate_ppm`. Le script ne modifie aucun code du bot et n'ajoute
aucune dépendance.

```bash
python -B validation/treg_s002/decode_trade_events.py > validation/treg_s002/trade_events.jsonl
sha256sum validation/treg_s002/trade_events.jsonl
```

## Sortie

- `validation/treg_s002/trade_events.jsonl` : 7 lignes, une par événement de
  trade, sur les 7 fichiers.
- SHA-256 : `fe0f25afaeea778d1c504f88194d5adf4307dc397ec4e456323487fb8b5ce2ee`,
  identique sur deux exécutions successives : la sortie est déterministe.
- `exact_curve_check` est vrai pour les 7 événements.
- `implied_fee_rate_ppm` varie de 12460 à 12499.

Ces chiffres décrivent des transactions historiques déjà archivées. Ils ne
constituent **ni** un résultat de trading, **ni** une preuve de rentabilité,
**ni** un PAPER BUY/SELL du Master.

## Tests

```bash
python -B -m pytest -q tests/test_launchlab_market_events.py tests/test_launchlab_collector.py -p no:cacheprovider -W error
```

Résultat : `32 passed`, 0 échec (Python 3.13.18).

## Ce que R02 doit auditer

1. Le commit soumis ne modifie que `validation/treg_s002/`.
2. Le digest combiné des 7 fixtures au commit `4f2875d` vaut `eed8ddf8…`.
3. Exécuter le script sur le commit soumis reproduit exactement `fe0f25af…`.
4. Les tests ci-dessus passent.
5. Le dépôt ne contient aucun secret ; le script ne fait aucun appel réseau.

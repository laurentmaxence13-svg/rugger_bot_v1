# psverdict 0.2 — corrections V-1 et V-2 de l'audit R02 (d67570d9) sur la 0.1

Pour le reste, README_PSVERDICT_v0_1.md reste valable.

- **V-1, pare-feu STRUCTUREL.**
  - Il est récursif et porte sur les CLÉS de la sortie paperstream : aucune ne doit contenir `pnl`, `return`, `mark_`,
    `hypothes`, `genuine`, `master_cycle`, `live_` ni `HW`.
  - Les clés de chaque table `blocking_reasons` sont exemptées, car ce sont les noms de motifs du moteur gelé. Leurs
    valeurs doivent en revanche être des entiers.
  - Les chemins des clés en cause sont publiés (`firewall_offending_keys`).
  - Tests :
    - (a) les motifs `high_volatility_return`, `causal_adjacent_price_return_proxy` et `critical_veto:mark_pnl_HW`
      passent, et le verdict reste IDENTITY_PROVEN ;
    - (b) une clé `pnl_lamports`, `net_return`, `mark_pnl_lamports` ou `HW1_label`, au sommet ou imbriquée dans une liste,
      échoue ;
    - (c) une valeur non entière dans `blocking_reasons` échoue.
- **V-2, trois contrôles ajoutés.**
  - **F-4 (`labels`) :** `thresholds.these_cycles_count_toward_them` et `thresholds.operational_master_entry` valent
    false. C'est un contrôle d'intégrité.
  - **C-3 (`cycles_sum`) :** `closed_cycles_all_arms` est égal à la somme de `counts.*.closed_cycles`.
  - **`journal` :** il exige en plus `reconciled_cycles > 0`.
- **Ancres R02 dans le code**, testées : MANIFEST ebe1959d…, série 7458f615…, 128 cycles master.

## Commande W1 (après le run, par R03 ou R02)

```
PYTHONPATH=<psverdict_pkg> python -B -m psverdict.verdict --run <ps04_W1_out1> --printed-sha256 <sha affiché par le run> \
       --rc <code retour> --manifest-sha256 ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e \
       --series-file-sha256 7458f61579bed089cde4ac2037839d2da1cc36c44e13d3f63252111e98e0dbdc --expect-master-closed 128
```

## Preuves

- **Tests.** 30 réussis sous `-W error`, hors réseau, sur une vraie sortie paperstream 0.4 obtenue sur les fixtures.
- **Mutations.** 27 sur 27 détectées (MUTATIONS_psverdict_v0_2.json). Elles portent sur :
  - chaque contrôle remplacé par « vrai » ;
  - les valeurs des motifs non vérifiées ;
  - les clés des motifs non exemptées ;
  - le pare-feu non récursif ;
  - zéro cycle accepté ;
  - INVALID_RUN rapporté comme IDENTITY_FAILED ;
  - le mode du checkpoint non vérifié.

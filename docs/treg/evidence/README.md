# Preuves archivées des exécutions T-REG réelles

Les issues GitHub font foi. Ces fichiers en sont une copie fidèle, conservée dans
le dépôt : on peut ainsi rejouer et tester les exécutions sans réseau
(`tests/test_treg.py::test_archived_runs_replay_and_show_exactly_their_unjournaled_wakes`).
Ne pas modifier : ajouter une nouvelle exécution dans un nouveau dossier.

| Exécution | Fichier | SHA-256 | Source |
|---|---|---|---|
| S-001 | `S-001/events.json` (21 événements) | `a28192a610dfc3cc5145e2b524646d8c111577e3962991fb72381d1200fe9b52` | issues #104 (T-0001), #105 (T-0002), #106 (T-0003) ; politique `docs/treg/runs/S-001.policy.json` |
| S-002 | `S-002/events.json` (19 événements) | `0abae59bee38d8ef4139db623db305fdddd8decc25a72fc6c26525df3d66fcd5` | issues #107 (T-0004), #108 (T-0005), #109 (T-0006) ; politique `docs/treg/runs/S-002.policy.json` |
| S-003 | `S-003/events.json` (21 événements) | `6fc02cef980bcc388addc8e66e8287926d6b430fb8bddc1c2cc058eeb9d5e49c` | issues #110 (T-0007), #111 (T-0008), #112 (T-0009) ; politique `docs/treg/runs/S-003.policy.json` |
| S-003 | `S-003/dashboard_full_registry.md` | `e317088c6a0f8a424e835925a50d7595e65a1bb0b92261e4b24490c61dc974a4` | tableau de bord du registre complet (61 événements), publié dans le corps de #103 |
| S-003 | `S-003/timeline_r01.md` | `4adc4b817cb0c2cee89db82bb0e4b169e7255d75974057d0fac0241e7d451200` | chronologie notée par R01 (envois, réceptions, tests négatifs) |
| S-002 | `S-002/dashboard_published.md` | `700854feebf690c354111cf1466ec8d81f05aa4c17ec5a2e1b87718c4647fed8` | tableau de bord publié dans #103 (commentaire 6618407272), sans la phrase d'introduction |

## Autres preuves

- **S-001** :
  - sortie de T-0002 sur `claude/r01-t0002-s001` @ `a94ecbcd9684578c4b9abdd7c01131f162da9612` ;
  - rapport T-0003 dans #103.
- **S-002** :
  - certification T-0004 : 7 fichiers @ `4f2875d`, digest combiné `eed8ddf85745bdeee7a1f9df73a386f8d8254c5ac7d998bc80eff8ff7755bfc3` ;
  - sortie de T-0005 sur `claude/r01-t0005-s002` @ `164291788e242d2142ec36027dabc453199cf0bf` (`trade_events.jsonl`, `fe0f25afaeea778d1c504f88194d5adf4307dc397ec4e456323487fb8b5ce2ee`) ;
  - audit PASS de R02 (#108) ;
  - rapport T-0006 dans #103 (commentaire 6618377904).

## Réveils non journalisés constatés (historique)

Le rejeu avec les règles de journalisation des réveils fait apparaître 3 réveils
que la transition exigeait, mais qui n'ont pas été inscrits au registre :
- S-001, T-0001 : R03 → R01. C'est l'ancien défaut des vues partielles, corrigé
  par `downstream`.
- S-001, T-0002 : R02 → R01. Le message a été envoyé, mais pas journalisé.
- S-002, T-0005 : R02 → R01. Le message a été envoyé, mais pas journalisé.

Avec les règles actuelles, le destinataire refuserait ces pointeurs
(`unjournaled_wake`), et l'émetteur recevrait `journal_wake` tant que le réveil
reste utile.

## S-003 : réveils journalisés en conditions réelles

- Les 4 réveils exigés ont tous été journalisés **avant** l'envoi, puis acceptés par
  `accept-pointer` chez leur destinataire.
- Tests négatifs réels :
  - N1 : pointeur non journalisé, refusé par R03 ;
  - N2 : pointeur mal adressé, refusé par R02 ;
  - D1 : doublon, sans effet chez R02.
- Audit PASS de R02 sur `claude/r01-t0008-s003` @ `0b41b13ba27352156ccd38690443605036703107`
  (sortie `879556eb…`). Rapport : #103, commentaire 6619063411.
- Écarts documentés :
  - l'énoncé de T-0007 contenait une erreur, corrigée dans la chaîne par `T-0007-OWNER-0002` ;
  - le premier démarrage de R03 est venu d'un message du propriétaire.

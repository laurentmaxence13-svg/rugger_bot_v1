# Comparaison décision par décision : test PAPER en direct arrêté ↔ livesim

getSlot, hors du texte 1366025b, a été utilisé (écart D15) ; usage ratifié a posteriori par le propriétaire le 26/11 à 07:14:54Z (événement e383a010), l'écart restant documenté.

Limite L4 : livesim est rétrospectif par blocs de 2 h, le live interroge toutes les 30 s ; l'écart de latence est structurel. Aucune somme nette ne se compare comme preuve d'un côté sur l'autre.

Labels : PAPER_LIVE_DEMO, PAPER_SIMULATION, DESCRIPTIVE_COMPARISON. counts_for_operational_master = false. Aucun verdict, aucune conclusion économique : résultat descriptif. Jamais une transaction Master opérationnelle, jamais compté pour 50/20.

now commun = 01:32:30Z (1795656750), dernier STEP du journal ; départ live 18:40:00Z ; départ livesim 11:38:51Z ; fin du segment conforme 20:10:03Z. Tête du journal 3ea13757f2b7f0e4033d323e53cc44a074d3836736b33b8d049f81574a98a97c (2056 enregistrements).

Vues : L = journal live ; P = a posteriori sur les pages live ; S = livesim sur ses pages. Raisons : arbre déterministe déclaré à R02 avant lecture.

Éligibilité livesim au now : GaPTvX… éligible; 6CQSpR… éligible; 5zk4vh… éligible

## Segment conforme [18:40:00Z ; 20:10:03Z[ (getSlot ratifié) : entrée et sortie avant 20:10:03Z

Signaux G2-3 : 2 lignes. Comptes à clé stricte (sans appariement décalé) : live seul 1, livesim seul 1. Lignes appariées « décalées » (seuil figé 3600 s), à part : 2.
Live : 1 positions (1 fermées, 0 ouvertes), somme nette des fermées -0.000994 SOL. Livesim : 1 positions (1 fermées, 0 ouvertes), somme nette des fermées -0.000868 SOL (descriptif).

| # | pool | présence | déclencheur L (latence) | déclencheur S | Δ décl. s / slots | entrée L / S (slot) | sortie L | sortie S | net L | net S | S à T+24 h | raisons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR… | live seul (P) ; décalé avec 4XwDKz… | 18:47:49Z / 473852221 (+14 s / +64 sl.) | — | -2778 / -12914 | 473852289 / — | horloge 19:18:04Z | — | -0.000994 | — | — | chaîne de signaux différente |
| 2 | 6CQSpR… | livesim seul ; décalé avec 3cBj5S… | — | 19:34:07Z / 473865135 | -2778 / -12914 | — / 473865139 | — | horloge 20:04:08Z | — | -0.000868 | -0.000868 | chaîne de signaux différente |

Témoin (tirage au now de la comparaison, non comparable au T+24 h) : 2 lignes ; comptes à clé stricte : live seul 1, livesim seul 1. Live : 1 positions (1 fermées), somme nette des fermées -0.000801 SOL. Livesim : 1 positions (1 fermées), somme nette des fermées -0.001312 SOL (descriptif).

| # | pool | présence | entrée L | entrée S | sortie L | sortie S | net L | net S | raison |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR… | live seul | 19:07:03Z / 473857570 | — | horloge 19:37:04Z | — | -0.000801 | — | mécanismes de témoin différents par construction |
| 2 | 6CQSpR… | livesim seul | — | 19:14:16Z / 473859591 | — | horloge 19:44:17Z | — | -0.001312 | mécanismes de témoin différents par construction |

## Conforme à l'entrée, sortie hors protocole (publié à part, non additionné au segment conforme)

Signaux G2-3 : 1 lignes. Comptes à clé stricte (sans appariement décalé) : live seul 1. Lignes appariées « décalées » (seuil figé 3600 s), à part : 0.
Live : 1 positions (1 fermées, 0 ouvertes), somme nette des fermées -0.000755 SOL. Livesim : 0 positions (0 fermées, 0 ouvertes), somme nette des fermées +0.000000 SOL (descriptif).

| # | pool | présence | déclencheur L (latence) | déclencheur S | Δ décl. s / slots | entrée L / S (slot) | sortie L | sortie S | net L | net S | S à T+24 h | raisons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR… | live seul (P) | 19:49:05Z / 473869310 (+28 s / +128 sl.) | — | — | 473869442 / — | horloge 20:19:34Z | — | -0.000755 | — | — | chaîne de signaux différente |

Témoin (tirage au now de la comparaison, non comparable au T+24 h) : 1 lignes ; comptes à clé stricte : livesim seul 1. Live : 0 positions (0 fermées), somme nette des fermées +0.000000 SOL. Livesim : 1 positions (1 fermées), somme nette des fermées -0.000999 SOL (descriptif).

| # | pool | présence | entrée L | entrée S | sortie L | sortie S | net L | net S | raison |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5zk4vh… | livesim seul | — | 19:44:22Z / 473867991 | — | horloge 20:14:23Z | — | -0.000999 | mécanismes de témoin différents par construction |

## Segment hors protocole [20:10:03Z ; now]

Écarts de ce segment : D13 (transaction manquée de GaPTvX, slot 473875242 ; exclusion G-0 à partir de 20:11:03Z) ; D14 (erreurs tolérées).

Signaux G2-3 : 5 lignes. Comptes à clé stricte (sans appariement décalé) : les deux 5. Lignes appariées « décalées » (seuil figé 3600 s), à part : 0.
Live : 5 positions (5 fermées, 0 ouvertes), somme nette des fermées +0.006831 SOL. Livesim : 5 positions (5 fermées, 0 ouvertes), somme nette des fermées +0.007100 SOL (descriptif).

| # | pool | présence | déclencheur L (latence) | déclencheur S | Δ décl. s / slots | entrée L / S (slot) | sortie L | sortie S | net L | net S | S à T+24 h | raisons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5zk4vh… | les deux (P) | 20:44:39Z / 473884853 (+31 s / +143 sl.) | 20:44:39Z / 473884853 | +0 / +0 | 473885000 / 473884857 | TP/SL 20:45:41Z | TP/SL 20:45:41Z | +0.006660 | +0.006929 | +0.006929 | latence du live (ancre à la réception) |
| 2 | 6CQSpR… | les deux (P) | 20:55:52Z / 473887979 (+15 s / +68 sl.) | 20:55:52Z / 473887979 | +0 / +0 | 473888051 / 473887983 | horloge 21:26:08Z | horloge 21:25:53Z | -0.001107 | -0.001107 | -0.001107 | latence du live (ancre à la réception); point de sortie différent, même règle |
| 3 | 6CQSpR… | les deux (P) | 21:56:21Z / 473904870 (+16 s / +73 sl.) | 21:56:21Z / 473904870 | +0 / +0 | 473904947 / 473904874 | horloge 22:26:38Z | horloge 22:26:22Z | -0.001143 | -0.001143 | -0.001143 | latence du live (ancre à la réception); point de sortie différent, même règle |
| 4 | 6CQSpR… | les deux (P) | 22:59:04Z / 473922287 (+23 s / +103 sl.) | 22:59:04Z / 473922287 | +0 / +0 | 473922394 / 473922291 | horloge 23:29:28Z | horloge 23:29:05Z | -0.001015 | -0.001015 | -0.001015 | latence du live (ancre à la réception); point de sortie différent, même règle |
| 5 | 5zk4vh… | les deux (P) | 23:36:07Z / 473932609 (+20 s / +96 sl.) | 23:36:07Z / 473932609 | +0 / +0 | 473932709 / 473932613 | TP/SL 23:38:53Z | TP/SL 23:38:53Z | +0.003436 | +0.003436 | +0.003436 | latence du live (ancre à la réception) |

Témoin (tirage au now de la comparaison, non comparable au T+24 h) : 13 lignes ; comptes à clé stricte : live seul 6, livesim seul 7. Live : 6 positions (6 fermées), somme nette des fermées -0.006251 SOL. Livesim : 7 positions (6 fermées), somme nette des fermées +0.001639 SOL (descriptif).

| # | pool | présence | entrée L | entrée S | sortie L | sortie S | net L | net S | raison |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6CQSpR… | live seul | 20:14:03Z / 473876286 | — | horloge 20:44:04Z | — | -0.001159 | — | mécanismes de témoin différents par construction |
| 2 | 6CQSpR… | livesim seul | — | 20:37:48Z / 473882947 | — | horloge 21:07:49Z | — | -0.000905 | mécanismes de témoin différents par construction |
| 3 | 5zk4vh… | livesim seul | — | 20:45:08Z / 473884988 | — | TP/SL 20:45:41Z | — | +0.006660 | mécanismes de témoin différents par construction |
| 4 | 5zk4vh… | live seul | 20:51:06Z / 473886656 | — | horloge 21:21:07Z | — | -0.001058 | — | mécanismes de témoin différents par construction |
| 5 | 6CQSpR… | live seul | 21:20:07Z / 473894747 | — | horloge 21:50:08Z | — | -0.000599 | — | mécanismes de témoin différents par construction |
| 6 | 6CQSpR… | livesim seul | — | 21:38:45Z / 473899965 | — | horloge 22:08:46Z | — | -0.001263 | mécanismes de témoin différents par construction |
| 7 | 6CQSpR… | live seul | 22:20:06Z / 473911488 | — | horloge 22:50:07Z | — | -0.001373 | — | mécanismes de témoin différents par construction |
| 8 | 6CQSpR… | livesim seul | — | 22:49:36Z / 473919653 | — | horloge 23:19:37Z | — | -0.000983 | mécanismes de témoin différents par construction |
| 9 | 6CQSpR… | live seul | 23:08:56Z / 473925017 | — | horloge 23:38:57Z | — | -0.001043 | — | mécanismes de témoin différents par construction |
| 10 | 5zk4vh… | livesim seul | — | 23:38:23Z / 473933238 | — | horloge 00:08:24Z | — | -0.001091 | mécanismes de témoin différents par construction |
| 11 | 5zk4vh… | live seul | 23:40:26Z / 473933812 | — | horloge 00:10:27Z | — | -0.001018 | — | mécanismes de témoin différents par construction |
| 12 | 6CQSpR… | livesim seul | — | 00:16:38Z / 473943896 | — | horloge 00:46:39Z | — | -0.000780 | mécanismes de témoin différents par construction |
| 13 | 6CQSpR… | livesim seul | — | 01:17:41Z / 473960932 | — | ouverte | — | NON MESURÉ | mécanismes de témoin différents par construction |

## Annexe : transactions présentes d'un côté seulement, [départ live ; now]

| pool | côté | signature | slot | heure | segment | D13 |
|---|---|---|---|---|---|---|
| GaPTvX… | absente du live | 5fP94raR8gL7… | 473875242 | 20:10:19Z | hors_protocole | oui |

- GaPTvX… : 922 transactions live et 923 livesim dans la fenêtre ; 0 transactions live avant le départ.
- 6CQSpR… : 101 transactions live et 101 livesim dans la fenêtre ; 0 transactions live avant le départ.
- 5zk4vh… : 131 transactions live et 131 livesim dans la fenêtre ; 0 transactions live avant le départ.

Interruptions du live : GAP [— ; —], [— ; —], [— ; —] ; reprises [20:29:33Z ; 20:30:37Z], [22:20:06Z ; 22:20:57Z], [00:10:26Z ; 00:12:01Z].

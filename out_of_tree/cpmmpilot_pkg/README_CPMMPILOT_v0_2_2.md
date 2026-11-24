# cpmmpilot 0.2.2 — espacement du transport après le 429 (R03), HORS LIGNE

Cette version répond à la note R02 41c20a16 (D3). Elle a été écrite et testée hors ligne, sans aucun appel réseau.

## Contexte

Le temps 1 de U-2 a été lancé le 24/11 à 09:23:16Z avec la version 0.2.1. Il s'est arrêté en STOP sur un HTTP 429 après 155 lots `getMultipleAccounts` envoyés sans aucun espacement. 287 crédits ont été consommés et aucune liste L n'a été produite. Les preuves sont dans `out_of_tree/cpmmpilot_run/TIME1_20261124T092316Z/`.

## Seul changement de logique (`rpc.LiveRpc`)

`MIN_INTERVAL_S = 0.2` : deux envois successifs ne sont jamais séparés de moins de 0,2 s, soit au plus 5 requêtes par seconde. C'est dans les limites de l'offre Free, qui autorise 10 req/s et 5 gPA/s.
- L'horloge (`clock`) et l'attente (`sleep`) sont injectables pour les tests. Par défaut, ce sont `time.monotonic` et `time.sleep`.
- Un appelant déjà lent n'est pas ralenti davantage.
- Un 429 reste un STOP (`rate_limited_429`). Il n'y a ni nouvel essai ni repli : la requête est débitée une fois et envoyée une fois (test).

Le reste du paquet est INCHANGÉ par rapport à 0.2.1 (PASS R02 746f7d94).

## Vérifications (hors ligne, `unshare -rn`, g1ind 0.6.1)

- **Tests : 38 sur 38.** Deux sont nouveaux :
  - l'espacement mesuré sur une horloge simulée : 5 attentes de 0,2 s, aucune attente au premier envoi ni après un appelant lent ;
  - le 429, qui provoque un STOP sans nouvel essai, aussi bien dans le `Client` seul que dans `u2.run_list`, sans que LIST_L soit écrit.
- **Mutants : 55 sur 55 tués** (`MUTATIONS_cpmmpilot_v0_2_2.json`). Trois sont nouveaux : `spacing_removed`, `spacing_0_1`, `last_sent_not_updated`.
- **Répétition :** journal bc57a0f8….

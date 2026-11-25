# livepaper 0.1.3 — 0.1.2 + horodatage des appels RPC, durée de collecte, seuil de GAP « ≥ »

RUGGER 01, 25/11/2026. Feu vert R04 (20:33Z), priorité basse, après la pause de 60 s observée par R03
(20:10:03 → 20:11:03Z, traitement 29 ms) que la 0.1.2 ne permet pas d'expliquer.
**Cette version n'est ni lancée ni substituée à la 0.1.2 en cours.** Audit R02 avant tout usage, et seulement pour
un test futur.

## Les trois changements
1. **`TimedClient`** (`source.py`) enveloppe le Client gelé `cpmmpilot.rpc.Client`, qui ne change pas.
   - Chaque appel écrit une ligne dans `<calls>.timing.jsonl` : méthode, sha des paramètres, départ et fin (horloge
     murale), durée (horloge monotone, ms), `ok`, `error`.
   - Les échecs sont aussi écrits : `RpcError`, `BudgetExhausted`. L'exception est relancée telle quelle.
   - `error` = type + 80 premiers caractères du message ; jamais l'endpoint.
   - Le journal d'appels gelé garde son format, octet pour octet.
   - `run` et `collect-gsfa` utilisent `TimedClient`.
2. **`fetch_ms` dans STEP** : durée de `source.fetch()` (horloge monotone de l'hôte).
   - Champ VOLATILE, comme `wall`, `mono_ns` et `processing_ms` : publié, exclu de l'identité de rejeu.
   - Un journal 0.1.2 ne peut pas être repris par la 0.1.3 : le START porte `schema`, qui diffère, et le rejeu
     refuse un enregistrement différent. Un run = une version. (Lecture du code ; pas de test dédié.)
3. **Seuil de GAP** : une pause de `2 × poll_s` **ou plus** est un GAP (0.1.2 : strictement plus).
   - Exemple : poll_s = 30 s, pause de 60,0 s → GAP ; 59,9 s → pas de GAP.

`SCHEMA = 'livepaper-v0.1.3'`. Le reste est livepaper 0.1.2 (459f9c7 + 1a626c8), y compris
`AUTHORIZED_TEXT_SHA256`, `check_imports` et le grand livre de crédits (plafond 25 000, arrêt 24 500).
Aucun crédit supplémentaire : le wrapper n'ajoute aucun appel.

## Tests (cas limites écrits avant les mutants)
- `test_every_call_is_timed_even_when_it_fails` : une ligne pour un succès, une pour `RpcError`, une pour
  `BudgetExhausted` ; durées sur l'horloge de test ; journal gelé inchangé.
- `test_the_fetch_time_is_in_step_and_a_pause_of_exactly_two_polls_is_a_gap` : `fetch_ms` exact sur l'horloge de test ;
  frontière 60,0 s / 59,9 s ; pas de GAP sans pas précédent.
- `test_commands` : fichiers `.timing.jsonl` pour `collect-gsfa` et `run` ; `fetch_ms` flottant dans STEP.
- 28/28 avec livesim 0.3.1 et avec livesim 0.3.2.

## Mutants
84 (76 de la 0.1.2 + 8 nouveaux : `timing_ok_always`, `timing_duration_seconds`, `timing_swallows_errors`,
`fetch_ms_dropped`, `gap_strict`, `fetch_ms_not_volatile`, `run_not_timed`, `collect_not_timed`).
Résultat : 84/84 détectés, avec livesim 0.3.2 + cpmmrecon 0.1 (`MUTATIONS_livepaper_v0_1_3.json`).

## Limite connue
`fetch_ms` et `timing.jsonl` mesurent le temps vu par l'hôte. Ils ne disent pas si le délai vient du réseau, du
fournisseur ou d'une suspension du conteneur. Une suspension se verrait comme un écart entre l'horloge murale et la
somme des durées mesurées : NON MESURÉ tant qu'aucun run 0.1.3 n'existe.

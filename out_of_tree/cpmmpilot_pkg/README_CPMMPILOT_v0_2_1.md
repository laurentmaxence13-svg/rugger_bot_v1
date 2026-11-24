# cpmmpilot 0.2.1 — autorisation B+C inscrite, U-2 en deux temps (R03)

Cette version est écrite HORS LIGNE et n'a fait aucun appel réseau. Elle répond aux messages de R02 (07:01Z, 07:02Z) et de R04 (07:01Z, 07:09Z).

## Autorisation

**Texte.** Le texte B+C du propriétaire (v1.3) est l'événement b1f263a6 de la session R04, écrit le 24/11 à 07:00:22Z depuis iOS. R02 l'a vérifié à la source et l'a déclaré VALIDE.

**Fichier canonique.** `AUTORISATION_B_C_v1_3.txt` contient les octets UTF-8 exacts de `message.content`, sans saut de ligne final :
- taille : 2 175 octets ;
- sha256 : e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1.

R03 a recalculé ce sha de son côté, et il est égal à celui de R02.

**Code.** `rpc.AUTHORIZED_TEXT_SHA256 = frozenset({e25389f0…})`, et AUCUN autre sha. Un test vérifie le fichier, sa taille, l'absence de saut de ligne final et les clauses : plafonds 5 000 / 50 000, arrêt à 49 000, programme, « hachée et ancrée par R02 ; puis ».

## U-2 en deux temps

Le texte B dit que L est « hachée et ancrée par R02 ; puis » vient la permutation. U-2 se fait donc en deux appels distincts.

- **Temps 1, `u2.run_list`.**
  - Appels : `getSlot`, `getProgramAccounts` (AmmConfig, puis pools), coffres WSOL par `getMultipleAccounts`.
  - Écrit `LIST_L.json` : liste, sha_L, t0, comptes, configs.
  - Retourne `LIST_L_AWAITS_R02_ANCHOR`, puis ARRÊT.
  - AUCUN `getTransactionsForAddress` n'est envoyé ; un test le vérifie avec un espion.
  - Si L contient moins de 20 pools : INCONCLUSIF.
- **Temps 2, `u2.run_qualify(anchored_sha_l)`, après l'ancrage de sha_L par R02.**
  - Relit `LIST_L.json` et REHACHE la liste AVANT tout appel.
  - Refuse (`list_l_not_anchored`) si le sha diffère du sha ancré, ou si le fichier a été modifié.
  - Ensuite seulement : permutation `random.Random(int(sha_L[:8], 16))`, puis GTFA asc limit 1, jusqu'à 24 pools valides.
  - Les deux temps partagent le même registre de crédits, qui est repris (test).
- **`u2.run`** enchaîne les deux temps. Il ne sert qu'à la répétition et aux tests, où le sha de la répétition tient lieu d'ancrage.

## Vérifications

Toutes sont faites hors ligne (`unshare -rn`), avec g1ind 0.6.1 f31269e :
- 36 tests sur 36 passent ;
- 52 mutants sur 52 sont tués (`MUTATIONS_cpmmpilot_v0_2_1.json`). Nouveaux : `release_authorizes_another_sha`, `u2_anchor_not_checked`, `u2_list_not_rehashed`, `u2_first_time_continues` ;
- répétition synthétique : journal bd818e84…

## Environnement (noms seulement, aucune valeur lue)

- Hôte RPC autorisé : `beta.helius-rpc.com`.
- Secret réseau injecté par le proxy dans l'en-tête `X-Api-Key`.
- Endpoint prévu : `https://beta.helius-rpc.com/`. R02 doit confirmer que GTFA y est servie ; sinon, refus = ARRÊT sans repli.

## Reste AVANT tout appel réel

1. PASS R02 de cette 0.2.1.
2. Relevé de quota du propriétaire : disponible ≥ 7 500 avant B, ≥ 75 000 avant C, autoscaling OFF.
3. Si le contrôle d'accès de R03 refuse le premier appel : arrêt, et le propriétaire recolle le texte dans la session R03.

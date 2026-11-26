# livepaper 0.1.4 — 0.1.3 + corrections de D13, D14 et D15 (version candidate, non lancée)

RUGGER 01, 26/11/2026. Défauts établis sur le snapshot ancré 1e86638 :
- **D13**, diagnostic R01 confirmé par R02 et R04 : transaction 5fP9… de GaPTvX perdue, puis exclusion G-0 définitive.
- **D14**, R02 01:31Z : la 0.1.2 tolère des RpcError sans STOP ni journalisation, ce que le texte signé interdit.
- **D15**, R02 et R04 01:34–01:36Z : la liste des méthodes appelées doit être exhaustive et publiée. Le texte signé ne
  nomme pas `getSlot`.
Le test 0.1.2 a été **arrêté par R02**. Cette version n'est lancée sans nouvelle décision du propriétaire, ni pour un
test futur avant l'audit de R02. La 0.1.2 n'est pas modifiée.

## Mécanisme de D13 (lecture du code 0.1.2 et des données ancrées, aucun appel)
1. Pas 181 : `GSFA(GaPTvX, until=n6EY…)` renvoie 5fP9… ; `getTransaction(5fP9)` réussit (C.jsonl, lignes 1026–1027).
   `_gsfa` fait avancer `last_sig` et `seen` **avant** la remise du lot au moteur.
2. La requête suivante, `GSFA(6CQSpR)`, est débitée mais échoue : 4 323 crédits pour 4 322 lignes, seul trou après la
   ligne 1027. `fetch()` lève l'exception et le lot est perdu.
3. Le Runner dort 30 s et relance ; `GSFA(GaPTvX, until=5fP9)` (ligne 1028) ne rend plus que 62zK.
4. La chaîne des réserves casse : G-0 refuse GaPTvX à 20:11:03Z, et ce refus est définitif.
5. Le trou de 60 s (D12) est le même événement. Le type d'erreur est NON MESURÉ en 0.1.2.
Vérification reproductible : `livesim_runs/BILAN_T6H_LIVEPAPER_20261126/d13_verify.py` (commit 9d6f8b6).

## Changements (liste de R02 01:31Z, points a à d)
- (c) **`Source.fetch` est « tout ou rien »** (D13).
  - `last_sig`, `seen`, `rank` et `since` sont sauvegardés, puis restaurés sur toute exception.
  - La relance repart de la dernière signature effectivement remise au moteur.
- (a) **STOP au premier incident** (D14) : une `RpcError` ou `SourceError` arrête le processus. Il n'y a plus de
  sommeil suivi d'une relance. Seule tolérance, celle de livesim_collect (`activity_l2.RetryOnceClient`) :
  - `RetryOnce` relit **une fois** le même appel, uniquement sur `response_truncated` ;
  - la relecture est débitée (le Client débite avant l'envoi) et journalisée dans le journal d'appels (`retry=True`) ;
  - une deuxième troncature est un incident. `RETRY_ON_TRUNCATED = 1`.
- (b) **Enregistrement `ERROR`** avant le STOP : type, message expurgé (caractères `[A-Za-z0-9_:.-]`, 80 au plus) et
  heure murale.
  - `ERROR` et `STOP` sont écrits par le Runner ; le rejeu les saute (`RUNNER_KINDS`).
  - Raison du STOP : `incident:<type>`.
- (d) Horodatage de la 0.1.3 (`TimedClient`), conservé : l'appel en échec y est écrit avec son type
  (`RpcError:provider_error` dans le test qui reproduit D13). Ordre : `RetryOnce(TimedClient(Client))`, donc chaque
  tentative est horodatée.
- (D13, second filet, R04 01:29Z et 01:34Z) **Rattrapage borné avant toute exclusion G-0**, en mode `gsfa_rank`
  seulement.
  - Avant chaque pas, `Engine.breaks_ahead` calcule, sans aucun effet (ni enregistrement, ni page, ni état), les pools
    dont G-0 deviendrait `reserves_chain_broken` avec ce lot.
  - Pour chacun de ces pools : 1 `getSignaturesForAddress` (les 100 plus récentes, sans curseur) et au plus 10
    `getTransaction`, soit 11 crédits au plus.
  - Sont rattrapées les signatures jamais remises qui ne sont ni après le slot de réception ni plus récentes que le
    dernier slot remis.
  - Le résultat est toujours journalisé : `CATCHUP`, avec `outcome`, `signatures` et `receipt_slot`.
  - Les transactions trouvées rejoignent le lot (`RECEIVED` et pages, `index_source = gsfa_rank_catchup`). Le rejeu
    les re-dérive et saute l'enregistrement `CATCHUP`.
  - Refus, sans rien ajouter, quand : mode `gtfa` ; rien de manquant ; plus de 10 manquantes ; une manquante tombe dans
    un slot qui contient déjà des transactions remises (rang incertain) ; une transaction non servie. Le refus G-0 est
    alors maintenu.
  - Une erreur RPC pendant le rattrapage est un incident (ERROR puis STOP), et l'état de la source est restauré.
- (e, D15) **Liste exhaustive des méthodes** : `METHODS_livepaper_v0_1_4.txt`, dans le MANIFEST, une méthode par ligne,
  triée : `getSignaturesForAddress`, `getSlot`, `getTransaction`, `getTransactionsForAddress`.
  - `getSlot` est gardé, selon la voie recommandée par R02. Cette liste suppose que le futur texte du propriétaire le
    nomme ; la décision lui revient.
  - Trois contrôles :
    - `METHODS` est égal à la liste publiée ;
    - un balayage du code par l'AST : toute méthode littérale passée à `.call`, `.request` ou `.charge` est dans la
      liste, et chaque méthode de la liste est appelée ;
    - une marche de bout en bout dans les deux modes, rattrapage compris, n'appelle que des méthodes listées et les
      appelle toutes.
  - Le grand livre et le transport refusent toute autre méthode.
- Chiffrage des crédits sur 24 h, méthode par méthode : `CREDITS_24H_livepaper_v0_1_4.md`. En voie (i-a), 3 pools :
  de 14 856 à 16 752 crédits par 24 h, central 15 641.
- Le test demandé par R02 le 25/11 à 21:07Z est ajouté : un journal 0.1.2 (schéma `livepaper-v0.1.1`) ou 0.1.3 n'est
  pas repris (`replay_differs_at:0`).
- `SCHEMA = 'livepaper-v0.1.4'`. `fill.py` et `ordercheck.py` sont identiques à la 0.1.2.

## Tests (cas limites écrits avant les mutants)
- D13, rouge sur la 0.1.3 et vert sur la 0.1.4 (vérifié) :
  - 4 cas d'échec au milieu d'un fetch (`gsfa_rank` et `gtfa`, sur l'appel du 2e pool ou sur `getSlot`) ;
  - pour chacun : la précondition (le 1er pool a bien été lu), l'état restauré, aucune transaction perdue ni doublée.
- D13 + D14 en marche réelle : un sondage en échec donne ERROR puis STOP `incident:RpcError`. Le rejeu reprend depuis
  le journal, sans perte, sans `reserves_chain_broken`, et le rejeu reste identique.
- Une erreur unique donne STOP immédiatement : `network_error`, `provider_error`, et `SourceError` (`slot_not_an_integer`).
- Relecture unique :
  - 1 troncature : relue, débitée deux fois, journalisée ;
  - 2 troncatures : incident ;
  - `retry=0` : incident ;
  - autre erreur : pas de relecture ;
  - ligne de commande `run` avec un `getSlot` tronqué : la marche continue.
- Expurgation du message.
- Rattrapage :
  - une transaction que les sondages ne listent jamais : sans rattrapage, le pool est exclu (précondition vérifiée) ;
    avec, un seul `CATCHUP` « found », un seul GSFA de rattrapage, G-0 ne refuse jamais, et le rejeu est identique ;
  - refus pour rang incertain (refus G-0 maintenu), pour plus de 10 manquantes, en mode `gtfa` (aucun appel) ;
  - échec RPC pendant le rattrapage : incident et état restauré ; frontière du slot de réception (après : jamais ;
    égal : oui) ;
  - deux transactions manquées, la seconde en échec RPC ou non servie : la première est annulée elle aussi.
    Ce test a été ajouté après la survie du mutant `catchup_not_restored` au premier passage, à 111/112.
- D15 : liste publiée, balayage AST, marche de bout en bout dans les deux modes.
- Tests : 43/43, avec livesim 0.3.1 et avec 0.3.2 (`-W error`).
- Mutants : 113/113 détectés (`MUTATIONS_livepaper_v0_1_4.json`).

## Limites et points à décider
- Le rattrapage ne voit que les 100 signatures les plus récentes. Une transaction manquée plus ancienne n'est pas
  retrouvée et le refus G-0 est maintenu. Ce choix borne le coût.
- La cassure `reserves_chain_broken` peut aussi venir d'un dépôt direct dans la vault, pas d'une transaction manquée.
  Le rattrapage répond alors `nothing_found` et le refus est maintenu. Une seule tentative par cassure, car un pool déjà
  refusé pour cette raison n'est plus sondé par `breaks_ahead`.
- `processing_ms` d'un STEP inclut la durée des appels de rattrapage quand un `CATCHUP` le précède.
- lpbilan 0.1 ne liste pas encore les enregistrements `ERROR` et `CATCHUP` d'un journal 0.1.4 (il faudrait une 0.1.1).
- `getSlot` dans la liste : décision du propriétaire, à inscrire dans un nouveau texte. Toute reprise exige une
  nouvelle décision du propriétaire.

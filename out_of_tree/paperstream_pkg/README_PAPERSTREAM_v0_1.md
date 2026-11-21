# paperstream 0.1 — moteur PAPER EN FLUX du MASTER gelé, hors ligne (plan v0.1 accepté par R02 sous 7 conditions)

## Principe

**HISTORICAL_REPLAY seulement.**
- Les événements LaunchLab enregistrés sont poussés UN PAR UN, dans l'ordre du temps.
- Aucune requête réseau, aucune clé, aucune signature.
- Aucune conclusion économique : l'outil reproduit un rejeu connu. Ce n'est pas un essai, et N reste à 168.

**Ce qui est écrit : `StreamTrade`.**
- C'est une copie, en mode « poussé », de la machine d'états du `bot.market.replay.replay` gelé : décision, atterrissage
  après la latence, détention, déclencheur de sortie, sortie d'horloge, migration, marquage final.
- La stratégie ne reçoit que les événements déjà poussés, sous forme de tuple, comme le rejeu.
- Un événement hors de l'ordre du temps, ou poussé après la fin, est REFUSÉ.

**Ce qui n'est pas changé : `streaming_engine()`.** Ce gestionnaire de contexte remplace SEULEMENT le moteur de trade
du `hrr.replay_pool` gelé, puis le restaure à la sortie. Restent ceux du code gelé :
- le bras MASTER (`ResearchArm`) et l'observateur ;
- les coûts et les lignes de trade ;
- la sortie d'horloge et la migration ;
- les paramètres L1 de W1 (`w1_run.l1_params()`, latence de 4 slots, horloge de 30 s).

## Usage

```
python -B -m paperstream.engine reference --pools <pack> --manifest-sha256 <ancré> --out <DOSSIER>   # référence EN LOT gelée
python -B -m paperstream.engine run --pools <pack> --manifest-sha256 <ancré> --reference <REFERENCE.json> \
       --reference-sha256 <ancré> --out <DOSSIER>                                                    # flux ; 0 si identique
```

## Conditions de R02

1. **Hors ligne.**
   - Un test fait échouer toute connexion.
   - Aucun module d'envoi ni de signature de `bot.live` n'est importé (testé).
   - Le code ne contient ni requests, ni urllib, ni websocket, ni http, ni signature, ni clé.
   - Exécution sous `unshare -rn`.
2. **Données.** Le pack gelé seulement à ce stade. P0 visible viendra après le PASS de R02. W1 seulement sur un PASS
   distinct. Jamais le holdout 9f19ccac.
3. **Identité.** La référence est le rejeu EN LOT gelé, sur la même entrée. Son sha est ancré AVANT le run, et `run`
   refuse une autre référence. L'identité est octet pour octet (JSON canonique), sans tolérance.
4. **Libellés.**
   - La catégorie est HISTORICAL_REPLAY.
   - Ni « genuine », ni « MASTER_CYCLE », ni LIVE dans la sortie (testé).
5. **Seuils.** 50 cycles et 20 groupes sont lus dans `bot.master_decision.POLICY`, testés égaux à 50 et 20. Le code gelé
   refuse 49. Ces cycles ne comptent JAMAIS pour les seuils.
6. **Aucune conclusion économique.** `trials_added = 0`.
7. **Ni flux réel ni Render.** Ils ne sont pas dans ce paquet.

## Preuves

**Tests : 16 réussis.**
- `StreamTrade` = `replay` gelé, à l'identique (TradeResult complet), sur les vraies chronologies du pack, pour 6
  scénarios : entrées précoces et tardives, sortie déclenchée, sortie d'horloge, position ouverte à la fin, latence 0
  et 2 à 4.
- Sur le pack, avec le MASTER RÉEL : enregistrements en flux = en lot, octet pour octet.
  - **Limite déclarée :** sur ces 3 pools, le MASTER gelé reste en WAIT. Cette identité est donc une identité de WAIT.
  - D'où un test à ENTRÉE FORCÉE dans l'observateur, à l'identique en lot et en flux. Il couvre le `ResearchArm` gelé :
    stop loss, take profit, sortie d'horloge à 30 s. Les enregistrements sont identiques, et le journal se réconcilie
    (jusqu'à 6 cycles, résidu nul). Un journal falsifié est refusé.
- Le moteur gelé est restauré après le bloc.

**Défauts volontaires : 15 sur 15 détectés** (`MUTATIONS_paperstream_v0_1.json`). Un 16ᵉ, `rate_reads_future`, est
ÉQUIVALENT, et donc retiré : à la décision, le moteur ne détient que les événements poussés. C'est la causalité par
construction.

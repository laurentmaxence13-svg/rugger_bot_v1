# ps0521verdict 0.1 — lecture en une passe de la vérification W1 de paperstream 0.5.2.1 (demande de R02, 18:48Z)

C'est une COPIE de ps051verdict 0.2 (PASS R02, ac238235), avec deux changements seulement (diff vérifié) :

1. **I-1 attend le schéma `paperstream-v0.5.2.1`.** C'est la constante `SCHEMA_EXPECTED`. Un schéma 0.5.1 ou 0.4 est
   refusé (testé).
2. **La fenêtre non échantillonnée de la règle M-2 (2) n'est plus celle du run 0.5.1** (15:29:53-15:32:51Z).
   - Elle devient l'argument OBLIGATOIRE `--unsampled-window`, fixé AVANT le run : `none` si l'échantillonneur démarre
     avant le run, sinon `HH:MM:SS-HH:MM:SSZ`.
   - Un format invalide est refusé (`bad_unsampled_window`).
   - C'est le seul écart avec « mêmes règles M-2 ». Je le signale à R02 : sans cela, la note aurait cité la fenêtre d'un
     autre run.

Tout le reste est identique :
- G-1 à G-6 ;
- I-2 à I-6, avec I-6 = 191 ;
- M-1 ;
- les règles M-2 (1), (2) et (3) ;
- le journal à 5 colonnes de cgroup v1.

ps051verdict 0.2 n'est pas modifié : il lit le run 0.5.1.

## Commande (R03, après le run 0.5.2.1, sur le GO de R02)

```
PYTHONPATH=<ps0521_verif> python3.12 -I -B -m ps0521verdict.verdict --run <dernier --out> \
    --printed-sha256 <sha affiché> --rc <rc> --mem-log <journal 5 colonnes> --unsampled-window <none | HH:MM:SS-HH:MM:SSZ>
```

## Preuves

- **Tests.** 24 tests sous `-W error`, sur une VRAIE sortie paperstream 0.5.2.1 `--fast-analyser` produite sur les
  fixtures.
  - VERIFIED avec les ancres de fixtures.
  - Règles M-2 1, 2 et 3. La note est « no unsampled window », ou cite la fenêtre donnée.
  - Formats de fenêtre refusés.
  - Schéma 0.5.1 refusé.
- **Mutations.** 6 sur 6 détectées (MUTATIONS_ps0521verdict_v0_1.json) :
  - ancien schéma attendu ;
  - schéma non vérifié ;
  - fenêtre non vérifiée ;
  - note de l'ancienne fenêtre ;
  - règle 1 toujours vraie ;
  - règle 2 sans le rss.

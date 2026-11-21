# paperstream 0.5.1 — conditions du PASS conditionnel de R02 sur la 0.5 (52115d9)

**BROUILLON.** La 0.4 reste la SEULE version du run W1 en cours et de son contrôle final.

## Ce que la 0.5.1 ajoute

1. **Mémoire du cache (condition 1).**
   - Avec `--fast-analyser`, la garde mémoire de dayj (étape trials) ajoute une marge :
     workers × la plus grosse archive gz du pack × `MEMO_BYTES_PER_GZ_BYTE`.
   - `MEMO_BYTES_PER_GZ_BYTE` vaut 8,0. Sur les fixtures, on a mesuré de 4,75 à 7,1.
   - Exemple sur W1, avec 4 workers et la plus grosse archive (13,8 Mo) : environ 420 Mo, ajoutés à la projection, avec
     la marge ×1,5.
   - La valeur réelle se mesure avec `paperstream.memo_probe`, hors ligne et en lecture seule : aucun rejeu, aucune
     décision, aucun résultat.

     ```
     python -B -m paperstream.memo_probe --archive <plus grosse archive W1> --sha256 <son sha du MANIFEST>
     ```

     La sortie ne contient que des tailles et la RSS : `dumps_per_gz_byte`, `rss_delta_mb`, `hwm_mb`. R02 ancre la
     valeur, puis la constante est mise à jour.
   - Le dépassement est refusé avant toute écriture (testé), sauf avec `--memory-override`, qui exige l'accord écrit de
     R02.
2. **`--verify-fast` (pour la condition 3).**
   - Il exige `--fast-analyser`.
   - Chaque valeur servie par le cache est recalculée, et le premier écart lève une erreur.
   - Le drapeau est consigné dans la sortie.
   - Usage prévu : un run sur P0 visible (aca7de08), sans aucun écart, par R03, sur le GO de R02.
3. **`--perf-counters` (compteur technique demandé).** Pour chaque pool, il compte :
   - les évaluations complètes (appels à `build_features`) ;
   - les attentes courtes ;
   - les secondes d'horloge et de CPU.

   Le tableau `PERF_COUNTERS.json` est trié par rang de taille gz. Il ne contient AUCUN identifiant de pool, ni aucun
   résultat, et son sha est consigné. Les tests vérifient trois points :
   - le bundle est identique avec et sans compteurs, avec 1 et 2 workers ;
   - le total des évaluations vaut le nombre de décisions ;
   - aucun pool ni mot interdit n'apparaît.

## Ce que la 0.5.1 ne fait pas

- Aucun usage de `--fast-analyser` avant les deux conditions suivantes :
  - **condition 2** : une identité préalable sur W1 contre les 3 sha L1 ancrés (fichier 3409bf9d, JSON 9eb43426,
    champ c7556f14). C'est un nouveau rejeu, qui ne se fait qu'après le contrôle final de la 0.4, sur le GO de R02,
    puis passe par psverdict ;
  - **condition 3** : le run `--verify-fast` sur P0 visible.
- **N reste inchangé (condition 4).** Aucun essai n'est ajouté.

## Preuves

- 61 tests sous `-W error` : les 42 de la 0.4 et 19 nouveaux.
- Mutations : 19 sur 19 détectées sur les parties nouvelles des versions 0.5 et 0.5.1 (MUTATIONS_paperstream_v05_1.json). Le run complet en détectait 16 ; 2 tests ont été ajoutés, puis les 3 mutants relancés sur les tests finaux sont détectés.

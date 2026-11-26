# Préparation de la collecte pilote G2-3 du 06/12 (R03, 26/11 13:35Z) — hors ligne, 0 crédit

## 1. Essai à blanc (unshare -rn, extraction du commit 7ce025c dans un worktree séparé, supprimé ensuite)
- Lanceur `launch_g23.sh` 70d503a0. Seuls les chemins sont réécrits vers le worktree, la garde de date est neutralisée et HTTPS_PROXY est retiré, dans une copie.
- Tous les contrôles d'intégrité passent :
  - MANIFEST 0.2.8.1 ba38eba3 : 0 écart ;
  - driver bf62d082, activity_l2 9b2c0487, U2 3ca0260a, texte 3d6999ec ;
  - pythonpath 3cfa5e0d, cpmmcost v0.3 a0bd2adb (0 écart), arbre cpmmx 9e64445e ;
  - OUT inexistant.
- Le driver est importé et s'exécute. Il refuse de lui-même avec `window_not_closed`, rc 1, sans aucun appel. Aucun dossier de sortie n'est créé.
- Commande réelle du 06/12 : `git checkout --detach 7ce025c` dans /home/user/rugger_bot_v1 (arbre propre), puis `bash out_of_tree/cpmmpilot_run/launch_g23.sh` en arrière-plan suivi (timeout 7 200 000). Ensuite, retour sur la branche et commit des sorties.

## 2. Chiffrage, sur la base des pages pré-T0 d'A2r (7 j), extrapolées à 12 j ; 1 seule méthode, GTFA à 10 crédits par page
| Pool | Pages en 7 j | Estimation sur 12 j | Crédits |
|---|---|---|---|
| G8kgi7 | 1 055 | 1 809 | 18 090 |
| AEZjoU | 141 | 242 | 2 420 |
| GdxFyc | 35 | 60 | 600 |
| Gms3Ma | 10 | 18 | 180 |
| **Total** | 1 241 | 2 129 | **≈ 21 290** |

- Plafond : arrêt dur à 32 340, soit une marge de ×1,52.
- Avec une activité ×1,25, le coût passe à ≈ 26 600 ; avec ×1,5, à ≈ 31 900, au ras du plafond.
- G8kgi7 pèse 85 % du coût.
- Le niveau d'activité réel de la fenêtre est inconnu : sa lecture est interdite avant la clôture.

## 3. Points de défaillance et parades
| Point | Risque | Parade | Testé ? |
|---|---|---|---|
| Réponse tronquée | Perte d'une page | Une seule relecture, crédit compté (RetryOnceClient). Une seconde troncature donne un STOP et le partiel est publié | Oui : tests du driver, mutants retry_* |
| 429 / proxy / réseau | Arrêt | STOP immédiat sans repli, conforme au texte. Le partiel est publié | Oui : tests 429 et OSError |
| Plafond | Arrêt en cours de route | Arrêt dur à 32 340, puis partiel publié. Marge ×1,52 | Oui : test_cap_reached |
| Durée > 2 h | Processus tué | Durée estimée de 9 à 26 min (0,25 à 0,72 s par appel mesurés sur livesim et A2r), très en dessous de 2 h | Mesuré |
| Redémarrage du conteneur | Processus perdu | Pages et STATE conservés. Le driver refuse de relancer sur un OUT existant : il faut une décision de R02 et du propriétaire | Garde out_exists testée |
| Arbre de code | INTEGRITY_FAIL | Extraction de 7ce025c (D-décision R02 09:48Z), vérifiée en blanc ici | Oui (ce document) |
| Disque | STOP disk_below_minimum | 5,7 Go libres pour un seuil de 2 Gio. Pages estimées à ≈ 0,4 Go | Mesuré |
| Réveil | Oubli | send_later trig_01NjFRjNxU296Kgbnn3G4Hg3 à 10:31Z, procédure incluse | Programmé |
| Texte | Refus du classifieur | Texte G2-3 3d6999ec écrit par le propriétaire dans cette session | — |

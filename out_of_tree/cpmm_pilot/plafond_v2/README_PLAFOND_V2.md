# Plafond v2 de la collecte G2-3 — code PROJET (R01, 26/11/2026)

Plan de R02 (e886578c, 26/11 13:48Z), points 1 à 5. Décision de R04 (13:54Z) : R01 est le seul auteur ; R03 relit la
partie opérationnelle (chemins, commande, dossier) et refait l'essai à blanc ; R02 audite par diff contre 7ce025c.

**Rien n'est gelé ni exécutable.** L'empreinte de l'additif du propriétaire est EN ATTENTE à trois endroits :
`rpc.ADDENDUM_TEXT_SHA256 = None`, `g23_collect_v0_2.ADDENDUM_TEXT_SHA256 = None` et `ADD_SHA=PENDING` dans le lanceur.
Tant qu'elle n'est pas inscrite, le driver refuse avant tout appel et le lanceur sort en INTEGRITY_FAIL. Le fichier
canonique `AUTORISATION_G23_ADDENDUM.txt` sera créé par R03 depuis le message signé, après la vérification de R02 à la
source.

| point | fichier | changement |
|---|---|---|
| 1 | `cpmmpilot0282_pkg/` (copie de 7ce025c) | `budget.G23_CAP` 32 340 → 88 200 ; `rpc` : l'additif s'ajoute à `AUTHORIZED_TEXT_SHA256`, 3d6999ec reste, `NOT_COVERING` inchangé |
| 2 | `cpmmpilot_run/g23_collect_v0_2.py` (nouveau ; bf62d082 n'est pas touché) | CAP 88 200 ; deux fichiers exigés et vérifiés par sha, `--authorization` (l'additif, passé à LiveRpc) et `--base-text` (3d6999ec) ; les deux sha sont écrits dans G23_COLLECT_RESULT (schéma g23-collect-v2) |
| 3 | `cpmmpilot_run/launch_g23_v4.sh`, `cpmmpilot_run/g23_complete.py` | mêmes contrôles que 70d503a0, avec les nouveaux sha (MANIFEST 0.2.8.2, driver, g23_complete, les deux textes) ; même garde de date ; dernière ligne `COMPLETE=true` ou `false` (informatif) |
| 4 | tests et mutants | cpmmpilot : 56 tests + 1 échec volontaire (en attente) ; driver : 30/30 ; mutants : 18/18, plus 1 équivalent documenté |
| 5 | `ERRATUM_FICHES_G23_v0_6_N1_v0_7_PLAFOND_V2.md` | texte de l'erratum ; R02 l'ancre AVANT toute lecture de la fenêtre |

La publication d'inscription changera seulement les trois constantes EN ATTENTE et la ligne PENDING_TEST, et ajoutera
le fichier canonique de l'additif.

Fichiers copiés à l'identique depuis 7ce025c, pour que les tests s'exécutent :
- activity_l2.py 9b2c0487 ;
- U2.json 3ca0260a ;
- AUTORISATION_G23.txt 3d6999ec ;
- AUTORISATION_T1_T2.txt et AUTORISATION_T2_BIS.txt.

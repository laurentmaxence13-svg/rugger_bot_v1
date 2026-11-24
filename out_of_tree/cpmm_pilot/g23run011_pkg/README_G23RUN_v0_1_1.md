# g23run 0.1.1 — confirmation C-169 corrigée (audit R02 de la 0.1)

RUGGER 01, 24/11/2026.
- Audit R02 de la 0.1 : PHASE PILOTE PASS et ancrée (registre 4df09aff, 2026-11-24T23:38:34Z). La phase confirmation
  n'a pas été validée.
- **Paquet séparé** (`cpmm_pilot/g23run011_pkg`). La 0.1 ancrée (`g23run_pkg`, MANIFEST 3e3cb105) reste INTACTE ;
  R03 l'utilise pour le pilote.
- La 0.1.1 ne sert qu'en cas de GO_PILOTE de G2-3.
- **Chemin pilote identique à la 0.1** : un test d'identité charge la 0.1 (sha 9ff0b5eb de run.py vérifié) et compare
  lignes et rapport. La seule différence est le drapeau F2 dans `erratum_c169`.

## Corrections

| Point R02 | Correction |
|---|---|
| F1 / F3 (erratum 08b14a6b, R04-9) | Entrée `--owner-p accepted\|refused` (`evaluability`). Si `accepted` : P ≤ 60 000 est exigé et D_c = D_c*. Si `refused` : D_c = D_c33, qui doit être ≥ 12. Sinon **NON ÉVALUABLE** (`p_above_60000` ou `d_c33_below_12`) : c'est publié, aucune page n'est lue. `--d-c` ne sert plus qu'à vérifier l'égalité avec D_c |
| F2 | Au pilote, chaque K de `erratum_c169` publie `p_above_60000` |
| F4 | K = 1 : α = 0,025 seulement. α n'est plus un choix manuel ; il est refusé en confirmation |
| F5 | K = 2 : UNE exécution calcule les critères c1 à A1 et le mot à 0,0125 ET à 0,025 (`at_alpha`). La p bootstrap ne dépend pas de α ; le code vérifie qu'elle est la même aux deux seuils |
| Holm | `final_words({nom: {p, words: {α: mot}}})` : rang par p, INCONCLUSIF ou STOP compte p = 1 (fiche C-169 § 4), égalités par le nom. Le rang r est testé à α₂/(K − r) ; l'arrêt se fait au premier p au-dessus. Une hypothèse rejetée est CONFIRMÉ seulement si son mot AU SEUIL qu'elle reçoit est « CRITÈRES REMPLIS » |
| Mineur | Par pool, le nombre de lignes primaires issues d'une CostError d'`exit_point` (`exit_point_errors`) |

**Changement de sémantique à valider par R02.** En 0.1, `final_words` comptait p = 1 pour une hypothèse qui manquait
ses critères. La 0.1.1 suit la fiche C-169 § 4 à la lettre : seuls INCONCLUSIF et STOP comptent p = 1, et Holm se fait
sur les p bootstrap ; une hypothèse rejetée qui manque ses critères est NON CONFIRMÉ.

**Pour N1 avec K = 2** : C-170 doit fournir ses mots aux deux seuils. n1verdict 0.3 s'exécute alors deux fois
(`--alpha 0.0125` puis `--alpha 0.025`), sur les mêmes pages, et sa p est identique d'une exécution à l'autre.

## Validation

- 18 tests : les 13 de la 0.1 adaptés, plus 5 nouveaux. Ils couvrent :
  - Holm avec le mot au seuil attribué ;
  - la règle d'évaluabilité ;
  - NON ÉVALUABLE sans lecture de pages ;
  - le compte des erreurs d'`exit_point` ;
  - l'identité du chemin pilote avec la 0.1.
- La confirmation est testée de bout en bout pour K = 1 et K = 2.
- 68 mutants sur 68 détectés (`MUTATIONS_g23run_v0_1_1.json`) : les 42 de la 0.1 qui portent sur du code inchangé, et 26 nouveaux. Le runner copie la 0.1 à côté des mutants.

## Exécution de la confirmation (R03, une fois, seulement après un GO_PILOTE et l'ancrage de la 0.1.1)

```
python -B -m g23run.run --phase confirmation --u2 U2.json --root OUT_CONF/window/collect/window --t0-slot 473309024 --sheet-sha <C-169 ancrée> --pilot-dir OUT_G23RUN --kept <K> --owner-p <accepted|refused> --d-c <D_c attendu> --g23-credits <crédits du registre g23> --out OUT_C169RUN
```

Chemin Python : g23five 0.3 (`g23five03_pkg`).

# w2arms.cb 0.1 — verdict W2 du bras C-B (§ 5 du Dossier B v1.8) sur les lignes gelées de statelab.hypotheses

**Ce que fait l'outil.**
- **Lignes :** celles de `statelab.hypotheses export` (empreinte 1e5fb31a, contrôlée), une par fenêtre, à 4 slots.
  Rien n'est rejoué.
- **Candidat :** les lignes de l'hypothèse retenue après la lecture HW1 unique, à son horizon gelé.
- **Placebo apparié :** la règle gelée de statelab (`table._paired`), soit la ligne PLACEBO du MÊME pool, au même
  horizon, avec un bootstrap par créateur.
- **Mode gelé de C-B : loyer PERDU**, avec dénominateur = la mise.
  - Le loyer est `statelab.table._rent` : la classe de jeton du recensement, ou SPL par défaut.
  - Migrée, ou sans valeur à l'horizon : (− coût − loyer) / mise.
  - Le mode « compte fermé » (closedacct 0.2) est publié à part, avec la latence de 10 slots si les lignes à 10 slots
    sont fournies.
- **Conditions, comme `ce.verdict` :**
  - c1 à c4 : α = 0,05 / 3, 10 000 tirages, graine = int(sha du gel[:8], 16) ; moitiés coupées par slot de
    CRÉATION à EVAL_MIN_1 + k × 1 612 800 / 2 ; identité des coûts en lamports ;
  - c5 : aucune condition propre à C-B, donc PASS ;
  - pas de règle 6.4 ;
  - décision : INCONCLUSIVE si n < 414, puis GO, sinon NO-GO.
- **`creation-slots` :**
  - **Pourquoi :** les lignes gelées ne portent que le slot de décision.
  - **Contenu :** le slot de création de chaque pool de la fenêtre, lu dans l'export, sans aucune valeur.
  - **Statut :** ancré par R02 comme les lignes.

**Gardes.**
- Empreinte gelée ; latence de 4 slots ; source `export`.
- Fenêtres consécutives (`w1_run.plan`).
- Un fichier de slots par fenêtre.
- Aucun pool dans deux fenêtres ; aucune position sans slot de création.
- sha de chaque fichier ; pas de pool dans le verdict.

**Preuves.**
- `test_cb.py` : 8 tests réussis (24 au total pour w2arms). L'un fait passer l'export gelé réel du pack par la commande.
  Un autre vérifie l'appariement par pool : un écart apparié constant donne exactement cette borne.
- Défauts volontaires : 12 sur 12 détectés (`MUTATIONS_cb_v0_1.json`). Les 2 défauts non détectés au premier passage
  ont conduit à 2 tests ajoutés.

**À confirmer par R02.** Le placebo apparié de C-B est-il bien la règle gelée de statelab (même pool, même horizon) ?

## cb 0.2 — condition 5 et placebo confirmés par R02 (Dossier B v1.9)

- **Placebo apparié de C-B.** R02 le CONFIRME : c'est le placebo gelé de statelab, sur les MÊMES pools, au même
  horizon, avec la même sortie et la même latence (fiche W1 § 4).
- **Condition c5, pour HW1-5.**
  - Le net moyen est > 0 à 10 slots. Les lignes `--latency10` des mêmes fenêtres sont OBLIGATOIRES ; elles sont
    contrôlées (latence 10, mêmes plages, empreinte gelée).
  - ET le net moyen est > 0 sans les 5 meilleurs pools.
- **Condition c5, pour toute autre hypothèse :** PASS.
- **Publié à part :** `without_best_5_pools`.
- **Preuves.**
  - Tests : 11 dans `test_cb.py`, 27 pour w2arms. Le test réel du pack passe par la commande, avec l'export gelé à
    10 slots.
  - Défauts volontaires : 18 sur 18 (`MUTATIONS_cb_v0_2.json`).

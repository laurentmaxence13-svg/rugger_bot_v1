# w2pack 0.3 — collecte W2 paramétrée par fenêtre (R03) — écrit et testé hors ligne, NON exécuté en réseau

- La collecte reste celle du code GELÉ (`bot.market.backfill_cli run`, arbre aff97638). w2pack ne remplace que les
  bornes par k fenêtres GELÉES consécutives (Dossier B v1.6 § 7, R02 7b867c0f) : fenêtre i = `w1_collection.bounds`
  (s0 + i × 1 612 800), k entier ≥ 1, toute autre longueur refusée. UN RUN PAR FENÊTRE : l'export gelé lit un seul
  run vérifié, dont la fenêtre doit être celle du plan (démontré hors ligne sur le pilote). Les fenêtres se
  recouvrent de 407 312 slots (warm-up + écart), recollectés à chaque run.
- `plan` : les k fenêtres, leur union (évaluations jointives), projection de crédits au taux mesuré de W1, recouvrements
  compris, avec la marge.
- `argv` : IMPRIME la commande gelée d'une fenêtre ; il ne l'exécute pas. L'exécution demande le GO du propriétaire,
  un relevé de quota actualisé et la clé fournie par le mécanisme sécurisé.
- Reprise : on relance la même commande (state.json gelé, plafonds cumulés et inscrits avant chaque envoi).
- `verify` : `bf.verify` gelé.

Tests, lancés depuis l'arbre gelé avec `PYTHONPATH=<arbre>:<w2pack>`, `unshare -rn`, `-W error` :
- fenêtre i identique à `w1_collection.bounds(s0 + i × 1 612 800)` ;
- k = 1, 4, 8 et 15 : évaluations jointives, union exacte ;
- k non entier, k ≤ 0, ancienne clé de longueur libre : refusés ;
- `argv` conforme à la fenêtre, plafond borné ;
- rejeu hors ligne du VRAI pilote W1 (61 997 transactions) par un faux opener, avec une archive identique
  (ensemble de signatures) et une vérification OK ;
- arrêt au plafond de crédits, puis reprise par la même commande, avec la même archive et sans doublon ;
- interface d'export (R02 e042f7b8) : une pseudo-fenêtre collectée en UN run et la même en DEUX runs contigus. L'export
  gelé ne prend qu'un run, et l'export d'un morceau diffère de celui de la fenêtre entière ; une fenêtre qui en
  recouvre une autre s'exporte normalement à partir de son propre run.

Gabarits `configs/W2_k{4,8,15}_TEMPLATE.json` : s0 vaut 1, à remplacer par le S0 gelé de W2.
Le calcul par lot (export, série, trials) et le ledger reprenable restent dans P-4 (R01).

## Mois de quota sous la règle GELÉE (v0.3, R02 2a6901f8)

`w1_collection.main_run_cap` impose par mois de collecte : 1 000 000 ≥ dépense du pilote + plafond de chaque run du
mois (SOL/USD compris), QUEL QUE SOIT le forfait Helius. `plan` donne `quota_months` :
- par fenêtre, un run LaunchLab et un run SOL/USD, plafonnés à leur dépense W1 mesurée × la marge :
  343 323 et 108 867 avec ×1,5 ;
- 2 fenêtres par mois avec la marge ×1,5 (910 743 réservés, pilote 6 363 compris), 3 sans marge ;
- mois requis avec la marge : k = 1 → 1, k = 4 → 2, k = 8 → 4, k = 15 → 8.
Au lancement, le `check_run_cap` gelé s'applique de toute façon à chaque run.

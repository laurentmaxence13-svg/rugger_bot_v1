# w2pack 0.1 — collecte W2 paramétrée par fenêtre (R03) — écrit et testé hors ligne, NON exécuté en réseau

- La collecte reste celle du code GELÉ (`bot.market.backfill_cli run`, arbre aff97638). w2pack ne remplace que les
  constantes W1 de `w1_collection` par des paramètres (`W2Config`) et découpe la fenêtre en segments contigus,
  pour le calcul hebdomadaire par cohortes (R02 0eb4fe3f, 7f7e49d6).
- `plan` : bornes, segments, cohortes (segment après lequel chaque cohorte est traitable), projection de crédits
  au taux mesuré de W1, avec la marge.
- `argv` : IMPRIME la commande gelée d'un segment ; il ne l'exécute pas. L'exécution demande le GO du propriétaire,
  un relevé de quota actualisé et la clé fournie par le mécanisme sécurisé.
- Reprise : on relance la même commande (state.json gelé, plafonds cumulés et inscrits avant chaque envoi).
- `verify` : `bf.verify` gelé.

Tests, lancés depuis l'arbre gelé avec `PYTHONPATH=<arbre>:<w2pack>`, `unshare -rn`, `-W error` :
- bornes W1 identiques à `w1_collection.bounds` ;
- segments contigus couvrant la fenêtre, et cohortes jamais coupées ;
- configurations invalides refusées ;
- `argv` conforme et plafond borné ;
- rejeu hors ligne du VRAI pilote W1 (61 997 transactions) par un faux opener, avec une archive identique
  (ensemble de signatures) et une vérification OK ;
- arrêt au plafond de crédits, puis reprise par la même commande, avec la même archive et sans doublon.

Gabarits `configs/W2_{14,30,60}d_TEMPLATE.json` : s0 vaut 1, à remplacer par le S0 gelé de W2.
Le calcul par lot (export, série, trials) et le ledger reprenable restent dans P-4 (R01).

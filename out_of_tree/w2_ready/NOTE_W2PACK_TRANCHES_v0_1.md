# w2pack — l'export gelé d'une fenêtre de 4 jours accepte-t-il des collectes par tranches de 7 jours ? — v0.1 (R01, 21/11)

**Réponse : NON.**
- Il n'y a pas de découpage possible sans nouveau code à auditer.
- La démonstration est hors ligne, sans réseau, sur le code gelé `bot/market/w1_collection.py` (arbre aff97638) :
  `w2pack_tranches_demo.py`.

## Ce que le code gelé exige

1. **Fenêtre exacte.** `export()` compare d'abord la fenêtre du manifeste de la collecte à `bounds(s0)` :
   adresse LaunchLab, `slot_min = s0`, `slot_max = s0 + 2 020 112`. Toute autre fenêtre est REFUSÉE
   (`window_is_not_the_w1_window`). Résultat de la démonstration (s0 = 470 904 145) :
   - tranche de 7 jours commençant à s0 : refusée ;
   - tranche de 7 jours contenant la fenêtre : refusée ;
   - bornes exactes : le contrôle passe, puis l'export exige le pilote W1 (`not_the_pilot_window`).
2. **Pilote W1.** `main_run_cap()` exige le répertoire du pilote W1 (slots 466 226 737 à 466 248 336 de P0, au plus
   50 000 crédits). Le pilote W1 existant peut servir pour W2 ; c'est à confirmer par R02.
3. **Plafond de crédits.** La collecte, le pilote et les autres collectes du MOIS (`other_runs`) restent sous
   **1 000 000 de crédits**. Le contrôle porte sur les plafonds réservés, pas seulement sur la dépense.

## Conséquences pour W2 (k fenêtres consécutives, Dossier B § 7)

- **Une collecte par fenêtre.** Chaque fenêtre dayj doit être une collecte à part, avec les bornes exactes
  [s0_i ; s0_i + 2 020 112], soit ≈ 5,03 jours collectés pour 4 jours évalués.
- **Chevauchement.** Deux fenêtres consécutives se recouvrent de 407 313 slots (402 800 de préchauffe + 4 513 d'écart).
  Ce recouvrement est collecté deux fois : **≈ +25 % de crédits et de durée de collecte** (ratio 1,2526).
- **Crédits.** La mesure revient à R03. L'ordre de grandeur du Dossier A est ≈ 60 000 crédits par jour, soit
  ≈ 300 000 par fenêtre. Le plafond gelé de 1 000 000 par mois permet donc ≈ 3 fenêtres par mois, pilote compris.
  - **C-E** (48 à 64 j, soit 12 à 16 fenêtres) : ≈ 3,6 à 4,8 M de crédits, soit 4 à 5 mois de quota gratuit, ou un
    abonnement payant. Il faut une décision du propriétaire, et il n'y a AUCUNE dépense sans son accord. C'est une
    raison de plus de ne pas retenir C-E.
  - **C-B avec HW1-5** (≈ 4 j) : 1 fenêtre, dans un mois de quota.
  - **C-B avec une autre hypothèse HW1** (10 à 25 j) : 3 à 7 fenêtres, soit 1 à 3 mois de quota.

## Options

| Option | Code | Coût | Avis R01 |
|---|---|---|---|
| (a) Une collecte par fenêtre, avec les bornes exactes, paramétrée par `s0_i` (paquet de R03) | aucun changement du code gelé | +25 % de crédits (chevauchement) | **recommandée** |
| (b) Collecte continue par tranches de 7 j, puis un « découpeur » qui fabrique pour chaque fenêtre un répertoire de collecte aux bornes exactes | NOUVEAU code : il réécrit un manifeste, un registre de dépense et des pages, avec `bf.verify` et les contrôles de plafond à repasser | −25 % de crédits | déconseillée : elle fabrique des manifestes de collecte, et ses preuves seraient lourdes |
| (c) Modifier `w1_collection` (fenêtre W2) | modification du code gelé | — | exclue |

**Question pour R02.** Le plafond de 1 000 000 par mois et le pilote W1 s'appliquent-ils tels quels à W2 ? Avec
`other_runs` = les collectes du même mois de quota. Sinon, c'est une règle W2 à écrire dans le Dossier B.

# closedacct 0.2 — corrections 1 et 2 de R02 (P-5)

1. **Un seul dénominateur : la MISE de 0,1 SOL, dans les deux modes** (Dossier B § 4).
   - Ouvert : r = (reçu − coût − loyer) / mise.
   - Fermé : r = (reçu − coût − frais_nettoyage) / mise.
   - Migrée : reçu = 0, pas de nettoyage, r = (− coût − loyer) / mise dans les deux modes.
   - L'écart entre les modes vaut exactement (loyer − frais) / mise = **+1,93 point** (testé sur un vrai rejeu).
2. **Échecs de fermeture figés à 0**, avec une sensibilité à 1 (`FROZEN_FAILED_ATTEMPTS`,
   `SENSITIVITY_FAILED_ATTEMPTS`). Après 3 échecs, le compte reste ouvert : le loyer est perdu et les 3 frais sont
   payés.

**Inchangé.** Le frais de nettoyage de 105 000 lamports (prudent) ; 5 000 lamports en sensibilité live ; seule une
vente totale est admise.

**Preuves.** 4 tests réussis. Défauts volontaires : 9 sur 9 détectés, dont `closed_on_cost`,
`open_on_cost_plus_rent`, `frozen_attempts_1` et `migrated_minus_one` (`MUTATIONS_closedacct_v0_2.json`).

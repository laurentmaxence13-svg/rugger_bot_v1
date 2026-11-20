# closedacct 0.1 — mode « compte de jetons fermé » du simulateur (prérequis P-5 de C-E)

**Modèle.** Il applique la conception live de la branche `claude/r01-live-close-base-ata` (commits edc2a1c et
9674826, hors ligne, jamais armée). Après une vente TOTALE, une transaction séparée exécute un Burn borné, puis
CloseAccount.
- Le dépôt (2 039 280 lamports) revient au portefeuille. Ce n'est pas un produit de vente.
- Seul le frais réseau est un coût.
- Formules :
  - fermé : r = (reçu − coût − frais_nettoyage) / coût ;
  - ouvert : r = (reçu − coût − loyer) / (coût + loyer), c'est-à-dire le `latelab.net_return` gelé ;
  - migrée : −1 dans les deux modes.
- Frais de nettoyage : 105 000 lamports par défaut, valeur PRUDENTE (une transaction de la chaîne gelée). La valeur
  par défaut du live est 5 000 lamports ; elle est fournie comme sensibilité.
- Échecs : chaque tentative coûte le frais. Après 3 échecs, le compte reste ouvert et le loyer est perdu.

**Admissibilité.** Le mode ne s'applique qu'à une vente totale ; tout autre résultat est refusé.

**Effet sur une position de 0,1 SOL.** +1,89 point : le loyer de 2,00 %, moins le frais de 0,105 %.

**Preuves.**
- 5 tests réussis, dont un sur un vrai rejeu `run_rule` du pack gelé : fermé = (reçu − coût − 105 000) / coût, et
  fermé > ouvert.
- Défauts volontaires : 7 sur 7 détectés (`MUTATIONS_closedacct_v0_1.json`).

**Limite.** Ce n'est pas une preuve sur la chaîne. La fermeture réelle reste à exécuter en devnet ou en PAPER par
le chemin live, après décision.

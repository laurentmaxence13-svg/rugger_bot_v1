# Point 3 — exécution PAPER coûtée en continu, câblage HORS LIGNE — plan v0.1, AVANT tout code (R01, 21/11)

**But.** Un moteur PAPER en flux qui reçoit les événements LaunchLab UN PAR UN, dans l'ordre du temps et sans regard
vers l'avant, comme ils arriveraient en direct.
- Il décide avec le MASTER gelé.
- Il produit des cycles BUY/SELL coûtés et journalisés.
- Tout se fait hors ligne, sur des données déjà collectées (pack gelé, P0 visible, W1 après autorisation), sans
  réseau, sans clé, sans signature.
- Le flux réel (point 2) et Render (point 4) restent soumis à l'accord du propriétaire.

**Ce qui existe déjà (branche integration/consolidation-20261103) et sera réemployé SANS modification.**
- Décision et rejeu coûté gelés : `bot.master_v2` (politique MASTER de W1), `bot.p4.historical_research_replay`
  (rejeu, ExecutionModel), v4sim M-P, `bot.market.replay.causal_fee_rate`. Ils produisent déjà, en lot, les cycles
  coûtés de W1 (HISTORICAL_REPLAY).
- Journal : `bot.p4.live_like_paper_ledger`, un registre PAPER par événements qui échoue fermé (frais inconnus,
  sorties censurées, horloges périmées).
- Observateurs en direct, lecture seule : `bot.live.helius_rolling_signed_paper` et autres. Ils ne sont PAS branchés
  dans ce point.

**À écrire (paquet hors arbre `paperstream` 0.1).**
1. **Source d'événements rejouée** : elle lit une archive de pool et émet les événements un à un, avec un horodatage
   de « réception ». Elle ne garantit rien de plus que l'ordre du temps.
2. **Moteur en flux** : à chaque événement, il appelle la décision gelée du MASTER sur l'historique reçu
   seulement.
   - **ENTER** : achat PAPER, avec atterrissage après la latence gelée (4 slots) et le fill calculé sur l'état de
     courbe à l'atterrissage, avec le taux causal.
   - **Sortie** : vente PAPER selon la règle gelée du MASTER.
   - **Écriture** : chaque intention, fill et coût (frais de courbe, tx, loyer ou fermeture via closedacct) va dans
     le journal.
   - **WAIT** est journalisé avec sa raison.
3. **Garde « aucun regard vers l'avant »** : le moteur ne reçoit jamais un événement postérieur à l'horloge
   courante. Un test lui injecte un futur et attend un refus.

**Preuves prévues (tests hors ligne).**
- (i) Sur le pack gelé et sur P0 visible (PASS R02 requis pour P0) : les cycles du moteur en flux sont IDENTIQUES,
  octet pour octet, à ceux du rejeu en lot gelé. Ce sont les mêmes décisions, fills, coûts et sorties.
- (ii) Les intentions de recherche (`MASTER_RESEARCH_PAPER`) et les démonstrateurs DexScreener ne peuvent PAS être
  étiquetés « cycle MASTER » (test).
- (iii) Seuils protégés : 50 cycles qualifiés et 20 créateurs. Ils restent ceux du code et ne sont jamais abaissés.
  Le moteur dit « WAIT, seuils non atteints » s'il le faut.
- (iv) Le journal se réconcilie : coût = frais + tx + loyer, net en lamports, avec un résidu nul.
- (v) Défauts volontaires.

**Ce que cela prouve et ne prouve pas.**
- **Prouvé :** le chemin décision → BUY/SELL PAPER coûté → journal fonctionne en flux, comme en lot.
- **Non prouvé :** la qualité d'un flux réel (latence, trous), qui relève du point 2. Une rentabilité : aucune
  stratégie n'est validée.
- **Libellé :** un cycle issu de ce moteur sur des données passées reste HISTORICAL_REPLAY. Ce n'est PAS un
  « genuine Master PAPER BUY/SELL » en direct.

**Effort.** ≈ 1 à 2 jours, puis l'audit de R02.

# Contre-revue indépendante du moteur LIVE — 29 octobre 2026

Périmètre : `bot/live/wire.py`, `route.py`, `safety.py`, `engine.py`,
`journal.py`, `rpc.py`, et leurs tests. Aucun appel réseau de marché, aucun
portefeuille, aucune clé, aucune signature réelle ni soumission n'a été utilisé
par cette revue. Les tests d'exécution utilisent des services explicitement
factices avec les véritables octets de transaction construits par le routeur.

## Défauts établis et corrigés pendant la contre-revue

1. **Arrêt/expiration après le dernier await.** Un kill persistant pendant le
   dernier `get_block_height` n'empêchait pas l'envoi. La santé pouvait aussi
   devenir périmée, ou l'autorisation expirer, pendant cet appel. Les trois
   scénarios indépendants ont échoué avant correction. La transition finale
   `SIGNED -> SUBMITTING` tient maintenant le verrou SQLite `BEGIN IMMEDIATE`,
   vérifie le kill et réévalue synchroniquement l'admission avec la nouvelle
   horloge, les faits reçus et les réservations du journal. Aucun autre await
   n'intervient avant l'appel d'envoi. Les trois régressions passent.

2. **Frais des transactions échouées hors plafond de perte.** Le journal
   enregistrait les dépenses, mais pas la perte irréversible des frais d'une
   transaction échouée. La réconciliation comptabilise désormais `pnl = -fee`,
   alimente la perte journalière et conserve le compteur d'échecs.

3. **Dépôt ATA immobilisé omis après réconciliation.** La réserve initiale
   incluait le dépôt, mais le capital engagé et le budget journalier l'oubliaient
   ensuite. Le dépôt réellement immobilisé est maintenant conservé séparément
   du coût de revient, inclus dans les limites de capital et de trésorerie,
   y compris après liquidation complète des tokens lorsque l'ATA reste ouvert.
   Le dépôt WSOL créé puis remboursé dans la même transaction n'est pas confondu
   avec un coût irréversible.

4. **Impact de prix non lié aux limites du propriétaire.** Le routeur bornait
   l'impact selon un paramètre technique, sans plafond dans l'autorisation.
   `max_price_impact_bps` est maintenant obligatoire dans l'enveloppe financière,
   `price_impact_bps` est lié à l'ordre, et l'admission applique cette limite
   indépendamment du slippage. Les montants restent des entiers exacts. Un
   changement du plafond change le digest et invalide l'armement précédent.

5. **Réservation abandonnée avant soumission.** La reprise conservait une
   réservation `RESERVED` sans signature indéfiniment. `RESERVED` et `SIGNED`
   peuvent maintenant être annulés sans réémission, car le marqueur durable
   `SUBMITTING` précède strictement l'unique appel d'envoi. Les états ambigus
   conservent leurs réservations et exigent une réconciliation de chaîne.

6. **Cohérence entre audit et tables financières.** Les vérifications de reprise
   lient maintenant les ordres, leurs états, réservations, signatures, octets
   signés, inventaires, comptes journaliers et kill au journal de hachage. Les
   altérations directes des lignes et des résultats comptables sont refusées.

## Contrôles observés dans le code et tests

- ABI LaunchLab épinglée, quantités atomiques, `min_out`, privilèges et taille
  maximale du paquet vérifiés; route reconstruite depuis la requête raw retenue.
- Programme et PDAs du graphe re-décodés; Token-2022 et migration refusés
  explicitement dans cette version; aucune route non implémentée n'est inventée.
- WSOL éphémère dédié, création/initialisation/synchronisation/fermeture explicites;
  aucun vidage d'un compte WSOL existant.
- Deux actions d'armement distinctes, enveloppe liée au wallet/cluster/RPC,
  limites exactes de capital, pertes, dépenses, frais, impact et slippage.
- La cotation garde son slot et son heure de réception. Le contrôle de risque
  peut utiliser une bank ultérieure, jamais une bank antérieure; il ne rafraîchit
  pas artificiellement l'heure de la cotation.
- Signature externe vérifiée par Ed25519; vecteur public RFC8032 testé. Le
  signataire factice est identifié comme tel dans les tests de cycle isolé.
- Marqueur durable avant envoi, pas de retry implicite, pas de reconstruction
  automatique d'un ordre ambigu; disparition d'une confirmation et expiration
  de statut inconnu déclenchent un arrêt et préservent les fonds réservés.
- Réconciliation finale liée à la signature, au message exact, aux quantités,
  aux balances, aux frais et au slot; ventes partielles et reliquat entier testés.

## Résultat reproduit de cette revue

Commande sur copie jetable sans réseau, `.env`, ou base utilisateur :

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B tools/offline_check.py \
  -q tests/test_live_adversarial_review.py tests/test_live_engine.py \
  tests/test_live_safety.py tests/test_live_wire_route.py tests/test_live_rpc.py \
  -p no:cacheprovider -W error
```

**177 tests réussis en 1,19 s**, stderr vide. Le groupe comprend les 3
régressions indépendantes d'arrêt/expiration et 88 tests des protections.
Logs locaux : `/workspace/work/live-20261029/live-counterreview.txt` et
`live-counterreview.stderr`. Ce résultat porte sur cette copie de fichiers;
le checkpoint final doit être associé à son manifeste exact et à la suite
complète réalisée par l'intégrateur.

## Limites de preuve

Cette revue ne certifie pas `LIVE_READY_TO_ARM`. Les tests RPC factices ne
démontrent ni simulation mainnet réussie ni validité d'un programme déployé.
Le fournisseur d'observations courantes et la supervision doivent réellement
relier les banks RPC, la santé scanner/WS, les coûts et l'état du programme
avant toute admission. Une vérification du propriétaire/programme ne constitue
pas une attestation du binaire déployé. Les scopes d'autorisation sont des
reçus d'opérateur et ne sont pas un mécanisme d'authentification externe.

`LIVE_EXECUTION_VERIFIED` et `ECONOMIC_EDGE_VALIDATED` restent également non
établis : aucune transaction financière ni performance indépendante n'a été
effectuée ou démontrée par ces tests. Une signature/confirmation factice ne
doit jamais être publiée comme une opération de marché.

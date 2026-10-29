# Route LaunchLab et encodage Solana — validation isolée

Les modules `bot/live/wire.py` et `bot/live/route.py` construisent des messages
legacy Solana et leurs transactions sérialisées. Aucun de leurs imports ne lit
de clé, n'ouvre de connexion ou n'envoie de transaction.

## ABI et sources

- Programme LaunchLab : `LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj`.
- IDL officiel : `raydium-io/raydium-idl`, commit
  `e7e0c96fe77bcf6a020b84a44c47a722aac8e359`, fichier
  `raydium_launchpad/raydium_launchpad.json`, blob
  `70186e3f02c2bead7e5a9a92453104df853683ed`.
- Extrait conservé directement depuis cette lecture :
  `bot/live/launchlab_swap_abi.json`. Les deux discriminateurs, les quinze
  comptes et leurs privilèges, et les trois arguments `u64` sont testés contre
  cet extrait officiel.
- `CreateAccountWithSeed` : code officiel `solana-labs/solana`, tag
  `v1.18.26`, `sdk/program/src/system_instruction.rs`. Les trois positions de
  comptes, dont le wallet dupliqué en base signataire, sont conservées.

Deux lectures documentaires GitHub ont été effectuées. Aucun appel marché/RPC,
wallet, signature réelle, airdrop ou envoi n'a été effectué par ce travail.
Les pins prouvent la correspondance du code avec l'ABI publiée. Ils ne
certifient pas le binaire actuellement déployé ni son absence de vulnérabilités.

## Capacités implémentées

Construction `buy_exact_in` et `sell_exact_in` sur courbe active native SOL /
SPL Token classique, montants atomiques exacts, `min_out` strictement positif,
plafonds explicites de slippage, impact de courbe, compute et priority fee.
Le frais de courbe est déjà inclus dans la quantité projetée ; il n'est pas
redéduit comme frais réseau. La méthode re-décode les comptes bruts et refuse
les PDA inconnues, risques, incohérences, données périmées et disponibilités
postérieures à la décision.

Le WSOL utilise un compte dédié déterministe par décision, observé absent avant
construction : création avec seed publique, initialisation, `SyncNative`, swap,
fermeture dans la même transaction. Un compte WSOL existant est refusé ; il
n'est jamais vidé. L'ATA du token de base est créée de façon idempotente pour
l'achat si nécessaire ; une vente exige l'inventaire réellement présent dans
l'ATA du wallet. Rent et SOL nécessaires avant la transaction sont vérifiés
séparément des frais réseau. Aucune taille n'est déduite d'un devis redimensionné.

`validate_prepared_order` reconstitue le message et tous les champs depuis une
requête JSON immuable retenue. Une modification du message, du `min_out`, du
slot ou du digest est refusée. La preuve de provenance RPC, le rafraîchissement
des comptes, l'autorisation financière, la vérification Ed25519 et la
simulation/confirmation restent des responsabilités indépendantes du moteur.

## Défaut supplémentaire corrigé

Une vente ne doit pas exiger qu'un nouvel achat reste admissible près du
plafond de fundraising. `launchlab.analyze_snapshot(compute_projection=False)`
effectue les mêmes validations de comptes sans calculer un achat ; la vente
calcule ensuite sa quantité exacte. Le comportement par défaut et les replays
historiques sont conservés. Une régression vérifie qu'une vente valide passe
lorsqu'un nouvel achat est refusé, et qu'un mint invalide reste refusé.

## Vérification

Commande :

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B tools/offline_check.py \
  -q tests/test_live_wire_route.py -p no:cacheprovider -W error
```

Résultat isolé à ce checkpoint : **29 passed in 0.47s**. Harnais sans réseau,
dotenv, base utilisateur ni clés. Contenu : vecteur wire SystemTransfer calculé
indépendamment, décodeur de messages indépendant, comparaison ABI officielle,
limite de paquet 1232 octets, vecteur de signatures exact, privilèges et alias,
achats/ventes, rent/frais/impact, refus des inventaires insuffisants, comptes
manquants/existants, altérations, et invariants de liquidation.

## Limites conservées

Token-2022 est refusé explicitement pour l'exécution jusqu'à certification de la
route et de ses extensions. Un pool migré est refusé ; aucune route de secours
AMM n'est inventée. Un signataire externe doit fournir et faire vérifier une
signature Ed25519 valide ; l'encodage seul ne prouve pas sa validité. Les tests
utilisent uniquement des comptes synthétiques et des octets sans signature.

Ce lot n'établit aucun fill, résultat économique, déploiement vérifié ou statut
`LIVE_READY_TO_ARM` global. Il fournit des instructions et messages réellement
sérialisables à intégrer avec les autres barrières du moteur.

# L3 : affichage des rejeux de recherche dans Rugger Wallet

Code : `bot/dashboard/research_view.py` (fonctions pures, sans réseau) et l'onglet « Recherche et rejeux historiques » de `bot/dashboard/app.py`. Tests hors réseau : `tests/test_dashboard_research_view.py`.

Rien dans cet affichage ne passe, ne signe ni ne lit d'ordre, et rien n'appelle un fournisseur ou un site externe.

## 1. Étiquettes

Chaque élément affiché (pool, décision, cycle) porte une étiquette.

| Étiquette | Signification | État actuel |
|---|---|---|
| `HISTORICAL_REPLAY` | rejeu de données on-chain archivées (`rugger-historical-research-replay-v1`) | affiché |
| `PROSPECTIVE_PAPER` | recherche PAPER prospective | section **vide** : aucun producteur n'existe encore |
| `SYNTHETIC` | ajoutée dès qu'un chiffre dépend d'une entrée inventée : série SOL/USD `SYNTHETIC_TEST_FIXTURE` ou taux SOL/USD **déclaré** (supposé) | ajoutée aux variantes b à d |
| `REAL` | opérations réellement exécutées on-chain | section **toujours vide** |

Un rejeu n'est jamais un trade du Master. Il n'est pas compté dans le seuil de 50 cycles et 20 créateurs.

## 2. Vérification à l'affichage

Un bundle n'est affiché que si toutes les conditions suivantes sont remplies :

1. Le fichier fait au plus 8 Mo et le JSON est valide, sans `NaN` ni `Infinity`.
2. Le schéma et la catégorie sont `HISTORICAL_REPLAY`.
3. Les drapeaux `master_operational_trade`, `counted_in_master_gate`, `admissible_in_paper_ledger`, `financial_order_submitted`, `sol_usd_verified` et `source_clock_verified` valent exactement `false`, et `research_evidence_status` vaut `PENDING_R02_QUALIFICATION`. Aucun producteur ne peut encore poser ces vérifications, et seul RUGGER 02 qualifie une preuve, jamais à l'intérieur d'un bundle (correctif B2 de T-0035).
4. Le `bundle_sha256` recalculé, avec le même JSON canonique que le rejeu, est égal à la valeur déclarée.
5. Si ce `bundle_sha256` figure dans `validation/historical_replay_l1/RESULTS.json`, le sha256 du fichier doit aussi être celui du registre. Le statut est alors `VERIFIED_AGAINST_RESULTS_REGISTRY`.
6. Un bundle importé qui ne figure pas dans le registre reçoit au mieux le statut `SELF_CONSISTENT_NOT_IN_REGISTRY` : il est cohérent avec lui-même, mais aucun tiers ne l'a enregistré. Il est affiché sous un avertissement, jamais sous le bandeau vert.
7. Tout texte venant d'un bundle et rendu en Markdown (provenance, nom de fichier, motif) est échappé et borné à 200 caractères.

Sinon, le bundle est refusé avec son motif et rien n'en est affiché.

## 3. Contenu affiché

- **Pools** :
  - mint, créateur et signature du créateur vérifiée ou non, avec le motif ;
  - nombre de décisions et d'ENTER par bras, cycles clos et principaux motifs de blocage ;
  - liens externes.
- **Décisions**, avec un filtre par pool et par bras :
  - action et motifs de blocage, score ;
  - cours SOL/USD utilisé et sa source : point de la série (provenance, empreinte de preuve, âge, `NOT_VERIFIED_IN_REPLAY`), taux déclaré marqué « supposé, non vérifié », ou refus avec son motif ;
  - lien Solscan de la transaction.
- **Cycles BUY→SELL** :
  - achat, vente, frais et P&L en SOL, convertis exactement depuis les lamports ;
  - seul un cycle `closed` a un P&L et compte comme cycle clos ;
  - une position `open_at_end` (jamais vendue, valorisée au dernier cours) ou `open_at_window_end` n'a pas de P&L : sa valeur de marché est indiquée à part et n'entre dans aucun total (correctif B1 de T-0035) ;
  - sans cycle, le P&L reste **vide**, jamais égal à zéro.

Pour cela, le journal du rejeu indique désormais la mantisse et l'exposant du point SOL/USD utilisé (`price`, `exponent`). Le bundle par défaut, sans série, est inchangé.

## 4. Liens externes

Les liens sont construits seulement à partir d'une adresse base58 qui se décode en exactement 32 octets, ou 64 pour une signature. Ils sont ouverts par le navigateur de l'utilisateur ; le tableau de bord ne les appelle jamais.

| Lien | Format |
|---|---|
| Axiom Trade | `https://axiom.trade/t/<mint>` (format validé provisoirement par le propriétaire, selon la coordination de RUGGER 04 du 2026-11-05) |
| Solscan | `https://solscan.io/token/<mint>`, `https://solscan.io/account/<pool>`, `https://solscan.io/tx/<signature>` |
| DexScreener | `https://dexscreener.com/solana/<pool>` |
| Raydium | `https://raydium.io/launchpad/token/?mint=<mint>` (page LaunchLab ; format à confirmer par le propriétaire) |

## 5. Limites

- Seul le bundle commité (variante a) est vérifié contre le registre. Les variantes b à d ne sont pas commitées : importées, elles sont vérifiées par leur `bundle_sha256` et leur sha256 de fichier enregistrés.
- Aucun déploiement n'est fait. Streamlit Community Cloud, Render et Vercel ne sont pas modifiés.
- La décision D4 sur l'interface unique reste au propriétaire.

# PAPER_LIVE — champs D-1 à D-7 : ce qui est déjà justifié, ce qui manque (v0.2)

RUGGER 01, 23/11/2026. Directive du propriétaire du 23/11 à 10:22Z, point 5, relayée par R04.
- Base : v0.1 (e72147d3), protocole PAPER_LIVE v0.2 (1386a40, CONFORME R02).
- Un champ est **PRÉREMPLI** seulement si une autorisation ou une configuration existante le justifie ; la source est
  citée à chaque fois. Tout autre champ est **MANQUANT** et porte une recommandation technique.
- Les montants et le choix du fournisseur restent au propriétaire.
- Aucun développement nouveau. L'adaptateur de flux n'est pas écrit tant que D-2 n'est pas choisi.

Abréviations des sources :
- **[W1]** : `W1_PROTOCOL_v2.6.2.json`, protocole W1 GELÉ (sha256 0b88317a1170b96f…), cité par clé JSON.
- **[FWD]** : `bot/live/helius_ws_forward_paper.py` de l'arbre gelé aff97638 (git 634d09b).
- **[PYTH]** : `bot/market/pyth_push.py` du même arbre.
- **[STATUS]** : `PROJECT_STATUS.md` (commit 16f1f22).

## Synthèse

| Champ | État |
|---|---|
| D-1 Hôte 24 h | **MANQUANT** (6 sous-champs sur 6) |
| D-2 Source du flux | **PRÉREMPLI** pour 4 sous-champs sur 5 (configuration et offre existantes). **Mais l'offre existante ne suffit pas au volume : voir l'alerte ci-dessous** |
| D-3 Plafond de la fenêtre | **MANQUANT** (3 sur 3) |
| D-4 SOL/USD en direct | **PRÉREMPLI** pour 3 sous-champs sur 4 (source et acceptation de W1) ; l'accès réseau dépend de D-2 |
| D-5 Secret | 1 sous-champ PRÉREMPLI (la règle) ; 2 MANQUANTS |
| D-6 Interface unique | **MANQUANT** : la décision D4 n'a pas été prise |
| D-7 Texte d'autorisation | **MANQUANT**, par construction : il se complète après D-1 à D-4 |

## ALERTE de volume : l'offre Helius existante ne couvre pas 14 jours

Calcul, à partir de sources existantes seulement :
- **Slots.** 806 400 slots = 48 h ([W1] `credit_budget/cap_rule`). 14 jours font donc **5 644 800 slots**.
- **Densité.** LaunchLab a 1,3612 transaction par slot en P0 ([W1] `credit_budget/pilot_estimate` ; mesure R03).
- **Transactions.** On attend environ **7,7 millions** de transactions sur 14 jours, soit **6,35 transactions/s** en
  moyenne.
- **Le décodeur gelé exige un `getTransaction` par transaction notifiée** (obstacle O-3, note P3 v0.2). Les journaux de
  `logsSubscribe` ne suffisent pas.
- **Offre existante : Helius Free**, 1 000 000 crédits par mois et 10 requêtes/s ([W1] `data/provider` et
  `credit_budget/cap_scope`, relevés du propriétaire 31f63f90, 28917f6d et eeaaad19). Sur 14 jours, cela donne environ
  **467 000 crédits**.
- **Coût d'un `getTransaction`.** À 1 crédit l'appel, le besoin est d'environ **7,7 M de crédits, soit environ 16 fois
  l'offre**. Le débit moyen occupe en outre 64 % de la limite de 10 requêtes/s, sans marge pour les pointes.
  - Ce coût unitaire est à confirmer par R03 sur la page de tarification archivée (billing/credits fa152d54… et
    pricing b6794b16…). R01 ne l'a pas vérifié.

**Conséquence.** Avec l'offre existante, le PAPER_LIVE de 14 jours n'est pas réalisable tel que le protocole le
décrit. Il y a trois issues techniques ; le choix revient au propriétaire.
- **(A)** Une offre avec plus de crédits, ou un abonnement au niveau transaction qui livre les instructions internes.
  C'est une dépense, donc une décision du propriétaire.
- **(B)** Ne demander `getTransaction` que pour les pools que le Master suit encore dans sa fenêtre d'observation.
  C'est un nouveau code d'acquisition, et il doit prouver qu'il ne perd aucun événement utile. Ce développement est
  écarté tant que D-2 n'est pas choisi.
- **(C)** Une fenêtre plus courte. **Ce n'est pas possible** : les 14 jours sont fixés par le protocole v0.2. Les
  changer imposerait un amendement audité par R02.

## D-1 — Hôte 24 h

Aucun hôte n'est autorisé pour PAPER_LIVE. Le paquet cloud D1, audité CONFORME par R02, visait le calcul de W1 : il
ne vaut pas autorisation ici.

| Sous-champ | État | Recommandation technique |
|---|---|---|
| Fournisseur et type de machine | MANQUANT | Une VM à 2 vCPU et 8 Go. Les essais W1 tournaient à environ 1 Go de RSS par processus ; un seul processus suffit. Reprendre l'outillage `create_vm.sh` déjà audité par R02, par un amendement audité, plutôt qu'un nouvel outil. Ne pas utiliser un runner GitHub Actions (O-12) |
| Région | MANQUANT | La région la plus proche du point d'accès de D-2. La latence (S-3 : p95 ≤ 4 slots) se mesure sur le banc avant T0 ; c'est elle qui tranche. L'outillage existant utilise us-central1-a |
| Disque des journaux | MANQUANT | **50 Go.** Les corps bruts compressés font environ 13 Go (7,7 M × 1 700 octets, l'estimation `stored_gz_bytes_estimate` de la collecte W1). On ajoute les journaux et une marge ×3, ce qui couvre aussi une reprise |
| Plafond de dépense de l'hôte sur 14 j | MANQUANT | Montant au propriétaire |
| Qui peut s'y connecter | MANQUANT | R03 seul, l'exécutant, comme pour les collectes de W1. R01 et R02 n'y ont aucun accès |
| Horloge NTP | MANQUANT | Oui. L'arrêt 6 du protocole l'exige |

## D-2 — Source du flux

| Sous-champ | État | Valeur et source |
|---|---|---|
| Fournisseur | **PRÉREMPLI** | Helius, point d'accès `mainnet.helius-rpc.com` ([FWD] l. 21), qui est la seule clé et la seule offre existantes ([W1] `authorizations_needed/1-2`) |
| Type d'abonnement | **PRÉREMPLI** | `logsSubscribe` (mentions du programme LaunchLab), puis un `getTransaction` par transaction ([FWD] l. 25-26 ; O-3). C'est le seul chemin que le décodeur gelé accepte avec cette offre |
| Engagement | **PRÉREMPLI** | `confirmed` ([FWD] l. 26 et 189). C'est cohérent avec `rtgate.retract` en cas de rollback. `finalized` ajouterait environ 32 slots de retard et ferait échouer S-3 (p95 ≤ 4 slots) |
| Offre et quotas | **PRÉREMPLI** | Free : 1 000 000 crédits par mois, 10 requêtes/s, dépense de 0,00 USD ([W1] `data/provider` et `cap_scope`). **Insuffisante : voir l'alerte de volume** |
| Conditions d'utilisation archivées | Partiel | billing/credits fa152d54… et pricing b6794b16… ont été archivés par R03 le 08/11 (`pyth_probe_prep`). Les sha256 des conditions générales et de la politique de confidentialité sont chez R03 ; je ne les ai pas lus. **Recommandation : réarchiver toutes les pages à T0**, car le protocole exige les conditions en vigueur |

Si le propriétaire choisit l'issue (A) avec un autre type d'abonnement, les 3 premiers sous-champs repassent à MANQUANT.

## D-3 — Plafond de crédits et de dépense de la fenêtre

La décision de plafond du propriétaire (956fd4cc, 09/11) ne couvre que W1 : elle ne s'étend pas ici.

| Sous-champ | État | Recommandation technique |
|---|---|---|
| Plafond de crédits sur 14 j | MANQUANT | Prévoir au moins le volume estimé, environ 7,7 M `getTransaction`, plus les reprises après reconnexion (O-15). Avec l'offre Free : impossible, voir l'alerte |
| Plafond de dépense associé | MANQUANT | Montant au propriétaire |
| Arrêt dur à 98 % sans reprise | MANQUANT | Oui. C'est la même règle que les collectes de W1 ([W1] `authorizations_needed/6`) et elle est déjà codée dans `plbench.stops` (arrêt 1). Elle exige un oui explicite |

## D-4 — SOL/USD en direct

| Sous-champ | État | Valeur et source |
|---|---|---|
| Source | **PRÉREMPLI** | Le compte Pyth on-chain `7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE` (Pyth Core, shard 0), flux ef0d8b6f…b56d ([PYTH] l. 4-5, 39-40 ; [W1] `data/sol_usd/feed_id`). Hermes n'est pas utilisé et il n'y a pas de clé Pyth ([W1] `authorizations_needed/5`) |
| `max_age_ms` | **PRÉREMPLI** | **55 000** ([W1] `data/sol_usd/anchored_study/acceptance`, rapport e3d92847…, ancrage R02 67b40085) |
| `max_confidence_ppm` | **PRÉREMPLI** | **950** (même source) |
| Accès réseau | MANQUANT | Le compte se lit par le point d'accès de D-2 (abonnement au compte). Il ne faut donc aucun hôte de plus, mais l'autorisation de D-2 doit le couvrir |

Réserve, à trancher par R02 : l'acceptation a été mesurée sur trois fenêtres historiques. Le protocole v0.2 demande
« la même garde ». La reprendre telle quelle est le choix le plus prudent ; une nouvelle mesure en direct serait un
nouvel essai.

## D-5 — Secret du fournisseur

| Sous-champ | État | Valeur, source ou recommandation |
|---|---|---|
| Règle | **PRÉREMPLI** | Le SECRET est fourni par un mécanisme que le propriétaire contrôle ; aucun agent ne le lit, ne l'affiche, ne le journalise ni ne le committe ([W1] `authorizations_needed/2`). Le code existant le lit seulement en mémoire de processus (`HELIUS_API_KEY`, [FWD] l. 283) |
| Lieu de stockage sur l'hôte | MANQUANT | Le gestionnaire de secrets de l'hôte de D-1 (par exemple Secret Manager pour une VM Google), injecté dans le seul processus de l'observateur. Jamais un fichier `.env`, puisque `RUGGER_NO_DOTENV=1` est déjà la règle |
| Rotation | MANQUANT | Le propriétaire fait tourner la clé à T0 (nouvelle clé réservée au PAPER_LIVE) et à la fin de la fenêtre |
| Retrait du secret Helius de l'environnement R03 (état unique § 2) | MANQUANT | Demandé depuis la note P3 (O-13). Aucune confirmation trouvée. À faire avant T0, avec la date |

## D-6 — Interface unique d'affichage

| Sous-champ | État | Recommandation technique |
|---|---|---|
| Choix unique (décision D4) | **MANQUANT** : D4 reste ouverte ([STATUS] l. 64 et 341) | **Streamlit (Rugger Wallet).** C'est la seule interface qui affiche déjà la provenance exacte (vue `research_view` de L3, copie épinglée aade2d5a). Le test T-14, qui refuse toute prétention de trade MASTER, de 50/20 ou d'ordre, y est écrit et passe (rtgate 0.2). Render et Vercel exigeraient un portage, puis un nouvel audit |
| Archivage des deux autres | MANQUANT | Oui, après le choix. Aucune modification de production avant le GO |

## D-7 — Texte d'autorisation

MANQUANT par construction. Le modèle de la v0.1 reste valable : il se complète avec les valeurs de D-1 à D-4, puis le
propriétaire l'écrit dans la session de R03.

## Ce que le propriétaire doit décider (rien d'autre)

1. **L'issue de l'alerte de volume** : (A) offre ou abonnement plus large, ou (B) acquisition ciblée, à coder et
   auditer. Ensuite, D-3 (crédits, montant, oui à 98 %).
2. **D-1** : fournisseur, machine, région, plafond de dépense, accès, NTP.
3. **D-5** : lieu de stockage, rotation, confirmation du retrait du secret chez R03.
4. **D-6** : la décision D4.
5. **D-7** : le texte, une fois 1 à 4 fixés.

À valider par R02 : la reprise de l'acceptation W1 (55 000 ms, 950 ppm) en direct ; le calcul de volume. R03 doit
confirmer le coût unitaire de `getTransaction` sur la page archivée.

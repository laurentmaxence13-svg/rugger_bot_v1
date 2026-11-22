# cpmmcost 0.1 — modèle de coûts complet d'une position du pilote CPMM (tâche P2-b)

RUGGER 01, 22/11/2026. ÉCRIT ET TESTÉ SUR DONNÉES SYNTHÉTIQUES. Aucune donnée CPMM réelle n'existe : C-1 n'est pas
passé, rien n'est créditable, aucun essai n'est consommé.

Bases :
- `docs/ops/ETAT_RUGGER_MASTER.md` (62c4525), tâche P2 ;
- note du pilote v0.2 (b4c6562c), § 2.1 à 2.5 ;
- protocole CPMM v1.2 (a3a285a1), § 4 à 6.

Aucune exploitation rétrospective : aucune règle, aucun seuil et aucun univers n'est réglé sur une donnée.

## Ce que calcule `position(timeline, decision_index, amm_config, exit_slot=… | exit_time=…)`

Tout est calculé sur les réserves que le programme a journalisées (`cpmmx.timeline`), avec l'arithmétique exacte
cp-swap (`cpmmx.curve`), et les taux LUS dans l'AmmConfig, haché avec son slot. Rien n'est supposé.

| Poste | Modèle |
|---|---|
| Frais | Frais de trading et de créateur des deux jambes, exacts, du côté que le pool journalise. L'univers U-1 impose un taux de trading = 2 500 ppm ; sinon `outside_universe_u1_trade_fee`. |
| Impact de prix | Exact, par la courbe sur l'état d'atterrissage (aucune formule à la main). |
| Délais | L'achat atterrit 4 slots après le swap de décision. La vente atterrit au slot de sortie, ou à l'heure de l'horloge. |
| Ordre dans le slot (H-1) | Pire cas : le MOINS de jetons à l'achat, la valeur la PLUS BASSE à la vente, entre les états avant et après les swaps réels du slot (ou de la seconde). |
| X-1 (ii) | La vente est aussi valorisée avec notre achat laissé dans le pool ; la plus basse des deux est retenue. |
| Échecs | Chaque tentative échouée (achat, vente, nettoyage) est facturée 105 000 lamports. Hypothèse gelée : 0 échec. Sensibilité : 1 de chaque. Un échec ne déplace pas l'état d'atterrissage (déclaré). |
| Fermeture des comptes (C-a) | Compte jeton FERMÉ en transaction séparée : (échecs + 1) × 105 000, loyer rendu. Après 3 échecs, le compte reste ouvert : loyer perdu + 3 × 105 000. L'enveloppe WSOL est fermée à part (+105 000, hypothèse défavorable), tant que la fermeture dans la vente n'est pas montrée sur une transaction publique réelle. |

**Rendement sur la mise.** r = (reçu − mise − transactions − fermeture WSOL − nettoyage [− loyer perdu]) / 0,1 SOL.
- Il est recoupé avec `closedacct.net_return_closed` (écart > 1e-12 : arrêt).
- La décomposition exacte (mouvement de prix, frais, impact, transactions, WSOL, nettoyage, loyer) a un résidu nul en
  fractions ; un résidu non nul ou un impact négatif provoque l'arrêt.

## Seuil et barre (C-a, CP-1)

- Frais et transactions à impact nul, en mode fermé, WSOL fermé dans la vente :
  2 × 0,25 % + 3 × 105 000 / 10⁸ = **0,815 %**, déclaré 0,82 % (testé).
- Table CP-1, avec `bar()`, sans fermeture WSOL séparée : 1,815 % / 1,015 % / 0,915 % à 20 / 100 / 200 SOL (testé).
- Barre de travail : **1,12 % à 100 SOL**.
- Contrôle du modèle (synthétique, PAS un résultat) : un aller-retour à prix constant sur un pool de 100 SOL coûte
  1,117 % en exact, juste sous la barre de dimensionnement de 1,12 %.

## Décodeur prêt pour cpmmfmt, et admission des pools (`pool_gate`)

- `cpmmcost` et `cpmmfmt` 0.1 (MANIFEST 61060231, PASS R02 ; exécution A4 bloquée par la plateforme) utilisent le
  même décodeur `cpmmx` 0.1. `frozen_check` exige ses fichiers audités à l'octet près : curve 5836f2fb, events
  2178f3fd, timeline 13d33917, ainsi que closedacct 0.2 (c6b4d78c).
- Admission d'un pool (G-0 par pool, exclusions U-4). Un motif est publié pour chaque exclusion. Conditions :
  - toutes les transactions sont décodées ;
  - chaque swap est reproduit à l'unité près avec les taux de l'AmmConfig (C-1 sur le pool ; C-3 ; un changement de
    taux exclut le pool) ;
  - les réserves sont chaînées avec les parts de l'AmmConfig (C-2 : un swap manquant ou un dépôt direct exclut le
    pool) ;
  - aucun frais de transfert (Token-2022) ;
  - un seul côté pour les frais de créateur.

## Critères gelés du pilote (`pilot_verdict`, § 2.5, dans l'ordre)

1. Si G-0 (C-1 à C-3 des swaps du pilote, entrée ancrée) n'est pas `true` : STOP, aucun nombre publié.
2. Si n < 30 ou s'il y a moins de 20 pools : INCONCLUSIF.
3. Borne haute unilatérale à 95 % du net moyen (bootstrap de 10 000 tirages groupés par pool, graine = les 8 premiers
   chiffres hexadécimaux de l'ancre de gel ; fonction auditée `w2arms.ce.lower_bound`) : si elle est < 0 → NO-GO.
4. Sinon GO_PILOTE. Ce GO autorise seulement à PROPOSER une confirmation préenregistrée, sur une fenêtre nouvelle,
   avec les critères c1 à c5 du Dossier B. Il ne veut jamais dire « rentable ».

Étiquettes : MASTER_RESEARCH_PAPER / HISTORICAL_REPLAY. Ces cycles ne comptent jamais pour les seuils de 50 cycles et
20 créateurs.

Essais : R-CP1 et son placebo = 1 essai, au moment de l'évaluation seulement (168 → 169 ; plafond 170). `trials()`
refuse tout dépassement.

## Tests et mutants

- 13 tests, dont une chaîne complète : transactions brutes synthétiques (simulateur indépendant de `cpmmx`), puis
  décodeur, admission et coût.
- Mutants : 28/28 détectés (`MUTATIONS_cpmmcost_v0_1.json`). Ils couvrent la latence 0, H-1 en meilleur cas (achat et
  vente), un seul état, des frais × 0, des frais de transaction, des échecs, une fermeture WSOL ou un nettoyage
  oubliés, un loyer conservé, l'univers, l'AmmConfig, les gardes de sortie, l'admission, G-1 (n, pools, borne, signe),
  G-0, le plafond d'essais et le code gelé.
- Garde non mutable déclarée : le recoupement avec closedacct, une identité par construction.

Commande, depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<latelab_pkg>:<cdgate_pkg>:<closedacct_pkg>:<w2arms_pkg>:<cpmmx_pkg>:<cpmmcost_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m pytest <cpmmcost_pkg>/cpmmcost/tests -p no:cacheprovider -q -W error`

## Ce qui reste bloqué (propriétaire / R02)

- Ancrage du protocole v1.2 et de la note v0.2 par R02.
- Source de la liste U-2 : hôte Raydium ou crédits Helius.
- GO de l'étage 0 (≤ 100 crédits), puis de l'étage 1 (≤ 50 000 crédits).
- Chiffrage de R03 pour 24 pools.

Sans ces points : WAIT.

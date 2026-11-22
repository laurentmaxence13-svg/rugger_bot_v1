# Protocole préenregistré — PAPER prospectif du MASTER gelé en flux réel (PAPER_LIVE), v0.2

RUGGER 01, 22/11/2026. Tâche P3-d (R04, 21:32Z). C'est une **conception seulement** : rien n'est branché, collecté
ni lancé.

**v0.2 = v0.1 (0c3e9628) + décisions de R02 (21:36Z).** R02 a FIXÉ les seuils de S-1, S-3 et S-5 et la durée
AVANT toute donnée. Il ajoute (a) l'arrêt sur tout changement de sha, (b) le reçu de cycle obligatoire pour compter
en 50/20, (c) l'affichage en PROSPECTIVE_PAPER. Le reste de la v0.1 est accepté.

## 1. Objet

On observe en temps réel le MASTER **gelé** (politique de W1, sans aucune modification) et on produit des cycles
PAPER BUY/SELL coûtés. Les outils sont déjà audités :
- `rtgate` 0.2, PASS : complétude du flux, défauts de livraison, rollback ;
- `papercost` (primaire) : garde de 2 %, H-1, loyer, fermeture, WSOL, positions marquées et comptées ;
- `mevsens` : N-6, en sensibilité seulement.

Ce que le protocole exclut :
- aucun ordre réel, aucune signature, aucun envoi ;
- aucun mot « rentable » ;
- aucun réglage de paramètre au vu d'un résultat.

**Essais.** 0 tant que le MASTER est inchangé : ce n'est pas une règle nouvelle, c'est l'observation prospective de
la règle gelée. Toute variante est un nouvel essai, avec un nouveau protocole, sous le plafond de 170 hors HW1.

## 2. Étiquetage

| Étiquette | Contenu | Compte pour 50 cycles / 20 créateurs |
|---|---|---|
| **PAPER_LIVE** | Cycles décidés sur le flux réel, au fil de l'eau, par le MASTER gelé, enregistrés avant toute relecture | **OUI, seulement** s'ils sont qualifiés au sens du `POLICY` gelé (seuils jamais abaissés) ET après le reçu de cycle de R02 (`cycle_receipt`, comme dans DOSSIER_W1) |
| HISTORICAL_REPLAY | Tout rejeu, y compris le rejeu du flux enregistré de PAPER_LIVE (contrôle R-1) | NON |
| MASTER_RESEARCH_PAPER | Intentions de recherche | NON |
| Démonstrateur DexScreener | Hors MASTER | NON |

- Dans Rugger Wallet, PAPER_LIVE s'affiche dans la section `PROSPECTIVE_PAPER` (ACCEPTÉ par R02), aujourd'hui vide.
  Il n'apparaît **jamais** dans la section REAL. Le test T-14 étendu est **obligatoire** avant tout branchement.
- Un enregistrement PAPER_LIVE porte : `label`, `source=live_stream`, `segment` (période de flux continu), `engine`
  (sha de paperstream, rtgate, papercost et du MASTER), `creditable: false` et
  `counts_for_operational_master`. Ce dernier vaut `false` tant que R02 n'a pas émis le `cycle_receipt` du cycle ;
  il ne devient `true` que si le reçu existe ET que le cycle est qualifié au sens gelé.

## 3. Durée (FIXÉE par R02)

- Fenêtre fixe de **14 jours** de flux. T0 est ancré par R02 avant le démarrage. Aucune prolongation.
- Pas de prolongation après regard. Une interruption ne prolonge pas la fenêtre : elle devient un segment
  INCOMPLET.
- Le rapport final tombe à T0 + 14 j, quel que soit le nombre de cycles. Si les seuils 50/20 ne sont pas atteints,
  le constat est **WAIT**, avec le décompte.

## 4. Critères de réussite (techniques, fixés d'avance ; aucun critère économique)

| # | Critère | Seuil (FIXÉ par R02 le 22/11 à 21:36Z, sauf S-2, S-4 et S-6, acceptés) |
|---|---|---|
| S-1 | Couverture : part des pools créés dans la fenêtre que rtgate termine COMPLETE | ≥ 95 % ; motifs INCOMPLET publiés ; une position ouverte dans un pool qui finit INCOMPLET est valorisée à **0** et COMPTÉE dans la publication des coûts |
| S-2 | Rapprochement : le rejeu hors ligne du flux brut enregistré, par le même code, redonne CHAQUE cycle PAPER_LIVE octet pour octet ; journal à résidu nul ; le sha du code et de l'environnement reste celui ancré à T0 | 100 % ; un seul écart = ÉCHEC ; tout changement de sha pendant la fenêtre = ARRÊT dur (ajout a) |
| S-3 | Budget de latence : réception → décision, mesuré par horloge monotone, pour les événements décidés | p95 ≤ 4 slots (≈ 0,86 s) ; le p99 est publié ; au-delà, le cycle est étiqueté `latency_budget_exceeded` et le constat le dit |
| S-4 | Aucun module de signature ou d'envoi importé ni appelé | Contrôle au démarrage et à chaque heure ; un seul manquement = ARRÊT |
| S-5 | Fraîcheur SOL/USD : décisions bloquées `sol_usd_stale` | ≤ 5 % |
| S-6 | Coûts : net publié en primaire (rent_lost) ET en compte fermé, avec les scénarios N-6 en sensibilité | Publication seulement ; aucun seuil |

Le protocole « réussit » si S-1 à S-5 passent. Cela prouve que la chaîne PAPER temps réel fonctionne. Cela ne prouve
aucune rentabilité.

## 5. Rapprochement

- Chaque cycle PAPER_LIVE est reconstruit depuis son journal (DECISION, BUY, SELL ou MARK) ; ses coûts ont un
  résidu nul.
- Contrôle R-1 (S-2) : le flux brut est rejoué une fois en fin de fenêtre, étiqueté HISTORICAL_REPLAY. Il doit être
  identique aux enregistrements.
- R02 tire et recalcule un échantillon.
- Les fichiers de journal sont ancrés par R02 chaque jour (sha).

## 6. Journalisation

- Notifications brutes du flux, avec l'heure de réception (horloge murale + horloge monotone).
- Corps bruts `getTransaction`, avec sha256 (O-3).
- Enregistrements rtgate, décisions, WAIT avec leurs motifs, points SOL/USD utilisés.
- Un fichier par heure, chaîne de sha (chaque fichier porte le sha du précédent), MANIFEST quotidien.
- **Aucun secret** : la clé du fournisseur reste en mémoire de processus ; les journaux sont balayés avant
  ancrage ; une fuite provoque l'ARRÊT et un rapport.

## 7. Arrêts (durs, déclarés d'avance)

1. Crédits ≥ 98 % du plafond accordé : arrêt, état écrit, reprise refusée sans nouvel accord.
0. Tout changement de sha du code, des dépendances ou de l'environnement pendant la fenêtre : ARRÊT dur, rattaché à S-2 (ajout a de R02).
2. Un manquement à S-4 (module de signature ou d'envoi) : arrêt immédiat.
3. Un secret dans un journal : arrêt immédiat et rapport.
4. INCOMPLET > 20 % des pools sur 24 h glissantes : arrêt, diagnostic.
5. Hôte ou flux coupé > 30 min : le segment est clos ; reprise en NOUVEAU segment, jamais de rattrapage.
6. Dérive d'horloge > 2 s par rapport à l'heure de bloc médiane : pause.
7. Disque à 90 % : arrêt propre.

## 8. Limites déclarées

- NOTRE atterrissage n'est pas observé (pas d'ordre). L'atterrissage reste modélisé, avec H-1 et 4 slots.
- N-6 (MEV, Jito) n'est pas observable en PAPER : `mevsens` en donne des scénarios déclarés, non calibrés.
- Les positions qui migrent vers CPMM sont comptées à valeur nulle tant que le décodeur CPMM n'est pas certifié
  (C-1).

## 9. PRÉREQUIS DU PROPRIÉTAIRE — BLOQUÉ PAR LE PROPRIÉTAIRE (rien n'est lançable sans eux)

| # | Décision | Pourquoi |
|---|---|---|
| D-1 | Hôte 24 h, et son coût | Un runner GitHub Actions ne convient pas (O-12) |
| D-2 | Source du flux : websocket fournisseur + `getTransaction` par transaction, ou abonnement au niveau transaction | O-3 ; le décodeur gelé exige les instructions internes |
| D-3 | Plafond de crédits ou de dépense de la fenêtre | O-15 ; arrêt à 98 % |
| D-4 | Source SOL/USD en direct (Pyth, via quel accès) | O-8 ; la garde gelée doit s'appliquer |
| D-5 | Gestion du secret : clé inaccessible aux agents ; retrait du secret Helius de l'environnement R03 | O-13 ; état unique § 2 |
| D-6 | Interface unique d'affichage (décision D4 : Streamlit, Render ou Vercel) | O-14 |
| D-7 | Texte d'autorisation écrit dans la session de l'agent exécutant | Contrôle d'accès de la plateforme (cf. A4) |

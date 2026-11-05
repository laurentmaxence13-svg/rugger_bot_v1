# RUGGER 03 — protocole préenregistré LaunchLab → CPMM (issue #158)

Statut : **BROUILLON**, à figer par le propriétaire (SHA du commit enregistré) **avant toute collecte**. Aucune collecte, requête réseau, secret, dépense ni trade n'a eu lieu. Spécification machine : `benchmarks/rugger03_prereg_v1/protocol.json` ; tests : `tests/test_rugger03_protocol.py` (8 tests offline).

**Rentabilité de MASTER : NON DÉMONTRÉE.**

## 0. Correction du rapport #152
Le #152 disait qu'aucun moteur MASTER n'existe. C'est exact pour *cette* branche/`main`, mais **MASTER existe sur d'autres branches** (démontré par `git ls-tree`) : `origin/feat/master-live-integration-20261029` (`bot/master_decision.py`, `master_positions.py`, `master_comparison.py`, `master_audit.py`, tests associés) et `origin/integration/consolidation-20261103` (idem + `bot/live/helius_signed_master_paper.py`). Son statut documenté est `EXPERIMENTAL_SHADOW_NOT_PROMOTED` et il exige déjà ≥50 cycles / 20 groupes de créateurs. Par ailleurs `docs/research/MASTER_FEATURE_RECONSTRUCTIBILITY.md` (branche `claude/dev-20261103-master-feature-reconstructibility-v1`) montre qu'un MASTER authentique **n'est pas reconstructible depuis les seuls TradeEvents** (USD, holders, historique créateur manquants). Non exécuté ici : exécution réelle de ce code = inconnue.

## 1. Critères vérifiables
**Créateur indépendant vérifié** : création signée réussie avec instruction LaunchLab reconnue, signature+slot, concordance mint/pool ; portefeuille distinct, non financé par un autre créateur de la cohorte (fenêtre de recul déclarée à l'avance), pas de fee payer partagé ; un lancement compté par créateur. Financement inconnu ⇒ *non vérifié indépendant*. Objectif : **≥ 50**.
**Cycle exploitable** : BUY PAPER à l'instant de décision avec données `available_at ≤ décision`, SELL PAPER par règle fixée d'avance, devis/réserves horodatés à taille exacte, source-time connu, frais complets connus. Coûts inconnus ⇒ exclu du P&L mais **conservé au dénominateur**. Objectif : **≥ 20**.
**P&L net** : lamports/Decimal ; frais pool/courbe, frais de base, priorité, rent ATA, slippage vs devis, tentatives échouées, latence (hypothèse en slots déclarée d'avance, sensibilité ×1 et ×2). SOL natif, pas d'USD sans source horodatée.

## 2. Comparaison MASTER vs référence
Mêmes observations, décisions figées avant résultats, split chronologique 50 % développement / 50 % holdout intouché. Métrique : P&L net moyen par observation éligible (WAIT = 0), différence appariée, bootstrap par grappe de créateurs, IC 95 %, graine déclarée. **Rentabilité déclarée démontrée seulement si** : borne basse IC95 holdout > 0, P&L net total MASTER > 0, objectifs 50/20 atteints, exclusions pour coût inconnu ≤ 20 %. Sinon : non démontrée.

## 3. Biais
Survie (pools disparus), ordre de l'API de découverte, look-ahead (USD, historique créateur, holders tardifs), devis ≠ exécution, heure de réception ≠ heure chaîne, régime d'une fenêtre courte, tests multiples sur variantes (`early_sniping`, `confirmed_momentum`, `adaptive_hybrid`), grappes Sybil, holders inconnus traités comme 0.

## 4. Voie gratuite vs Helius
- **Gratuit** (RPC public + API Raydium anonyme, déjà sondés dans `P3_DATA_READINESS_REPORT.md`) : suffisant pour une **faisabilité bornée**. Observé : sur 5 signatures LaunchLab récentes, 4 transactions échouées et 1 réussie sans création vérifiée → **0 création vérifiée sur 5** ; rendement de découverte très faible, donc 50 créateurs par RPC public non garanti. Limites : quotas non garantis, rétention, pas de backfill complet, pas de quantité de requêtes mesurée pour 50 créateurs (**inconnu**).
- **Helius** : non utilisé. Estimation = `requêtes × crédits/requête` (fonction testée `helius_credits`). Je n'ai **pas** de barème de crédits vérifié ici et n'invente ni crédits ni prix : à relever sur la grille officielle par l'utilisateur. Ordre de grandeur de requêtes à mesurer d'abord par un pilote gratuit borné : (signatures à parcourir pour 1 création) × (pages) + 1 `getTransaction` par candidat + lectures de pool/migration + devis. Décision d'abonnement à demander **seulement** si le pilote gratuit montre qu'il ne peut atteindre 50 créateurs dans la fenêtre.
- Budget autorisé actuel : **0 $**.

## 5. Prochaine mission recommandée
(a) Le propriétaire fige ce protocole (commit SHA). (b) Pilote gratuit borné et préenregistré (nb max de requêtes déclaré) mesurant le rendement créations/requête et les migrations CPMM observables. (c) Port/rejeu de MASTER (depuis `feat/master-live-integration`) et de la référence sur un même journal, en offline d'abord. (d) Seulement alors, demande d'autorisation Helius chiffrée avec le barème officiel.

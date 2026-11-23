# cpmmpilot 0.1.6 — g1ind 0.6 et vente nulle corrigée (R03), HORS LIGNE uniquement

Cette version répond à l'audit R02 6f071c5a (K-1 erratum, K-2) et à la décision de R02 de 22:07Z. Aucun appel réseau : `rpc.LiveRpc` lève toujours une erreur.

## Changements par rapport à 0.1.5

1. **K-1, erratum de R02.** `zero_sale_net_lamports(failures)` reproduit la composition gelée de `cpmmcost.position` (l. 231-238) avec received = 0 :
   - achat, `(1 + f.buy)` transactions ;
   - vente, `(1 + f.sell)` transactions ;
   - fermeture WSOL ;
   - nettoyage : si `f.cleanup == CA.MAX_CLEANUP_ATTEMPTS`, `f.cleanup` transactions plus le loyer perdu (`TOKEN_ACCOUNT_RENT_LAMPORTS` = 2 039 280) ; sinon, `(f.cleanup + 1)` transactions sans loyer.

   Valeurs :

   | Échecs | Vente nulle (lamports) |
   |---|---|
   | (0,0,0) | −100 420 000 |
   | (1,1,1) | −100 735 000 |
   | (0,0,3) | −102 669 280 (0.1.5 donnait −100 735 000) |
   | (0,0,2) | −100 630 000 |

   Ces valeurs sont recoupées par `closedacct.net_return_closed`. La signature et la forme des lignes ne changent pas : g1ind ≥ 0.5 importe cette fonction.
2. **K-2.** g1ind 0.6 (3d9166d, MANIFEST cda05131) remplace la 0.3. L'import se fait dans `step1.g1`, pour éviter un cycle avec g1ind, qui importe `cpmmpilot.step1`.
3. **P1, admis par R02.** `decision_slot` est copié depuis la timeline avant `zero_sale`.
4. **P2, admis par R02.** `cut_time = t0_time + int(D × 86 400) // 2`, un entier, est inscrit dans les deux fiches de gel et passé à g1ind.
5. **Test de bout en bout step1 → g1ind.** Des ventes nulles sont injectées dans le primaire, le témoin, « 1 échec » et « loyer perdu ». Le test vérifie :
   - les valeurs ligne à ligne ;
   - `decision_slot` ;
   - les mêmes décisions dans toutes les sensibilités ;
   - la décision dans {STOP, INCONCLUSIF, NO-GO, GO_PILOTE} pour RCP1 et B1 ;
   - les moitiés au `cut_time` de la fiche.

## État des vérifications (hors ligne, `unshare -rn`)

- **Contre g1ind 0.6 publiée (3d9166d) :** 27 tests sur 28 passent. L'échec attendu est `zero_sale_value_is_not_the_rule:rent_lost_vs_closed_account`, parce que le `RUN_FAILURES` de g1ind 0.6 n'a pas encore la clé « loyer perdu ». R02 a demandé l'ajout à R01 (g1ind 0.6.1).
- **PRÉ-CONTRÔLE, non livré :** une copie locale de g1ind 0.6 avec cette seule ligne ajoutée. Résultats :
  - 28 tests sur 28 passent ;
  - 35 mutants sur 35 sont tués (`MUTATIONS_cpmmpilot_v0_1_6.json`, base = pré-contrôle) ;
  - répétition synthétique : journal e8c73c03…, 27,3 s.
- **À refaire sur g1ind 0.6.1 dès qu'elle est poussée :** tests, mutants et répétition.

Nouveaux mutants :
- `rent_forgotten_at_cleanup_3` ;
- `cleanup_branch_never` ;
- `zero_sale_without_wsol` ;
- `zero_sale_failures_ignored`, réécrit.

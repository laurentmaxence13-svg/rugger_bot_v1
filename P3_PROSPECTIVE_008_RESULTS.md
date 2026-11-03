# P3 — contrôle008 effectivement exécuté

28 octobre 2026. Code récupéré puis publié `cc38e546`, durci/testé `39fe7fd0`.
Plan préenregistré et relu depuis GitHub `917a4541` avant le premier appel.
PR22 ouverte, sans fusion. Aucun ancien contrôle répété, aucun ordre/dépense.

| Mesure réelle | Résultat |
| --- | --- |
| Budget global utilisé |20/20 appels,24,825s/60s|
| Index reçu / candidats fixés avant résultats |100 lignes /3 mints distincts|
| Analysés / achats indicatifs1SOL |3/3 ; budget modèle total3SOL, jamais dépensé|
| Demandes intégrales, deux horizons |6 ; toutes INSUFFICIENT_LIQUIDITY|
| Diagnostics Q//4 préfixés |3 ; tous INSUFFICIENT_LIQUIDITY|
| Sorties intégrales/partielles cotées |0/0 ; aucune liquidation|
| Banks cohérents observés |462270186 et462270261|
| Créateurs déclarés / indépendance |2 ; indépendance non démontrée|
| Cycles économiques qualifiés / P&L net |0 / inconnu|
| Preuves |55 événements ;12 bundles/1694 événements cumulés|

Quantités attendues conservées dans l'ordre de découverte :31973987104815,
34193904632554 et31973987105824 unités atomiques. Les quantités minimales restent
distinctes. Chaque Q entier a été demandé initialement puis au suivi, et Q//4
fixé avant la première vente. Aucun ajustement pour obtenir une quote favorable.

Les refus ont une explication compatible avec les banks : real_a=0 pour les trois
pools, et real_b initial7/0/6 lamports. L'achat hypothétique n'a jamais eu lieu :
le fournisseur ne voit pas son effet. Les neuf refus ne prouvent donc pas que
la même position serait invendable après son propre achat.

Le modèle local existant ajoute explicitement l'achat puis sa réversion sans
activité intermédiaire : sorties888306249 /975156249 /888306249 lamports pour
1e9 engagés. Pertes de courbe conditionnelles respectives0,111693751 /0,024843751 /
0,111693751SOL, **avant frais additionnels inconnus**. Frais de courbe5,75%/1,25%/
5,75% par swap. Ce modèle mesure une friction structurelle ; il ne fournit ni
sortie future observée, ni P&L net de marché, ni avantage de stratégie.

La collecte est techniquement complète selon son programme ; la qualification
économique reste insuffisante : heures/slots source des devis absents, création
non recherchée dans ce budget, coûts propres non établis, aucune quote de sortie.
Les blockTime RPC ne remplacent pas l'horloge fournisseur. Un autre swap peut
documenter des frais de référence, jamais les frais de notre scénario.

Corrections vérifiées : budget unique RPC/index/quotes ; refus logique distinct
d'une erreur réseau ; aucune continuation après timeout/transport/HTTP invalide ;
bank malformé/slot périmé arrête le programme ; endpoint partagé lié au plan ;
rapport zéro candidat possible après erreur initiale ; préfixe immuable et
liens inventaire/quantité contrôlés. Les paramètres agressifs actifs sont conservés.

Validation du checkpoint récupéré :1590 passed,1 skipped,242 subtests,6,37s,
warnings en erreur ;79 tests ciblés ensuite incluant le parcours complet trois
candidats à20 appels et refus du bank non avançant. Réseau exclu des tests.

Fichiers : `validation/P3_PROSPECTIVE_008_REPORT.json`,
`evidence/p3/prospective_008/`, plan machine et protocole associés.
Suite utile : replay ancré et rapprochement des projections, moteur comparatif
P4 sur données as-of et supervision/reprise P5. Aucune nouvelle collecte implicite.
**P3 reste OUVERT ; aucun bénéfice de marché démontré.**

# Master V2 : comparaison référence/Master mesurable

28 octobre2026, Europe/Paris. Base distanteb680b90 vérifiée, PR22 ouverte.
Les cinq composants précédents sont conservés. Aucun paramètre actif modifié.

Le comparateur réutilise `_run_arm`, `record_quote`, l'inventaire et les limites
financières existants. Deux livres en mémoire simulent deux décisions différentes;
il n'existe pas de seconde implémentation comptable ou de portefeuille actif.
Les observations et budgets de départ10SOL sont identiques. La référence applique
le scorer actuel, les TP/SL/trailing/durée et10%du capital réconcilié. Le Master
utilise ses trois stratégies et positions. Les devis sont propres au lot/budget.

`python -B -m bot master-compare --input INPUT.json --output OUTPUT_NEUF.json`
reçoit `{corpus,plan}`. `make_plan` fige coupures, horizon30s–1h, hashes des
politiques et sensibilités optionnelles frais×1/×2,délai0/250ms. Le corpus est
borné1000frames. Aucun classement ni promotion. Les snapshots sont écrits avant
le pas de règlement et les résultats restent séparés. Il s'agit de replay
rétrospectif conditionnel, pas d'une preuve de publication prospective préalable.

Les refus, reliquats, abstentions et coûts inconnus sont conservés. Une abstention
a zéro cashflow engagé; cela ne transforme pas un résultat token inconnu en
zéro gain/perte. Les deltas ne sont calculés que sur des lots complètement
liquidés aux frais connus ou des bras sans entrée. Aucune valeur de marché ne
remplace des produits de vente cotés à quantité exacte. Les données observées
ne contiennent pas l'effet de notre propre achat hypothétique.

## Comparaisons synthétiques vérifiées

| Cas | Référence | Master | Conclusion admissible |
| --- | --- | --- | --- |
| Features connues, preuveéconomiqueMaster absente |Entrée/sortie,+0,199985SOL |WAIT,0cashflow |Coût d'abstention synthétique0,199985SOL |
| FixtureMaster qualifiée, TP |Lot exact totalement vendu |Même lot vendu |Delta0; frais15000ou30000lamports selonstress |
| Momentum dégradé, REDUCE |Unevente,+0,199985SOL |Deuxventes,+0,149975SOL |Delta−0,050010SOL, dont10000lamports de coûts supplémentaires |
| Vente refusée |Lot restant, nettotalUNKNOWN |Lot restant, nettotalUNKNOWN |Aucun deltapositiffabriqué |
| Capitalréférence aprèsun gain |Budgetsuivant1,0199985SOL |DécisionpropreMaster |Devis1SOL nonredimensionné, refus si devis exactabsent |

P4paired_validation optin préenregistre24hypothèses et alpha0,05/24. Les candidats
sont figés en développement, puis comparés aux références surholdout parmint et
parcréateur sous4conditions. Aucun pvalue/intervalle surfixture, indépendance
noncertifiée ni gagnant. Un scénario natif distinct mesure+60000000lamports
synthétiques pourun candidatTP7figé faceàréférence; pasuneperformance de marché.

## P3 et P5

P3 : protocole acquisition20appels/60s, checkpointsfeatures retenus dans le
CaptureStore, rejoués avec refs causales et bytesRPC lorsqu'elles existent.
Création reparsée depuis transaction liée, coûts propres asof, quotes et refus
retenus. Absence debytes/preuve resteUNKNOWN. Producteur nonbranché à une boucle
réseau; aucune collecte. Voir MASTER_P3_ACQUISITION.md.

P5 : journal12champs avantoutcomes, désaccords etlatences locales enlectureseule.
Endurance propose désormaisun pacing mural borné; horlogedonnées synthétique
explicitement séparée. Les rapports muraux et sources seront sauvegardés après
mesure. Aucune disponibilité24h/24 démontrée.

## Validation et limites

Suite complète1910passed,1skipped,242subtests,12,20s,warnings en erreur,stderr0 :
`python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error`.
Copiejetable sansréseau/.env/DButilisateur. Contre-revue indépendante a identifié
puisretesté deux défauts : fraisstressés visibles seulementaprèsdécision et
intentionsréférenceHOLD malgréTP. Corrigés avantcheckpoint.

P3resteouvert :0cyclemarchéstrictementqualifié,0nouvelleobservationmarché. Manquent
preuves temporelles/provenance/identité/création seloncas, fraispropres, sorties
cohérentesavecentreé et corpusindépendant. Aucun ordre/signature/dépense/fusion.
Les classifications nouvelles sont descriptives; ne pilotent pas le classement
Core sans validation séparée. L'état P4/P5 restepartiellementvalidé.

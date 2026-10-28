# Master V2 : comparaison mesurable et endurance finalisée

28 octobre 2026, Europe/Paris. Point de reprise vérifié sur GitHub :
`a51850e0607d8160d1ae0dadf22fae6f3dcedc49`. PR #22 ouverte, sans fusion.
L'arbre local était propre : le comparateur et ses tests étaient déjà publiés.
L'optimisation d'endurance annoncée avant interruption restait à écrire.

## Endurance avant/après à conditions identiques

Deux copies de sources jetables utilisent le même Python, les mêmes dépendances,
1 000 événements, 10 reprises, 20 opérations de backup et une cible de pacing de
30 secondes. Seule l'implémentation de master_endurance.py varie. Les copies des
autres sources ont été vérifiées identiques. Ordre : avant, puis après ; une paire
locale, sans inférence statistique ni mesure de performance de marché.

| Mesure | Avant | Après |
| --- | --- | --- |
| Durée murale de la boucle |120,246360 s |30,278584 s |
| Reconstructions du rapport détaillé |1 031 |1 |
| Événements, doublons, conflits, rollbacks |1 000 chacun |1 000 chacun |
| Reprises et snapshots immuables |10 et 10 |10 et 10 |
| Invariants vérifiés |7 054 |7 054 |
| Chaîne de décisions et états financiers |Identiques |Identiques |

Réduction mesurée de 74,8 %, ratio 3,97. Le pacing impose un plancher de 30 s.
Les contrôles intermédiaires lisent les vrais compteurs SQL au lieu de recalculer
tous les JSON. Le rapport détaillé reste validé en fin de test. Les contrôles de
capital, d'inventaire, de rollback et de sauvegarde restent exécutés à chaque
étape prévue. Aucun de ces contrôles n'a été remplacé par un échantillonnage.

La mesure antérieure à l'interruption, 117,982710 s, est conservée séparément.
La référence de la paire contrôlée ci-dessus est 120,246360 s. Aucun de ces tests
ne démontre une disponibilité de production 24 h/24.

```sh
python -B tools/benchmark_master_endurance.py --baseline-ref a51850e0607d8160d1ae0dadf22fae6f3dcedc49 --output /tmp/rugger-new-endurance-pair --events 1000 --restarts 10 --wall-seconds 30
```

L'outil ne récupère aucune révision réseau. Sur le workspace Cloud, la référence
Git locale équivalente est `273c6b755eb43b2d5f2c510eb4c1b30a16f5bf42`, arbre
`a04ea5560492f846682cdfe2f08b52e72bea0d25`. Les SQLite synthétiques restent
locales ; seuls les rapports JSON et les sources sont publiés. Un test court
supplémentaire valide le contrôle des copies avec 4 événements et 2 reprises.

## Comparaison fonctionnelle

| Critère | Moteur actuel | Master Trader | Conclusion admissible |
| --- | --- | --- | --- |
| Détection |Scanner LaunchLab existant |Même bande d'observations |Aucun avantage de détection démontré |
| Entrée |Scorer courant et gardes |Trois variantes, WAIT/NO_TRADE, preuves exigées |Désaccords figés avant le replay du résultat |
| Stratégie |Politique de référence |Priorité de régime figée ; neuf classifications descriptives |Aucun gagnant de marché |
| Taille |10 % du capital réconcilié, dans les limites |Quatre budgets admissibles, coûts et capacité de sortie |Devis propre au montant ; aucun redimensionnement |
| Sorties |TP, SL, trailing, durée et risques |Protections conservées ; HOLD, REDUCE et urgence |Une réduction peut dégrader le net |
| Coûts |Ledger natif ; inconnues conservées |Même comptabilité ; stress visible avant décision |Coûts propres de marché encore inconnus |
| P&L net admissible |Inconnu sur le marché |Inconnu sur le marché |Zéro cycle de marché strictement qualifié |
| Risques |Capital, perte quotidienne, créateur et sources |Gardes conservées et abstention possible |Aucun paramètre actif modifié |
| Robustesse |RPC/WS, ledger et supervision existants |Journal comparatif, reprises et latences locales |Endurance locale validée ; exploitation continue inconnue |

Deux livres isolés utilisent la même implémentation financière : `_run_arm`,
`record_quote`, l'inventaire atomique et les limites existantes. Aucun portefeuille
actif n'est ouvert. Les bras commencent chacun avec 10 SOL. Chaque décision est
retenue avant son pas de règlement simulé ; le replay rétrospectif ne prouve pas
une publication prospective antérieure aux observations de marché.

`master-compare` reçoit `{corpus, plan}` ou `{acquisition, plan}`. Le plan fige
coupures, horizon de 30 s à 1 h, politiques et sensibilités optionnelles de frais
×1/×2 et délai 0/250 ms. Le corpus est limité à 1 000 frames. Le split utilise la
première disponibilité de l'identité ; une identité future ne peut pas exclure
un candidat passé. Les créateurs communs sont exclus du holdout.

## Comparaisons économiques synthétiques

| Cas | Référence | Master | Ce que le test mesure |
| --- | --- | --- | --- |
| Preuve économique Master absente |Entrée puis sortie : +0,199985 SOL |WAIT : aucun cashflow engagé |Coût d'abstention conditionnel de 0,199985 SOL |
| Fixture Master qualifiée puis TP |Vente de tout le lot |Même lot vendu |Delta zéro ; frais de 15 000 ou 30 000 lamports |
| Momentum dégradé |Une vente : +0,199985 SOL |Deux ventes : +0,149975 SOL |Delta −0,050010 SOL, dont 10 000 lamports de frais supplémentaires |
| Vente refusée |Reliquat, net total inconnu |Reliquat, net total inconnu |Aucun delta total inventé |
| Gain suivi d'une nouvelle entrée |Budget suivant de 1,0199985 SOL |Décision propre au Master |Le devis de 1 SOL n'est pas redimensionné ; refus si le devis exact manque |

Ces trajectoires servent à vérifier les mécanismes, pas à choisir un réglage
rentable. Les 14 lignes de résumé comprennent les partitions et sensibilités
des quatre cas, sans représenter 14 opportunités de marché indépendantes.
Les deltas exigent des lots entièrement liquidés aux frais connus, ou un bras
sans entrée. Zéro cashflow engagé ne donne pas une valeur nulle à un token dont
le résultat demeure inconnu. Les devis ne prouvent pas des fills ou l'effet futur
de notre achat hypothétique sur une bank réellement observée.

## Avancées P3, P4 et P5

P3 conserve désormais une référence causale à la santé locale dans CaptureStore.
Une source future, périmée ou contradictoire n'autorise pas l'entrée. Les frames
journalisées retiennent les états de santé et de capital utilisés, avec les
inconnues. L'enveloppe complète passe au comparateur sans perdre refus, candidats
sans features ou dénominateur. Ces états restent des attestations locales, sans
authentification du fournisseur externe. Aucun hook réseau n'a été activé.

P4 évalue 24 candidats en développement, puis les candidats figés et leurs
références sur un holdout séparé par créateur. Le protocole optionnel préenregistre
une famille de 24 hypothèses, alpha 0,05/24, et quatre conditions frais/délai. Le
rapport sauvegardé contient 12 contrastes : trois candidats figés × quatre
conditions. Le holdout ne sert pas à classer les 24 candidats. Aucune p-value,
aucun intervalle de confiance ni aucune indépendance certifiée ne sont attribués
aux fixtures. Un test distinct mesure +60 000 000 lamports conditionnels pour
un candidat TP7 figé ; cela ne démontre aucun avantage sur le marché.

P5 conserve les snapshots comparatifs de douze champs avant résultats, les
désaccords expliqués et les premières latences locales mesurées. L'optimisation
porte sur le test d'endurance, sans changer la comptabilité ni les protections.

Les archives disponibles contiennent 8 banks, 4 mints et 2 sessions, dont 6 banks
avec identité qualifiée. Ces comptes ont été relus dans la preuve existante,
sans refaire les contrôles 006/007/008. Les coûts propres restent inconnus.
**P3 reste ouvert : zéro nouvelle observation réseau et zéro cycle de marché
strictement qualifié.** P4 et P5 restent partiellement validés logiciellement,
sans validation économique indépendante ni disponibilité continue démontrée.

## Preuves et reprise

`validation/master_v2/MANIFEST.json` ancre les entrées synthétiques, rapports
complets compressés, résumé A/B, rapport P4, mesures d'endurance et validation
finale. La commande publique a reproduit le rapport qualified octet pour octet
après décompression. Aucune base de données n'est téléversée.

Validation finale : **1 915 passed, 1 skipped, 242 subtests**, 12,03 s, warnings
en erreur et stderr vide. Le seul test ignoré exige la base utilisateur absente.

```sh
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
python -B -m bot master-compare --input validation/master_v2/comparisons/qualified.input.json --output /tmp/rugger-new-qualified.json
```

Prochaine priorité : une cohorte indépendante, active et préenregistrée, avec
clocks des devis, provenance des features, coûts applicables et sorties liées
au lot, après vérification des accès et quotas gratuits. Le plan préparé n'est
pas une collecte exécutée. Aucun ordre, signature, dépense, changement de politique
active ou fusion automatique.

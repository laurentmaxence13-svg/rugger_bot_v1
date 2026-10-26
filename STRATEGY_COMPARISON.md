# Comparaison de viabilité : memecoins Solana et trading BTC/SOL

26 octobre 2026 — étude préliminaire, sans collecte de marché ni exécution financière.

**Décision économique : `INSUFFICIENT DATA` pour les deux voies.** La revue du code permet de comparer les contraintes et de définir une expérience. Elle ne permet ni de classer leur rentabilité, ni de recommander une réorientation. Aucun carnet d'ordres, corpus de rendements réellement exécutables, tarif contractuel ou journal de latence fournisseur n'a été inspecté pour cette étude.

La comparaison initiale proposée oppose le sniping LaunchLab à du trading **spot, sans levier**, de BTC/SOL sur une plateforme à choisir. « Trading BTC/SOL » ne définit pas un lieu d'exécution : un carnet centralisé et un DEX Solana ont des coûts et des risques distincts. Les produits dérivés, le financement et les liquidations ne sont pas inclus dans ce premier protocole ; ils exigeraient une étude séparée.

## Ce que le dépôt démontre

Les références suivantes désignent les sources actives, sans utiliser les copies `bot/bot`, `tests/tests` ou les sauvegardes historiques.

| Fait démontré par le code | Conséquence pour la comparaison |
|---|---|
| `bot/scanner/transaction_parser.py:find_raydium_launches` identifie les créations LaunchLab et conserve les identités de chaque mint. | L'univers étudié dépend du protocole et de la capture du scanner ; il n'est pas l'ensemble du marché crypto. |
| `bot/analyser/final_decision_engine.py:SignalFeatures` et `decide` utilisent notamment le créateur, ses ventes/transferts, le momentum, la source de prix et des mesures de liquidité. | Ces heuristiques doivent être évaluées sur leurs propres labels. Elles ne constituent pas une stratégie BTC/SOL prête à l'emploi ni une preuve de détection de fraude. |
| `bot/analyser/launchlab_onchain.py:fetch_onchain_quote` distingue le funding d'une courbe LaunchLab de la liquidité d'un pool DEX. | Le funding observé ne mesure pas à lui seul le montant revendable ni le coût de sortie d'une position. |
| `bot/analyser/paper_trader.py:MarketQuote` conserve des champs optionnels de frais, profondeur, slippage et provenance ; certains restent inconnus. | Un prix indicatif ne suffit pas à construire un simulateur de remplissage pour une taille donnée. |
| `paper_trader._paper_free_capital` rapproche le capital PAPER avec le P&L SOL et les réservations ouvertes. `paper_engine._realized_metrics` mesure une equity réalisée en SOL. | Une comparaison en USD ne peut pas réutiliser ces valeurs en changeant leur étiquette. Le risque de change et la valorisation des positions ouvertes doivent être explicités. |
| `bot/analyser/temporal_split.py:temporal_partition` groupe signatures/timestamps et purge les labels qui ne sont pas connus avant la frontière. | Cette garantie temporelle est réutilisable dans son principe ; elle ne prouve ni l'intégrité d'un carnet BTC/SOL ni l'indépendance d'un test final. |
| `bot/scanner/supervision.py:ScannerHealth` mémorise un refus dans un contexte de supervision. | C'est un mécanisme intraprocessus, pas un contrôle universel de santé de toutes les plateformes ou de tous les processus. |

Les calculs PAPER et leurs tests établissent des propriétés logicielles dans leur périmètre. Ils ne mesurent pas le prix auquel un ordre réel aurait été exécuté. Cette étude n'a exécuté aucun nouveau test ni benchmark ; les résultats techniques de la livraison sont consignés séparément dans les rapports P1 et de validation.

## Comparaison des contraintes

Les différences ci-dessous sont des contraintes de conception et des hypothèses à vérifier sur des lieux d'exécution définis. Aucun classement numérique n'est déduit d'une réputation de marché.

| Dimension | Sniping de nouveaux memecoins LaunchLab | Trading spot BTC/SOL | Preuve nécessaire pour départager |
|---|---|---|---|
| Complexité technique | Création de l'actif, identité du mint/pool, transitions courbe/migration, transactions multiples et événements manquants sont dans le chemin critique. | Un univers de paires connu simplifie l'identification ; un carnet centralisé impose cependant séquences, snapshots, reconnexion, états d'ordre et remplissages partiels. Sur DEX, les contraintes Solana persistent. | Coût de développement et incidents par composant, sur le même périmètre fonctionnel. |
| Données | Il faut conserver les lancements rejetés, les tokens sans prix et les disparitions. L'indexation a posteriori peut masquer ce qui était disponible à l'entrée. | Les trades, carnets et bougies peuvent être disponibles selon le fournisseur ; leur historique et leur qualité ne sont pas garantis par une API live. Des bougies seules ne prouvent pas un fill. | Inventaire horodaté des sources, droits d'accès, rétention, trous, révisions et délai de publication. |
| Coûts d'exécution | Frais du pool/courbe, réseau, priorité, impact, slippage, tentatives échouées et sortie doivent être distingués. | Sur carnet : frais selon compte/type d'ordre, spread, impact, attente, sélection adverse et annulations. Sur DEX : ajouter les frais et aléas de chaîne. | Coût complet par taille et par régime, avec devis ou simulations observables à l'instant de décision. |
| Liquidité | L'indicateur « liquidité » ou le funding ne garantit pas une sortie à la taille voulue ; un actif peut devenir invendable. | Une meilleure profondeur sur certaines grandes paires est une hypothèse raisonnable à mesurer, pas une propriété universelle de BTC/SOL. Elle varie par lieu, taille et période. | Courbes de coût entrée/sortie par notionnel, disponibilité des routes et stress de retrait de profondeur. |
| Manipulation et information | Contrôle du token, concentration, comportement du créateur et coordination peuvent affecter directement la vendabilité ou le prix. Une heuristique n'établit pas une fraude. | Risques de volume trompeur, spoofing, sélection adverse et chocs de marché restent pertinents. Un carnet centralisé ajoute un risque de plateforme et de garde. | Labels documentés, observations antérieures au signal, faux positifs/faux négatifs et analyse par lieu. |
| Pertes extrêmes | Perte quasi totale d'une position et sortie indisponible doivent être des scénarios explicites. Un SL observé ne garantit pas un prix de vente. | Gaps, profondeur disparue, panne, gel des retraits ou défaillance du lieu restent possibles. Sans levier, le risque de liquidation d'un dérivé n'est pas applicable. | Historique de stress pertinent et scénarios d'absence de sortie, avec rapprochement comptable des positions restantes. |
| Concurrence | L'accès au flux, l'ordre d'observation et la qualité de la route de sortie pourraient compter davantage que le calcul local du score. C'est une hypothèse. | Une stratégie lente doit aussi supporter frais et concurrence ; une stratégie rapide exige de mesurer la priorité et la sélection adverse du lieu. | Latences P50/P95/P99, différence entre prix de signal, devis, arrivée et résultat simulé/exécuté autorisé. |
| Avantage statistique | Les fortes variations donnent une dispersion importante ; elles ne déterminent pas le signe de l'espérance nette. | Une série plus régulière ou un actif plus suivi ne crée pas automatiquement une anomalie exploitable. | Évaluation chronologique indépendante après coûts, rejets, absences et incertitude liée aux groupes/régimes. |
| Augmentation des volumes | Chaque hausse de taille peut modifier l'impact et la possibilité de sortie ; une extrapolation linéaire du P&L est injustifiée. | La capacité dépend aussi du lieu et de l'horizon ; la file d'attente et la profondeur limitent le volume exploitable. | Rejouer les mêmes signaux à plusieurs tailles, sans réoptimiser sur le test final. |
| Robustesse | Il faut résister à l'évolution du protocole, de l'univers de tokens, des comportements de créateurs et des fournisseurs. | Changements de régimes, de structure de frais, de règles de plateforme et de concurrence peuvent invalider une stratégie. | Résultats par sous-période, tests de panne et stabilité des paramètres sur fenêtres prospectives. |
| Infrastructure | RPC/WS, historique, stockage brut, indexation et calcul de cotations peuvent avoir des coûts propres. | Carnets détaillés, historique licencié, stockage, connectivité et rapprochement d'ordres peuvent aussi coûter. | Tarifs réellement accessibles, limites de débit et coût fixe mensuel ; aucun abonnement nouveau n'est autorisé par cette étude. |

La baisse d'un délai local ne prouve pas une meilleure exécution : il faut relier cette mesure à l'état du marché encore disponible lors de l'arrivée de l'ordre. Aucun rang concurrentiel, gain de latence économique ou capacité en capital n'est démontré ici.

## Protocole de comparaison équitable

1. **Fixer les produits et les lieux.** Décrire le protocole LaunchLab couvert et une plateforme spot BTC/SOL précise, sans levier. Documenter les règles d'accès et les hypothèses de garde. Ne pas comparer implicitement une cotation DEX à un prix de bougie centralisé.
2. **Fixer le budget de risque et la comptabilité.** Conserver le ledger actuel de Rugger en SOL. Produire une valorisation de recherche secondaire dans une devise commune avec taux horodatés et source connue. Séparer le rendement de la stratégie du simple fait de détenir SOL/BTC. Le témoin « conserver les SOL sans trader » a un P&L SOL nul, mais pas nécessairement un rendement USD nul. Comparer exposition, concentration et pertes extrêmes, pas seulement capital nominal.
3. **Définir un univers disponible au moment du signal.** Inclure lancements/paires rejetés, observations sans prix, échecs et actifs disparus. Geler les règles de missingness. Une observation incomplète peut rendre un trade non évaluable ; elle ne devient ni un gagnant ni une perte nulle par défaut. Publier la couverture et la sensibilité à ces absences.
4. **Geler la recherche avant le test final.** Séparer entraînement, sélection/validation et dernier test ; grouper les événements dépendants et purger selon l'heure réelle de disponibilité des labels. Enregistrer le nombre de règles, horizons et coûts essayés. Choisir les horizons et budgets de recherche avant l'évaluation finale et publier leurs différences entre produits. Ne pas choisir le marché gagnant sur le même holdout qui a servi à choisir ses paramètres.
5. **Modéliser l'exécution par lieu et taille.** Injecter latence, frais, slippage/impact, profondeur et échecs connus. Pour les ordres passifs, conserver attente, non-remplissage et sélection adverse ; pour les ordres agressifs, traverser une profondeur disponible. Prévoir absence de route/sortie et interruption. Un scénario synthétique vérifie le moteur, sans devenir un historique de marché.
6. **Comparer aux témoins préenregistrés.** Ne rien faire, détention de l'actif de compte et une règle simple à exposition comparable. Les témoins doivent avoir les mêmes contraintes d'information et de coût. Mesurer le P&L en unités monétaires, les réservations, le drawdown réalisé et la valorisation des positions ouvertes séparément.
7. **Publier le risque et l'incertitude.** P&L net, espérance, profit factor avec cas dégénérés explicites, nombre de trades/groupes, taux de remplissage, exposition, pires pertes, coût de sortie et drawdown. Estimer l'incertitude par blocs temporels/groupes adaptés ; ne pas traiter des créations liées comme autant d'observations indépendantes. Déterminer la taille d'échantillon à partir de la précision recherchée et de la variance mesurée, sans nombre de trades magique.
8. **Inclure les frais fixes.** Rapporter le P&L net des coûts variables, puis le résultat après infrastructure sur la même période calendaire. Une petite espérance par trade peut ne pas payer la collecte et l'exploitation. Les devis et coûts réels restent à obtenir sans engager de dépense.

Une hypothèse favorable mais dont l'incertitude recouvre zéro, ou dont le résultat dépend d'hypothèses de fills invérifiables, reste `INSUFFICIENT DATA`. Un résultat négatif robuste peut justifier l'abandon de l'hypothèse testée ; il ne suffit pas à condamner tout un marché. Un résultat positif indépendant justifierait seulement une phase PAPER prospective autorisée, pas un passage automatique au réel.

## Noyau commun et deux moteurs indépendants : faisabilité

Le dépôt fournit déjà des invariants utiles : réservations et rapprochement du capital, refus d'entrée en cas de panne, journal des décisions, conservation des erreurs et partition temporelle. Leur extraction éventuelle doit suivre un besoin démontré et des tests contractuels. Il n'est pas nécessaire de réarchitecturer le bot pour terminer P1 ou mener cette comparaison.

| Contrat commun envisagé | Point d'appui existant | Adaptation nécessaire avant réutilisation BTC/SOL |
|---|---|---|
| Observation disponible à une heure déterminée | `SignalFeatures`, provenance de `MarketQuote`, partition temporelle | Séparer instrument, identifiant d'observation, heure de marché, heure de réception et heure de disponibilité. La contrainte actuelle de mint unique ne peut pas identifier des observations répétées de BTC. |
| Proposition de position et contrôle de risque | `Decision`, `entry_allowed`, réservations PAPER | Exprimer taille, devise, coût, exposition et santé du lieu ; les signaux LaunchLab et les seuils actuels restent dans leur moteur. Aucune stratégie ne doit contourner le risque commun. |
| Ledger et rapprochement | `_paper_free_capital`, clôtures atomiques, `_realized_metrics` | Rendre explicites les unités et les soldes par devise/lieu ; ne pas partager automatiquement le même capital entre stratégies. Les métriques SOL actuelles ne sont pas un ledger multidevise. |
| Supervision et audit | `ScannerHealth`, erreurs principales/secondaires, rapports | Conserver un canal de santé par adaptateur et une politique de reprise vérifiée. Un scanner sain ne démontre pas qu'un autre lieu accepte des ordres ou que ses soldes sont rapprochés. |
| Évaluation et résultats | `temporal_partition`, rapports de recherche | Partager les règles de disponibilité/purge et les définitions des métriques ; garder des simulateurs de fills propres au protocole ou au carnet. |

Les adaptateurs de données et d'exécution resteraient distincts : créations et pools Solana d'un côté ; produits, carnet, ordres et remplissages d'une plateforme spot de l'autre. Les signaux, politiques de taille et résultats de chaque moteur devraient être séparés, avec plafonds d'exposition agrégés seulement si un gestionnaire de capital commun est ultérieurement conçu et testé.

**Décision d'architecture : faisabilité plausible, aucun second moteur à développer maintenant.** Le plus petit prochain livrable commun serait un contrat d'observation et un rapport de coût/exposition testé sur données synthétiques ; son utilité doit être évaluée après les gates P1/P2. Aucun adaptateur de trading réel n'est créé par cette étude.

## Sources et limites de vérification

Les faits sur Rugger proviennent des fonctions citées plus haut, lues pendant cette mission. Les documents officiels suivants sont des points de contrôle pour le futur choix des fournisseurs ; **ils n'ont pas été consultés en ligne dans cette étude et ne fondent aucune assertion de tarif, liquidité, latence ou rentabilité actuelle** :

- Solana, transactions et frais : <https://solana.com/docs/core/transactions> et <https://solana.com/docs/core/fees>.
- Raydium, documentation du protocole et LaunchLab : <https://docs.raydium.io/>.
- DexScreener, contrat et limites de l'API : <https://docs.dexscreener.com/api/reference>.
- Coinbase Exchange, exemple de documentation de carnet, produits et ordres d'une plateforme centralisée : <https://docs.cdp.coinbase.com/exchange/docs/welcome>. Ce lien ne constitue pas un choix de plateforme ni une preuve d'accès de l'utilisateur.

Les tarifs applicables, la profondeur, les frais de données et les conditions d'accès devront être vérifiés dans les documents effectivement en vigueur et les observations autorisées du lieu retenu. Aucun appel RPC/WS/API de marché, lecture de `.env`, base utilisateur, transaction, souscription ni dépense n'a été effectué pour cette étude.

**Prochaine priorité :** terminer les gates techniques, obtenir un inventaire de données et coûts comparable, puis préenregistrer le protocole. La poursuite de Rugger et l'étude BTC/SOL peuvent partager des définitions de risque et de mesure ; aucune réorientation économique n'est justifiée aujourd'hui.

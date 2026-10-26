# Audit économique préliminaire — Rugger Bot V1

26 octobre 2026. **Verdict économique : INSUFFICIENT DATA.**

Référence technique récupérée : `56294b4795390db14b1bc46205ab382eb4ac0f5d`,
branche d'intégration `fix/p1-research-gates-and-synthetic-protocol`. Cet audit
examine les fonctions actives et les correctifs P1 en cours ; les références de
lignes ci-dessous situent le code inspecté et peuvent évoluer avec l'intégration.
Les noms de fonctions restent les points de repère.

Aucun corpus de marché, fichier `.env`, portefeuille, clé, base utilisateur ou
service de marché n'a été interrogé. Aucun rendement économique n'a été mesuré.
La référence de tests **604 réussis, 1 ignoré, 242 sous-tests réussis** a été
reproduite par l'intégration ; elle étaye le fonctionnement synthétique, pas
l'existence d'un avantage de trading. Les verdicts P1/P2 relèvent du rapport de
gates ; cet audit ne les remplace pas.

## Ce que le système sélectionne effectivement

Le moteur `final_decision_engine.decide` est une politique PAPER exploratoire,
pas un modèle probabiliste calibré (`bot/analyser/final_decision_engine.py:1`,
`:229`). Il part d'un score de 50, favorise notamment la récurrence du créateur,
la liquidité observée, un momentum modérément positif et certains volumes. Il
refuse les risques de sa liste critique, puis demande un score d'au moins 45.
Une valeur de 60/100 ne signifie donc ni 60 % de réussite ni 60 % de sécurité.

| Hypothèse d'avantage | Ce qui existe dans le code | Preuve économique encore nécessaire |
|---|---|---|
| Détecter tôt une création LaunchLab exploitable | Identités de lancement, récupération/checkpoints et supervision testés synthétiquement ; observation n'est pas ordre | Référence indépendante des créations, taux de couverture et délais P50/P95/P99 jusqu'à un prix réellement traitable |
| Les créateurs récurrents sont plus favorables | Bonus au nombre de lancements antérieurs, sans preuve causale de qualité (`final_decision_engine.py:232`) | Rendement net conditionnel hors échantillon, comparé à une baseline et contrôlé pour liquidité, âge, régime et réutilisation des wallets |
| Éviter ventes développeur/relais réduit les pertes | Pénalités et veto explicites, interprétation d'un cache partiel (`:258`, `:306`) | Labels de comportement fiables, taux de détection avant décision, faux positifs/négatifs et coût des occasions manquées |
| Momentum/volume indiquent une continuation | Bonus/pénalités heuristiques (`:268`, `:287`) | Disponibilité réelle des indicateurs à l'entrée, stabilité après coûts et résistance au volume artificiel |
| Une sortie TP/SL/trailing maîtrise les pertes | Déclenchement au prochain prix observé, puis comptabilité PAPER (`paper_trader.py:633`) | Prix d'achat/vente pour la taille voulue, latence, gaps, échecs et absence de route de sortie |

Le choix de ces signaux est une hypothèse testable. Aucun benchmark externe ni
échantillon indépendant ne démontre actuellement un avantage concurrentiel.

## Risques économiques prioritaires

### E01 — L'unité de rendement USD n'est pas automatiquement un rendement SOL

Le capital et les tailles sont exprimés en SOL, mais le ledger calcule
`gross_return = exit_price_usd / entry_price_usd - 1`, puis
`pnl_sol = position_sol * net_return` (`bot/analyser/paper_trader.py:633`, `:650`,
`:657`). Le calcul est arithmétiquement cohérent **sous une convention de change
constant**, sans démontrer le rendement effectif en SOL.

Si une position de `q` SOL achète un token coté en USD, avant coûts et sous
hypothèse d'exécution parfaite, le rendement en SOL serait :

`R_SOL = (prix_token_USD_sortie / prix_token_USD_entrée)
         × (prix_SOL_USD_entrée / prix_SOL_USD_sortie) − 1`.

Exemple purement mathématique : token USD inchangé et SOL/USD en hausse de 20 %
impliquent `1/1,20 − 1 ≈ −16,67 %` en SOL avant coûts, contre zéro dans le ratio
USD seul. Pour 1 SOL exposé sur un capital initial de 10 SOL, cela représente
environ `−0,16667 SOL`, soit `−1,6667 %` du portefeuille avant coûts. Aucune
variation historique n'est supposée ici. Le collecteur LaunchLab
convertit le spot en USD, y compris depuis une courbe SOL, sans transmettre dans
`MarketQuote` le taux de change horodaté à chaque exécution
(`launchlab_onchain.py:148`, `:157`, `paper_trader.py:26`).

**Conséquence :** conserver le ledger actuel comme simulation indicative avec
convention explicite ; ne pas certifier son P&L comme profit SOL exécutable.
Avant validation économique réelle, figer la devise de référence et enregistrer
les prix token/devise, conversions et coûts dans cette devise. Ne pas convertir
ou réécrire silencieusement les anciennes positions.

### E02 — Un prix observé ne prouve pas une entrée ou une sortie disponible

Les pools LaunchLab fournissent un spot calculé sur l'état de courbe ;
`funding_usd` décrit le financement, pas une profondeur DEX interchangeable
(`launchlab_onchain.py:61`, `:158`). Les cotations DexScreener sont également des
observations, pas des engagements d'exécution. Le choix de la paire la plus
liquide ne prouve pas l'absence de frais, restrictions ou impact
(`paper_trader.py:384`).

L'estimation de slippage suppose un produit constant et un notionnel de référence
jusqu'à **100 USD**, ignore les frais du pool et ne représente pas nécessairement
une liquidité concentrée (`paper_trader.py:23`, `:84`). Ce notionnel n'est pas
recalculé depuis la taille effective en SOL ; le marché peut ne pas exposer les
réserves. Un champ inconnu reste inconnu. La pénalité de score correspondante
n'est pas un simulateur d'exécution.

**Données requises :** réserves et type de pool au slot de décision, devises,
taille de l'ordre, route, frais, quote de vente indépendante, disponibilité
horodatée et échecs de cotation. Tester les pertes de route et la liquidité retirée
sans supposer une vente au dernier spot.

### E03 — Les protections anti-rug ne constituent pas une certification du token

Le vecteur de décision ne contient pas de vérification explicite des autorités
mint/freeze ou de toutes les extensions/permissions pertinentes du token
(`final_decision_engine.py:18`). Les holders proviennent des soldes visibles dans
un cache souvent centré sur le créateur ; la concentration calculée porte sur
ce sous-ensemble, pas sur toute l'offre (`behavior_pipeline.py:151`, `:196`).
La cooccurrence de wallets au même slot est un indice, pas une preuve de bundle
ou de fraude.

Un comportement inconnu pénalise le score sans veto universel ; les données
holders inconnues et les métriques manquantes ne bloquent pas systématiquement
une entrée (`final_decision_engine.py:258`, `:284`, `:296`). Un score admissible
peut donc coexister avec d'importantes inconnues. Ne pas renommer cette admission
« token sûr ». Les autorités, concentration réelle, exécutabilité et fraîcheur
doivent avoir une politique de donnée critique explicite avant P3/P4.

### E04 — La latence utile inclut les appels et l'ancienneté des sources

Le moteur cote les candidats séquentiellement, enrichit ensuite le comportement,
puis décide (`paper_engine.py:980`, `:1000`, `:1053`). La date `now_quote` est
attribuée à la réception avant cet enrichissement ; elle ne renseigne pas à elle
seule l'âge de la donnée fournisseur au moment effectif de la décision.
Le poll par défaut est de 15 secondes, jusqu'à 10 candidats par cycle, avec RPC
adaptatif et temporisations (`paper_engine.py:1537`, `:1542`, `:1552`,
`multi_creator_research_engine.py:102`). Ces valeurs ne sont pas des latences
mesurées et les réduire n'établirait pas un avantage économique.

Mesurer séparément réception, décodage, attente de file, cotation, enrichissement,
décision et exécution simulée. Conserver l'heure de source, de réception et de
connaissance. Tester les P95/P99 et la couverture sous saturation, pas seulement
le temps CPU moyen. Toute priorité de file doit conserver la possibilité de
gérer les positions déjà ouvertes.

### E05 — Frais, gaps et sorties impossibles dominent potentiellement les seuils

Le ledger retranche un coût global hypothétique en points de base au rendement
brut ; il n'additionne pas des frais de réseau et de priorité observés, des coûts
d'échec et un impact calculé pour chaque ordre (`paper_trader.py:650`).
`decide` adapte TP/SL/horizon/trailing et le coût forfaitaire à la liquidité et
aux signaux ; ce coût n'est pas une facture ou une garantie de prix
(`final_decision_engine.py:309`).

Pour illustrer le seul seuil de rentabilité d'un modèle binaire simplifié, si les
gagnants font exactement `+TP`, les perdants exactement `−SL`, et chaque aller-
retour coûte `c` de la mise, alors `E[R] = p×TP − (1−p)×SL − c` et
`p_seuil = (SL+c)/(TP+SL)`. Les chiffres suivants sont des calculs sur paramètres
du code, **pas** des taux de réussite observés :

| Branche de paramètres | TP | SL | Coût supposé | Réussite minimale dans ce modèle simplifié |
|---|---:|---:|---:|---:|
| Base, avant adaptations momentum/coordination | 10 % | 8 % | 2 % | 55,56 % |
| Liquidité inférieure à 3 000 USD, avant adaptations | 7 % | 6 % | 3 % | 69,23 % |
| Liquidité d'au moins 25 000 USD, avant adaptations | 14 % | 8 % | 1,5 % | 43,18 % |

Ces seuils ignorent trailing, sorties risque/temps, gains/pertes variables,
changements de paramètres, gaps, impossibilité de vendre et change. Ils ne
doivent pas servir à sélectionner la stratégie sans données. Une vente constatée
après un effondrement peut dépasser largement le SL nominal. Si le prix tend
vers zéro, la formule simple produit `−100 % − coût` sur la position ; les frais
peuvent donc porter la perte simulée au-delà de son principal. Ce cas ne prouve
pas qu'une sortie existe. L'absence de quote de sortie ne vaut jamais rendement
nul ni clôture au dernier prix disponible.

### E06 — Une comptabilité réconciliée ne couvre pas toute la perte économique

L'allocation par défaut est de 10 % du capital réalisé, avec trois positions au
maximum, 20 entrées quotidiennes et perte journalière réalisée limitée à 10 %
(`paper_trader.py:312`, `:722`, `paper_engine.py:1539`). Trois positions initiales
de 1 SOL immobilisent ainsi 3 SOL sur 10 SOL ; une perte de 10 % sur une seule
position vaut 0,1 SOL, soit 1 % du capital initial, avant coûts. Ce calcul n'est
pas une prévision.

La limite journalière porte sur les clôtures réalisées. Elle ne garantit pas un
plafond des pertes latentes, corrélées ou non cotables. Le drawdown rapporté du
moteur est explicitement réalisé et réconcilié, pas un drawdown de liquidation
mark-to-market (`paper_engine.py:498`). Pour le risque de ruine, il manque la loi
des pertes extrêmes, les dépendances entre tokens/créateurs, les coûts et la
probabilité d'absence de sortie. Ne pas produire un pourcentage de ruine fictif.

## Ce que les backtests existants autorisent à conclure

Les groupes transaction/timestamp et la purge de labels des voies principales
réduisent des fuites temporelles identifiées ; ils ne prouvent pas la provenance
historique ni la disponibilité des prix au moment étudié. Le CSV historique
conserve `mint,timestamp,price_usd`, sans date de réception/connaissance, état
complet du pool ou devises d'exécution (`research_pipeline.py:32`, `:73`).

Les grilles comparent plusieurs horizons/coûts sur le même test et peuvent
qualifier un horizon après ces consultations (`research_pipeline.py:414`). Une
validation finale indépendante est nécessaire après le choix. Le diagnostic
`selected_equity_multiple` compose les rendements de trades comme si toute
l'equity était engagée à chaque fois ; il n'est pas le portefeuille PAPER
10 SOL/10 % avec positions simultanées (`research_pipeline.py:395`). Les routes
héritées non certifiées doivent rester exclues de la preuve OOS, même si leur
simulation arithmétique ou leurs tests unitaires réussissent.

## Données et critères de falsification pour la suite

1. **Univers et provenance :** figer le périmètre LaunchLab, conserver créations,
   rejets, échecs, événements non datés et tokens sans prix. Comparer la capture à
   une référence indépendante ; publier les exclusions et la couverture. Un
   résultat fondé seulement sur les survivants cotés invalide la conclusion globale.
2. **Décision observable :** snapshots horodatés des signaux, cache, permissions,
   holders et liquidité, avec distinction heure de marché/heure de connaissance.
   Un signal utilisant une information connue après l'entrée est exclu.
3. **Exécution et devise :** quotes achat/vente à taille effective, coûts de
   chaque tentative, slippage, disponibilité et conversions. Une espérance dont
   l'intervalle plausible des coûts change le signe n'établit pas un avantage robuste.
4. **Protocole figé :** candidats, critères, coûts, graines et budget d'essais
   déclarés avant mesure ; train/validation/test final groupés et purgés. Toute
   consultation du test final pour ajuster un choix impose un nouveau holdout.
5. **Mesures :** P&L et rendement dans la devise choisie, DD réalisé et latent
   distincts, exposition, espérance nette, PF avec cas dégénérés, gains/pertes,
   quantiles de pertes, nombre de trades/groupes, taux de remplissage, refus et
   intervalles d'incertitude par blocs/groupes dépendants. Aucune taille minimale
   arbitraire de 30/15/5 ne garantit à elle seule une puissance statistique suffisante.
6. **Robustesse :** comparer à l'absence de trade et à des baselines simples,
   puis régimes haussiers/baissiers, stagnation, retrait de liquidité et pannes.
   Une performance concentrée dans un créateur, une période ou quelques sorties
   irréalistes déclenche une enquête, pas un GO.

Le financement de la collecte et l'accès aux fournisseurs restent soumis au
périmètre autorisé ; cet audit n'en déclenche aucun. Avant d'allonger la recherche,
fixer aussi le coût complet d'infrastructure et le volume réellement traitable.
Un avantage brut inférieur aux coûts complets ou impossible à mesurer de façon
indépendante justifie l'arrêt ou la réorientation, après contrôle des erreurs de
données/simulation.

**Décision actuelle : INSUFFICIENT DATA sur l'avantage économique ; NO-GO pour
toute recommandation de trading réel.** Le prochain résultat utile est un protocole
et un simulateur validés dans leur périmètre synthétique, puis un corpus réel
autorisé, auditable et adapté à l'exécution. Un résultat synthétique positif ne
changera pas à lui seul cette décision économique.

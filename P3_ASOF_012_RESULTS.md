# P3-012 — observations causales et résultats économiques conditionnels

29 octobre 2026, Europe/Paris. **Le transport et le collecteur ont fonctionné ;
aucun cycle économique strict n'est qualifié.** Une opportunité a été retenue
avant S2 puis présente une valorisation conditionnelle négative aux deux tailles.
Le résultat défavorable est conservé. Aucun ordre, signature de portefeuille,
position acquise, dépense, changement de politique ou fusion n'a été effectué.

## Source, protocole et acquisition unique

Code exact : `f36ffc49e372ac8d9d2bb3ae419f63735fe2bf9f` ; préenregistrement
publié avant acquisition : `58468d83`. Plan :
`validation/p3_asof_012/plan.json`, SHA256
`93e94c4fb301e254cb577138ad9f1a74450bb214b15e6f7767dc695c5f0c838b`.
Sources : index public LaunchLab `lastTrade` et RPC public Solana mainnet,
uniquement en lecture, via le proxy configuré.

Une seule exécution : **12 requêtes, 35,494 s de capture, 35,942 s de processus**.
Tous les statuts HTTP sont 200. Aucun retry, fallback, dépassement du watchdog ou
appel supplémentaire pendant cette analyse. Les huit requêtes de réserve sont
restées inutilisées : 1 découverte, 4 `getMultipleAccounts` (racines puis S0/S1/S2),
3 `getBlockTime`, 2 pages historiques et 2 corps `getTransaction`.

Le journal contient 159 événements ; les 25 analyses de comptes ont été
reproduites depuis les réponses de banques conservées, et le rapport reproduit
est exactement égal au rapport original. Ancre finale :
`3cac1bf300e3023d5ade20336bccd3420d63469a417d148a0b32026bb3487523`.
L'analyse chiffrée est conservée dans
[`validation/p3_asof_012/ECONOMIC_ANALYSIS.json`](validation/p3_asof_012/ECONOMIC_ANALYSIS.json).

## Univers et chronologie

Les 100 lignes reçues sont conservées avec leurs champs de sélection et digests.
Le corps JSON intégral de découverte n'a pas été retenu : le filtre signale
`unsafe_or_oversized_body`. Le rejeu des banques est complet ; un rejeu du corps
intégral de l'index ne peut pas être revendiqué. Le tri `lastTrade` ne démontre
pas que les 100 tokens viennent d'être créés ; leurs dates de création d'index
restent des déclarations.

| Étape | Résultat conservé |
| --- | --- |
| Univers reçu | 100 lignes ; 66 hors périmètre natif SOL, 22 au-delà du préfixe fixe |
| Préfixe fixé avant les réserves | 12 pools natifs distincts |
| S0 puis S1 | 12 analyses par banque ; slots 462880905 puis 462880981 |
| Qualification S1 | 5 `STRICT_OBSERVATION`, 3 `RESEARCH_ONLY`, 4 refus |
| Paires S0/S1 admissibles en recherche | 8 ; 1 changement compatible achat, 7 sans changement net compatible achat |
| Sélection avant S2 | 1 pool ; aucune substitution selon le résultat futur |
| S2 | 1 analyse au slot 462881057 |
| Total de nouvelles analyses de banque | 25 ; ce ne sont ni 25 traders indépendants ni 25 cycles économiques |

Les attentes monotones préenregistrées sont de **15 002 ms** puis **15 003 ms**.
Le calcul de sélection est daté de 13:28:11.837 ; sa barrière d'ingestion est
13:28:11.912, celle des décisions A/B 13:28:11.995 et celle des hypothèses de coûts
13:28:11.998. La réponse S2 arrive à 13:28:28.035, après ces trois sauvegardes.
Les barrières d'ingestion ne sont pas présentées comme des horloges exactes de
commit durable. Les slots RPC et temps estimés des blocs sont conservés ; ils
ne sont pas des horloges de cotations d'un fournisseur.

Les quatre refus S1 sont conservés : une extension de mint non prise en charge,
deux divergences de supply (−1 090 480 886 130 unités et −1 unité), et une banque
sans circulation permettant la revente de la quantité projetée. Aucun contrôle
n'a été affaibli pour les faire entrer.

## Identité historique : un progrès vérifiable et une limite conservée

La recherche bornée porte sur les deux premières plateformes distinctes du
préfixe, une page au maximum par plateforme et un seul corps choisi avant son
résultat. Aucun ancien balayage de seeds n'a été relancé.

- Plateforme `EB2LqTh8pw4ym6jsuvSBz7BvykordCKZvqWyHoSGsFgo` : le plus ancien
  succès de la page, au slot 462186842, n'est pas une création correspondante.
  Cette recherche reste `UNKNOWN` et ne prouve pas l'absence d'une création plus
  ancienne hors de la page.
- Plateforme `9WmFLsgeEZ6zvqvUepFkiuVCJoKKgdjuHo5CUtFyVhDH` : la transaction
  `4reukNkZuftit9anD6kZmZdoLutoGXuDoXEeZ88L4HTeGZ3kx4SeNN7fMVT5nMF5jpmpq2e2G5hfh2sQduPpuAXc`,
  slot 462840563, contient le discriminateur et les paramètres complets de
  `CreatePlatformConfig`. L'admin signataire déclaré
  `9Jz9fxVLravw7iMc449zUdAYwt6XKLNKQs419dmNZfDF` dérive la PDA canonique.
  La preuve est disponible avant la décision ; seuls les deux pools concernés
  sont affinés. Les autres identités et refus restent inchangés.

Cette vérification relie le corps RPC conservé, sa signature identifiante, les
rôles du message et la PDA ; elle ne vérifie pas une signature Ed25519 sur un
message sérialisé absent. Les créations des tokens eux-mêmes ne sont pas prouvées
par les snapshots. Les frais 10 000 et 25 000 lamports de ces deux transactions
historiques appartiennent à autrui et ne remplacent aucun coût de notre position.

## Deux tailles exactes, aucune mise à l'échelle de devis

Mint sélectionné : `Em9pfyKaCv5Fw5hJYULiyMoknCUgU3ChJ2GNX2Vibeta` ; pool
`3e43Dn61MXmQRthF4GaTGYrZGNw89Z7TuRatdgb3jCXd`. Les taux présents dans ses
comptes S1 sont 2 500 + 7 500 + 5 000 ppm, soit **1,5 % par jambe** selon le
modèle épinglé. Chaque quantité est recalculée dans sa propre courbe.

| Taille hypothétique | Quantité projetée atomique | Revente immédiate après notre propre achat, modèle cohérent S1 | Écart immédiat avant coûts additionnels | Vente de cette même quantité contre S2 observé | Écart S2 avant coûts additionnels |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0,10 SOL | 503 219 539 783 | 0,097022499 SOL | −0,002977501 SOL | 0,094565758 SOL | −0,005434242 SOL |
| 1,00 SOL | 4 990 056 831 018 | 0,970224999 SOL | −0,029775001 SOL | 0,930057139 SOL | −0,069942861 SOL |

La quantité pour 1 SOL n'est pas dix fois celle pour 0,10 SOL. Le modèle immédiat
intègre notre achat dans les réserves, puis sa revente sans activité intermédiaire.
La valorisation S2 utilise les réserves réellement observées, **sans intégrer
l'effet de notre entrée hypothétique sur ce futur marché**. Ces deux bases sont
distinctes ; leur écart ne mesure pas à lui seul un rendement causal de stratégie.

Pour la même quantité fixe, les ventes contre les banques observées S1 puis S2
passent de 0,096840602 à 0,094565758 SOL, et de 0,952337068 à 0,930057139 SOL.
Après la décision, S1→S2 présente un changement compatible vente : `real_b`
diminue de 1,239753461 SOL, `real_a` de 6 415 469 850 265 unités et la contrepartie
du coffre de tokens est conservée. Cela ne prouve ni un nombre de swaps ni
l'indépendance de leurs auteurs. Ce résultat futur n'a servi à aucune sélection.

## Coûts, risques et seuil économique restant

Les frais de courbe sont déjà intégrés aux sorties du modèle. Ils ne sont pas
soustraits une seconde fois. Les coûts de réseau restent des hypothèses
préenregistrées : une signature par jambe, jusqu'à 1,4 M CU par transaction,
prix de priorité 0–1 000 micro-lamports/CU et au plus deux échecs à 6 400 lamports.
Leur intervalle total est **10 000–25 600 lamports**, sous ces seules hypothèses.

| Taille | Écart S2 après les seuls frais réseau hypothétiques |
| --- | --- |
| 0,10 SOL | −0,005459842 à −0,005444242 SOL |
| 1,00 SOL | −0,069968461 à −0,069952861 SOL |

L'ATA réellement nécessaire, le WSOL, leurs dépôts, leur récupération et les
frais effectivement applicables n'ont pas été observés. Le scénario `unknown_ATA`
garde une borne totale inconnue. Le scénario « ATA existant » suppose explicitement
zéro dépôt supplémentaire. Le scénario « nouvel ATA classique » suppose
2 039 280 lamports immobilisés ; si non récupérés à l'horizon, les bornes de cash
deviennent respectivement −0,007499122 et −0,072007741 SOL au pire coût déclaré.
Ce dépôt remboursable n'est pas présenté comme une perte irréversible prouvée,
ni comme l'intégralité des comptes requis par une future route.

Même le scénario de frais partiels le plus favorable est négatif. Les sorties
S2 devraient apporter au moins **5 444 242–5 459 842 lamports supplémentaires**
pour 0,10 SOL, ou **69 952 861–69 968 461** pour 1 SOL, avant les coûts encore
inconnus. Aucun réglage actif n'a été remplacé par le meilleur de ces scénarios.
Les six lignes de sensibilité représentent deux tailles alternatives sur un
seul pool/horizon et trois hypothèses de coûts, pas six essais indépendants.

## Master contre référence et suite économique

Les deux moteurs ont pris **12 décisions appariées WAIT/WAIT**, figées avant S2,
dans deux livres PAPER isolés de 10 SOL. Aucune entrée ; aucun changement du
portefeuille utilisateur. Les features causales requises, dont une conversion
SOL/USD actuelle, la santé opérationnelle attestée, les coûts propres complets
et l'historique d'edge indépendant sont insuffisants. Le P&L de marché est
`UNKNOWN`, pas un zéro de performance validé. Aucun vainqueur et aucune promotion
des 24 politiques ne sont établis.

Le progrès est instrumental : acquisition causale reproductible, conservation
des refus, une preuve historique de seed canonique, un candidat choisi avant
son résultat et des quantités propres chiffrées. **0 cycle P3 strict qualifié,
0 transaction exécutée, 0 avantage net démontré.**

Le prochain obstacle économique est de relier des features et coûts propres
admissibles aux décisions prospectives, puis d'évaluer une cohorte indépendante
par créateur sur des sorties exactes. Le changement positif S0→S1 de ce cas n'a
pas compensé la friction et la détérioration ultérieure. Une hypothèse d'entrée
agressive doit être figée puis éprouvée avec pertes, abstentions et positions
non liquidées ; retirer ce candidat perdant après S2 fausserait cette preuve.

# P3 — inventaire atomique intégré et réalisations PAPER partielles

27 octobre 2026, Europe/Paris. Code publié `82ce606ef0952154efb0d964e8cfea7befc20c37`,
arbre `49d9ca058dce7a6b953b96d997cf20a7bb187735`, équivalent local `2edcd43`.
PR #22 ouverte. Aucun ordre, signature, dépense, secret ou ledger utilisateur touché.

## Programme et comptabilité

Le chemin actif est `paper_engine.collect_once → record_quote → token_inventory`.
Une cotation d'entrée conserve le mint, les décimales ou leur absence, le budget
SOL, le scénario expected/minimum choisi, la quantité atomique, le corps/reçu,
les frais connus ou inconnus et la chronologie. L'acquisition reste **projetée**.
Les sorties utilisent ce lot persisté, jamais une quantité déduite d'un prix USD.
L'inventaire et les jambes de sortie sont dans la même base PAPER que les
positions ; **un seul capital**, `paper_portfolio`, est crédité.

Quantités, coûts et P&L des jambes sont des entiers conservés en TEXT ; le
portefeuille historique reste une représentation SOL flottante, rapprochée des
jambes entières. À chaque vente, le coût alloué est la différence entre deux
allocations cumulatives entières. La dernière jambe absorbe le reliquat exact.
Une jambe créditée n'est pas recréditée lors de la clôture. Les pertes partielles
comptent immédiatement dans la limite quotidienne et le drawdown. Les statistiques
de trades portent sur les positions complètement fermées, pas sur des jambes
traitées comme des trades indépendants.

Le vrai bridge P3 contrôle les corps, quantités demandées/annoncées/actualInput,
mint, provenance, disponibilité, fraîcheur, version et ordre des requêtes. Un
devis demandé avant fixation du nouveau reliquat est refusé. Une quote répétée
ne revend pas deux fois. La réconciliation finale réutilise l'agrégateur entier
P3 ; le financement est contrôlé avant chaque jambe, sans emprunt sur ses produits
futurs et sans fabriquer un capital initial couvrant tous les frais ultérieurs.

Les frais de route déjà intégrés aux sorties ne sont pas redéduits. Les frais
additionnels doivent être explicites. Frais inconnus : quantité projetée
conservable, coût restant et capital libre inconnus, nouvelles entrées bloquées,
aucune réalisation économique inventée. Les anciennes positions sans lot restent
UNKNOWN et suivent leur contrat historique, explicitement distinct du mode natif.

Les TP/SL et scores actifs sont conservés. Leurs déclencheurs de prix restent en
USD ; le P&L natif utilise les montants SOL des quotes, sans supposer SOL/USD
constant. Un déclencheur TP ne garantit donc pas un bénéfice net en SOL.

## Nouvelle démonstration exécutée

```sh
python -B -m bot economic-demo --output work/atomic-demo-next
python -B tools/compare_native_inventory_costs.py
python -B tools/evaluate_atomic_market.py
```

Dossier neuf exigé ; aucun réseau ni `.env`. Exécution finale conservée sous
`/workspace/work/atomic-demo-final`, rapports exportés dans
`validation/P3_ATOMIC_INVENTORY_DEMO.json` et `validation/atomic_inventory_demo/`.
Chaque cas utilise une base indépendante de 10 SOL et un lot projeté de
25 000 000 unités atomiques, décimales 6, acheté pour 1 SOL. Les frais synthétiques
de la fixture sont 5 000 lamports à l'entrée et 10 000 par sortie acceptée.

| Cas synthétique | Quantité vendue | Reliquat | Net réalisé simulé SOL | Capital SOL |
| --- | ---: | ---: | ---: | ---: |
| Sortie complète TP | 25 000 000 | 0 | +0,199985 | 10,199985 |
| Partielle, reconnexion, puis fin | 10 000 000 + 15 000 000 | 0 | +0,049975 | 10,049975 |
| Liquidité insuffisante | 0 | 25 000 000 | 0 réalisé ; résultat de position inconnu | 10 |
| Baisse et SL | 25 000 000 | 0 | −0,300015 | 9,699985 |

Le cas partiel alloue 400 002 000 puis 600 003 000 lamports de coût : P&L des
jambes +99 988 000 puis −50 013 000, total +49 975 000. La connexion est rouverte
après la première jambe et le même devis rejoué sans crédit. Cette reprise ne
prétend pas restaurer une VM. Le parseur/recovery, le scoring et les contrôles
financiers sont utilisés ; la lane offline sans scanner n'est pas une nouvelle
preuve de supervision WebSocket. Les quotes sont synthétiques, pas des fills.

**Comparaison à coûts identiques**, exécutée séparément : ancien calcul de prix
avec coût 200 bps et nouveau lot avec 20 000 000 lamports de frais additionnels
produisent tous deux **+0,18 SOL** sur la même hausse et le même notionnel.
Le nouveau chiffre +0,199985 de la fixture ci-dessus vient d'autres coûts
synthétiques, pas d'une amélioration de rentabilité. Aucune hypothèse de frais
de fixture n'est appliquée par défaut aux observations de marché.

## Marché déjà conservé : résultat mesuré, sans nouvelle collecte

Le contrôle 007 n'a pas été relancé. Le nouvel outil consomme ses preuves ancrées.

| Mesure | Valeur / effectif | Source et limite |
| --- | --- | --- |
| Inventaire projeté achat de 1 SOL | 34 076 309 234 009 unités ; un mint | Quote initiale 1020, acquisition non exécutée |
| Petites cotations de vente disponibles | 2/2, quantité 18 765 447 579 | Quotes 1021 / 1029, deux horizons |
| Part couverte par chaque petite quote | 0,0550689 % | Quantités exactes ; pas de scaling à toute la position |
| Reliquat hypothétique après une petite vente | 34 057 543 786 430 unités | Scénario indicatif, aucune jambe créditée |
| Demandes portant sur toute la quantité achetée | 0 | Disponibilité d'une sortie complète **inconnue** |
| Cycles économiques complets qualifiés | 0 sur ce cas | Heures/slots fournisseur et frais additionnels inconnus |
| Fréquence des sorties impossibles, P&L net, comparaison précoce/confirmation | Inconnus | Pas d'inférence depuis des demandes absentes |

Preuve : `validation/P3_ATOMIC_MARKET_EVALUATION.json`. Les quantités peuvent
être conservées malgré une heure source absente ; cette absence n'autorise
aucun règlement. L'effet de notre entrée n'a pas été appliqué à la banque observée.
Le modèle contrefactuel existant reste séparé des observations fournisseur.

## Lecteur branché au programme actif

Le moteur dispose maintenant de `--inventory-quotes` avec un nouveau
`--inventory-journal`. Il demande les tailles exactes choisies avant chaque appel,
et pour une sortie la totalité du reliquat persisté. Son budget propre est
20 GET de quote au maximum pendant 60 s, arrêt au premier refus/erreur, sans retry
ou fallback. Transport anonyme, reçu et corps conservés, fermeture sur annulation.
Une vérification après résolution du proxy interdit aussi un départ hors délai.
Ce budget ne décrit pas les autres appels scanner/prix/comportement du programme.

Forme disponible, **non exécutée sur le réseau dans cette session**, après
préenregistrement de l'observation complète et configuration locale autorisée :

```sh
python -B -m bot paper --network --shadow-final --session-seconds 60 --inventory-quotes --inventory-journal work/native-next/quotes.sqlite --db work/native-next/paper.sqlite --report work/native-next/engine.json --session-report work/native-next/session.json
```

Le journal doit être neuf et distinct du ledger. Les décimales/frais absents
restent inconnus : ce lecteur prépare la mesure à quantité complète, il ne rend
pas magiquement les réponses Raydium fraîches ou les frais observés. Les inconnus
bloquent les réalisations et, si le coût de l'entrée est inconnu, les entrées suivantes.

## Validation et conditions restantes pour P3

Preuves publiées `f29d39ee9612422f5695c9ae35fda255bbdebc3d`, puis trois fichiers
retéléchargés effectivement depuis cette référence GitHub dans un dossier neuf.
Neuf corps de quote et quatre jambes sur quatre cas rapprochés sans réseau ni
accès SQLite pendant replay. Aucun DB source nécessaire ou téléversé. Reçu :
`validation/P3_ATOMIC_INVENTORY_REMOTE_RESTORE.json`.

**1 535 tests, 242 sous-tests réussis, 1 ignoré**, 5,88 s, warnings en erreur,
stderr vide, sur copie jetable sans réseau/secrets ; 100 tests de plus que la
livraison fonctionnelle. Régressions causales : appel `asyncio.run` dans une
boucle active, écritures ignorées par trigger, réservation initiale confondue
avec frais ultérieurs finançables, latch après erreur de relecture et dépassement
de délai pendant résolution du proxy. Reprise, annulation, savepoint, double vente,
survente, source inconnue, frais non finançables et quantité 2**64−1 testés.

Avant de franchir P3, il reste à obtenir sur un corpus prospectif indépendant :

1. Identité, création, décimales, permissions et supply suffisamment prouvées.
2. Entrée et sortie portant sur le même lot, avec heures/slots exploitables et
   effet propre de l'entrée séparé ou explicitement modélisé.
3. Coûts réseau/priorité/ATA/échecs documentés, et transfert effectif distingué
   de la quantité expected/minimum du devis.
4. Sorties complètes ou partielles futures observables, reliquats non masqués,
   absences/refus conservés, comptabilité rapprochée et résultats nets comparables.
5. Séparation développement/validation et effectifs permettant une estimation
   crédible ; aucun bénéfice réel démontré à ce stade.

Préparation P4 : `P4_ATOMIC_COMPARISON_PROTOCOL.md`. Aucun paramètre agressif
modifié, aucune stratégie promue depuis ces fixtures. **P3 reste ouvert.**

# Rugger Bot V1 — Functional Release Candidate PAPER

Livraison exécutée le 27 octobre 2026 sur la branche de la PR #22, laissée
ouverte. Le programme intégré fonctionne en simulation reproductible. La
rentabilité de marché et la liquidation d'un inventaire réellement acquis
restent non démontrées. Aucun ordre, signature, portefeuille ou dépense.

## Lancer le programme

Depuis la racine du dépôt, avec Python 3.12 et les dépendances de
`requirements.txt` installées :

```sh
python -B -m bot demo --output work/demo-001
```

Le dossier doit être nouveau. Cette commande fonctionne sans `.env`, clé ou
réseau et refuse d'écraser un résultat existant. Elle produit :

- `demo_result.json` : étapes, contrôles et réconciliation du cycle ;
- `paper_report.json` : rapport moteur et `functional_dashboard` ;
- `paper.sqlite` : base **synthétique locale**, réutilisable pour inspection.

Le même point d'entrée produit un tableau de bord dans un second processus :

```sh
python -B -m bot report --db work/demo-001/paper.sqlite --output work/demo-001/dashboard.json --data-kind synthetic
```

La connexion est en lecture seule : aucun schéma, capital ou historique réparé
par le rapport. `--data-kind` décrit la provenance déclarée par l'appelant ;
il ne certifie aucune exécution de marché.

Le moteur actif est `bot.analyser.paper_engine`, supervisé avec le scanner par
`run_with_scanner`. `bot.main` seul n'est que le scanner. `python -m bot paper
--help` expose les options de ce moteur sans ouvrir `.env` ni le réseau.
La forme suivante est disponible pour une observation **après** configuration
locale Helius et préenregistrement de son protocole/budget ; elle n'a pas été
exécutée ici :

```sh
python -B -m bot paper --network --shadow-final --session-seconds 60 --db work/observation/paper.sqlite --report work/observation/engine.json --session-report work/observation/session.json
```

Cette voie conserve les quotas, délais et gardes existants. Elle ne constitue
pas une autorisation de campagne prolongée. Relancer avec la même base conserve
le portefeuille ; la supervision exige de nouveau un état scanner frais avant
les nouvelles entrées. Une observation publique anonyme P3 utilise ses protocoles
séparés ; elle n'est pas un remplacement silencieux de la configuration Helius.

## Démonstration réellement exécutée

Commande utilisée : `python -B -m bot demo --output
/workspace/work/functional-release-demo-001`, avec l'interpréteur de validation
`/workspace/.cloud-env/rugger_bot_v1/venv/bin/python`.

La fixture fournit une transaction LaunchLab synthétique et les prix USD
0,001 → 0,00105 → 0,0012, avec liquidité synthétique de 20 000 USD. Aucune décision
n'est forcée : les vrais composants sont appelés par `collect_once`.

| Étape | Résultat vérifié |
| --- | --- |
| Notification, récupération, parseur, cache | Deux notifications identiques, un seul fetch et un seul candidat |
| Backfill et supervision | Baseline refusée, puis préfixe rattrapé autorisé par le vrai garde scanner |
| Analyse et décision | Features, risques et trois décisions persistées ; un token analysé |
| Entrée PAPER | Une position de 1 SOL, capital initial de 10 SOL, allocation de 10 % |
| Reprise | Connexion SQLite réouverte après l'entrée, reçu rechargé, notification terminée ignorée |
| Suivi | Position conservée ouverte au prix intermédiaire |
| Sortie | Une clôture TP et aucun double crédit |
| Comptabilité | Brut 0,20 SOL, coût supposé 0,02 SOL, net 0,18 SOL, capital final 10,18 SOL |

Rendement du portefeuille : **+1,8 % sur cette fixture**. Win rate 100 % sur
un seul trade inventé ; profit factor et perte moyenne inconnus faute de pertes.
Ces chiffres ne mesurent pas une espérance de stratégie. L'ancien ledger applique
des rendements de prix USD à un capital SOL avec hypothèse SOL/USD constant ;
il ne conserve pas un inventaire atomique de tokens réellement acheté.
La reprise démontrée concerne la connexion et le reçu persisté, sans prétendre
avoir interrompu puis restauré une VM entière.

Les rapports exécutés sont conservés dans
`validation/RUGGER_FUNCTIONAL_DEMO.json` et
`validation/RUGGER_FUNCTIONAL_PAPER_REPORT.json`.

## Défaut corrigé et comparaison

La décision recalcule son hypothèse de coûts à chaque cotation. À la clôture,
le P&L débitait ce coût actualisé mais le ledger conservait le coût d'entrée.
Après redémarrage, un rapport pouvait reconstruire un brut faux.

Régression causale : position de 1 SOL, prix 1 → 1,20, coût d'entrée 200 bps,
coût de clôture 1 000 bps.

| Valeur | Avant | Après |
| --- | --- | --- |
| Coût réellement appliqué au modèle | 0,10 SOL | 0,10 SOL |
| Coût conservé dans le ledger | 0,02 SOL | 0,10 SOL |
| Brut reconstruit après reconnexion | 0,12 SOL | 0,20 SOL |
| Net et capital final | 0,10 / 10,10 SOL | 0,10 / 10,10 SOL |

Le coût appliqué est maintenant conservé dans la même transaction que la clôture
et le portefeuille. Une panne après écriture du capital annule aussi le nouveau
coût. Aucune ligne historique fermée réécrite ; ses anciens coûts ne sont pas
reconstitués sans preuve. Aucun seuil, score, TP/SL ou résultat net modifié pour
améliorer les résultats.

Le tableau de bord ajoute comptages distincts des tokens et décisions,
réservations, capital disponible, brut/net, coût pondéré par taille, rendement,
win rate, gains/pertes moyens, espérance empirique, profit factor, drawdown et
P50/P95/P99. Chaque métrique comporte valeur, unité, source, fiabilité et périmètre.
Les frais d'exécution, slippage réalisé et sorties non documentées restent
inconnus. Les latences d'acquisition/cycle utilisent une horloge monotone et
un échantillon roulant borné à 1 024 valeurs par étape, dans le processus courant.
Elles décrivent les appels revenus, pas toutes les erreurs. Les microsecondes de
la fixture ne sont pas une mesure HTTP ; son délai scanner de 1 000 ms est inventé.

## Évaluation sur observations de marché

Les sept paires archivées ont été requalifiées hors réseau, résultat identique
à la référence : six paires LaunchLab et une référence d'accès, zéro cycle
économique qualifié. Cinq manquent du corps d'achat et deux de l'heure source.
`tools/evaluate_functional_market.py` transforme cette qualification en rapport
chiffré sans remplacer les inconnus par zéro.

Après préenregistrement distant `ce70a4b`, une seule lecture RPC a obtenu
HTTP200 en 1 087 ms, sans retry, sur le même alias public que 007. Cela prouve
son fonctionnement à cet instant, pas un quota réservé. Le contrôle 007, déjà
préenregistré, a ensuite été exécuté **une fois**, sans changer son protocole :

- **12 requêtes / 19 871 ms**, contre plafond 20 / 60 000 ms ;
- snapshots aux slots **462210629 → 462210706** ; supply cohérente et PDA
  publiques vérifiées pour ce nouveau cas, distinct de l'ancien mint déficitaire ;
- quatre corps de cotation conservés : achat de référence 1 SOL et vente fixe,
  au premier état puis au suivi ;
- deux ventes **indicatives** de 18 765 447 579 unités atomiques cotées à
  **519 914 lamports** ; oracle entier indépendant : brut 526 496, frais de
  courbe 6 582, net de ces seuls frais 519 914 ;
- quantité fixée après le premier snapshot, avant toutes les quotes et avant
  le snapshot suivant, sans redimensionnement après réponse.

Progrès observé : deux références de vente à quantité fixe sont disponibles,
contre les refus `INSUFFICIENT_LIQUIDITY` des anciennes banques observées.
Mais cette quantité ne couvre que **0,05507 %** du montant attendu du devis
d'achat de 1 SOL. Elle ne liquide donc pas cet achat indépendant. L'heure/slot
source fournisseur et les coûts additionnels restent inconnus ; la création n'a
pas été trouvée dans le préfixe borné. **Zéro position acquise, zéro cycle complet,
P&L économique inconnu.** Aucun gain premier signal/confirmation démontré sur
ce cas unique ; aucune règle de stratégie retenue ou ajustée sur ce résultat.

Preuves : `validation/P3_ACTIVE_EXIT_007.json`,
`validation/P3_ACTIVE_EXIT_007_ANALYSIS.json`,
`validation/RUGGER_FUNCTIONAL_MARKET_EVALUATION.json` et bundles dans
`evidence/p3/`. Onze bundles / 1 639 événements vérifiés, dix analyses de snapshots
reproduites. Les deux nouveaux bundles ont été effectivement retéléchargés de
GitHub dans un répertoire neuf ; quatre quotes et deux snapshots reproduits avec
réseau et accès SQLite interdits. Résultat identique, aucune DB téléversée.

## Validation, publication et reprise

**1 435 tests et 242 sous-tests réussis, 1 ignoré** (base utilisateur absente),
warnings en erreur, stderr vide, 5,31 s sur copie jetable sans réseau ni secrets.
Vingt tests supplémentaires par rapport aux 1 415 de la référence : rapport,
CLI dans de vrais sous-processus, intégration, reconnexion/rollback des coûts
et lecture RPC strictement bornée. Les tests ne démarrent aucune collecte réelle.

Code distant `f50d226b9f437e9d0e3bccb171671f450fb7bd23`, arbre testé
`c343ad51f418c04e2d18e8d050877996e585a0f4`, commit local équivalent `4da94d3`.
Preuves publiées `8aeb6c83ac10d73ba4901b287bf776bd729d879a`.
Les commits locaux/distants ont des métadonnées différentes ; leurs arbres ont
été comparés exactement. PR #22 ouverte, aucune fusion.

```sh
python -B tools/offline_check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
python -B tools/evaluate_functional_market.py
python -B tools/analyze_p3_active_exit_007.py
python -B tools/verify_p3_evidence.py
```

Lancement unique, cycle synthétique, comptabilité, reporting et conservation des
preuves sont livrés. Le fonctionnement continu sur marché et les cycles économiques
à inventaire et frais complets restent à valider. Ne pas rejouer les collectes
terminées comme des tests : une nouvelle observation exige un nouveau protocole
borné, des chemins neufs et le respect effectif du fournisseur.

Prochaine action de développement : relier l'entrée PAPER à une quantité atomique
connue et conservée, puis qualifier une sortie sur **cette même quantité** avec
effet de l'entrée explicitement modélisé. Réutiliser le bridge existant, exiger la
chronologie et les frais, et garder séparés modèle contrefactuel et observations.
La comparaison sniping/confirmation ne doit commencer qu'avec ces cycles exploitables.
Les douze transactions historiques manquantes sont conservées dans l'état de
reprise ; elles ne suspendent pas cette intégration.

# Rugger Master — état de référence unique

> **Ce fichier est la seule source de vérité sur l'état du projet.** Tout autre
> document d'état (`P1_*`, `P3_*`, `CODEX_*`, `LIVE_*_CHECKPOINT`,
> `docs/MASTER_CONTINUITY.md`, `CLAUDE.md` de la pile #89) est un **journal
> historique** : utile comme preuve, jamais comme état courant.
> L'ancien contenu de ce fichier (préparation P3, 26-27 oct.) reste lisible via
> `git show d9b950e:PROJECT_STATUS.md`.

Dernière vérification : **2026-11-03**, sur `main` = `d9b950e`. Niveau de preuve
indiqué partout : *mesuré* (commande rejouée ce jour), *code* (lu dans le dépôt),
*historique* (affirmé par une note, non rejoué), *inconnu*.

---

## 1. Objectif final

Un **seul** bot Rugger Master pour Solana / Raydium LaunchLab (puis CPMM après
migration), capable de :

1. observer les créations LaunchLab en temps réel ;
2. décider (Master) ENTER / WAIT / EXIT avec coûts réels en SOL ;
3. exécuter en PAPER, puis — **sur décision séparée du propriétaire** — en LIVE
   avec un portefeuille dédié et des limites strictes ;
4. être suivi depuis une interface (Rugger Wallet) et sur Axiom.

Trois jalons **distincts**, aucun n'est atteint aujourd'hui :

| Jalon | Signification | État |
|---|---|---|
| `LIVE_READY_TO_ARM` | moteur LIVE complet, désarmé, testé hors réseau | non atteint (*historique*) |
| `LIVE_EXECUTION_VERIFIED` | vrais ordres autorisés, réconciliés | non commencé |
| `ECONOMIC_EDGE_VALIDATED` | avantage net de frais, hors échantillon | **non démontré** — aucune rentabilité |

## 2. Architecture de référence (cible)

```
bot/scanner  bot/solana       → capture LaunchLab (WebSocket/RPC)        [main]
bot/market                    → décodage exact TradeEvent + courbe       [#90]
bot/p3  bot/p4                → preuves, coûts, replay causal            [#89]
bot/master_*.py               → décision Master (shadow/PAPER)           [#89]
bot/analyser  bot/database    → moteur PAPER, SQLite, rapports           [main]
bot/live (cœur, 23 modules)   → route, signer isolé, submission, journal [#89]
bot/dashboard + Rugger Wallet → interface unique                         [main + #89]
```

Règle : un composant n'existe qu'à **un** endroit. Les sondes réseau ponctuelles
(40 modules `helius_*`, `public_*`, `pinned_*`… dans `bot/live`) sortent du
moteur d'exécution vers un espace recherche (étape ultérieure, voir §6).

## 3. Composants : état et classement

| Composant | Où | État | Classement |
|---|---|---|---|
| Scanner, client Solana, SQLite, config | `main` | testé (*mesuré*) | **CONSERVER** |
| Moteur PAPER `bot/analyser` | `main` | testé ; audit P0 du 22/10 corrigé par #1–#4 (*historique*) | **CONSERVER** |
| Décodeur TradeEvent + courbe exacte `bot/market` | #90 seulement | testé, unique dans le dépôt (*code*) | **FUSIONNER** dans la référence |
| Master `bot/master_*.py`, `bot/p4` | #89 seulement | testé ; S1 bank réel ajouté par #89 | **CONSERVER**, intégrer |
| Preuves/campagnes `bot/p3` (73 modules) | #89 | testé ; beaucoup de campagnes ponctuelles 009–012 | **AMÉLIORER** : garder le noyau, archiver les campagnes après intégration |
| Moteur LIVE cœur (23 modules `bot/live`) | #89 | testé hors réseau, désarmé ; anti-double envoi présent (`rpc.py:98`) | **CONSERVER** |
| Sondes réseau dans `bot/live` (40 modules) | #89 | scripts de recherche mélangés au moteur | **AMÉLIORER** : déplacer hors `bot/live` |
| Interfaces : Streamlit Rugger Wallet (#61), service Render (#63/#64/#87, #65–#74), aperçu Vercel (#86) | 3 endroits | trois UIs concurrentes | **FUSIONNER** : une seule (décision D4) |
| Workflows CI (51 sur #89, dont 4 planifiés Helius) | #89 | planifiés toutes les 6 h dès l'arrivée sur `main` | **AMÉLIORER** : désactiver les `schedule:` avant intégration (D3) |
| Copies `bot/bot/` (66 fichiers), `tests/tests/` (6), `*.bak*`, `*.avant_correctif` (6) | `main` | importées nulle part (*code*, `git grep`) ; inventaire en cours (#94) | **SUPPRIMER** après #94 |
| ~40 notes `.md` à la racine (`P1_*`, `P3_*`, `CODEX_*`) | `main` | historiques | **ARCHIVER** dans `docs/history/` (étape ultérieure) |
| Suivi Axiom | — | **aucun code** ; Axiom n'est cité que comme concurrent | **À DÉFINIR** (D5) |

## 4. PR et dépendances

Le dépôt contient **deux piles indépendantes** qui ne se connaissent pas :

- **Pile A** — `#22 → … → #88 → #89`, base `main@7ddddb9` (avant le terminal
  PAPER). **839 commits, ~115 000 lignes, 784 fichiers** hors de `main`. Contient
  Master, LIVE, P3/P4, Render.
- **Pile B** — `#90 → #91…#99`, base `main@d9b950e`. Agent Claude planifié.
  Contient `bot/market`, outils hors ligne, protocole d'autonomie.

Aucun fichier commun entre A et B (*mesuré*). L'intégration est faisable :
`#89 + main + #90` fusionnent avec **6 conflits**, tous dans les fichiers du
terminal PAPER (`bot/dashboard/app.py`, `README.md`, `TERMINAL_PAPER.md`,
`LANCER_TERMINAL_PAPER.bat`, `requirements-dashboard.txt`,
`.github/workflows/paper-terminal-ci.yml`) ; en prenant la version `main`
(correctifs Windows #59/#60 postérieurs) : **3974 réussis, 1 ignoré, 0 échec**.

| Catégorie | PR | Motif |
|---|---|---|
| **Porteuse à intégrer après revue** | **#89** (inclut 41 PR ouvertes) | pointe de la pile A, verte |
| **Porteuse à intégrer après revue** | **#90** | base de la pile B, verte, `bot/market` unique |
| Déjà contenues dans #89 → fermer après intégration de #89 | #22, #29–#31, #33, #34, #36–#39, #41, #42, #45–#48, #50, #52–#55, #65–#74, #76–#79, #81, #83–#85, #88 | 0 commit hors de #89 (*mesuré*) |
| Remplacées par une meilleure implémentation | #44 (anti-double envoi déjà dans #89, `bot/live/rpc.py:98`), #40 (ses commits propres se déclarent couverts par #41, inclus dans #89), #43 (fermée) | garde équivalent présent |
| Remplacée | #35 (61 commits) | branche parallèle de #36–#39, intégrée autrement via #39 « codex-free PR35–PR38 » ; à confirmer en revue |
| Corrections / décision nécessaires | #56 (1 commit Render ledger expérimental), #86 (Vercel), #80, #82 (preuves réseau ponctuelles) | dépendent de D3/D4 |
| Preuves historiques à conserver ouvertes temporairement | #24, #27, #28, #49 (recherche P3, 2–8 commits) | jamais intégrées, utiles comme trace |
| Pile B, en revue | #92, #93 (slot timing), #94 (inventaire copies), #95–#99 (rapports hors ligne) | sur #90, petites, testées par CI |
| Protocole d'autonomie | #91 | à garder **hors** de la référence (règles des agents) |

Ordre d'intégration recommandé (le propriétaire fusionne, jamais un agent) :
1. Décisions D1–D3 ci-dessous.
2. Branche d'intégration `#89 + main + #90`, désactivation des `schedule:`, revue.
3. Fermeture des 41 PR contenues ; rebase de #92–#99 sur la nouvelle référence.
4. Nettoyage (§6 étapes 2–4).

## 5. Dernier état réellement testé

Commande : `python -m pytest -q tests --ignore=tests/tests -p no:cacheprovider`,
Python 3.13, environnement isolé, sans réseau ni `.env`, 2026-11-03.

| Révision | Résultat |
|---|---|
| `main` `d9b950e` | 1358 réussis, 1 ignoré, 242 sous-tests |
| #90 `4f2875d` | 1404 réussis, 1 ignoré, 242 sous-tests |
| #89 `cf9a084` (+ `requirements-live.txt`) | 3926 réussis, 1 ignoré, 242 sous-tests |
| essai `#89 + main + #90` (non poussé) | **3974 réussis, 1 ignoré, 0 échec** |

Aucun de ces tests ne prouve une exécution réelle ni une rentabilité.

## 6. Prochaine mission prioritaire

**Construire la référence unique** sur une branche d'intégration, après D1–D3 :

1. `#89 + main + #90`, 6 conflits résolus côté `main`, `schedule:` désactivés,
   suite complète publiée.
2. Déplacer les 40 sondes hors de `bot/live` (aucun changement de logique).
3. Supprimer `bot/bot/`, `tests/tests/`, `*.bak*`, `*.avant_correctif`
   après revue de #94.
4. Archiver les notes racine historiques dans `docs/history/`.

Chaque étape = une PR courte, testée, réversible.

## 7. Blocages

**Techniques**
- Deux piles disjointes : l'agent planifié (pile B) développe sur `main` sans le
  Master ni le moteur LIVE, qui n'existent que dans la pile A.
- Consignes contradictoires (voir §8, D1).
- `main` non protégé ; l'identité connectée est administratrice. Les règles des
  agents ne sont pas une barrière technique.
- Les tâches planifiées s'appellent « DISABLED » mais sont **actives** :
  agent dev toutes les heures (`11 * * * *`), validation quotidienne (06:00 UTC),
  relecteur ponctuel. `docs/MASTER_CONTINUITY.md` (#91) les dit désactivées : faux.
- `data/` est ignoré par git : seules 3 archives de pools SOL sont versionnées
  (fixtures #90).

**Économiques**
- P3 : **NO-GO / INSUFFICIENT DATA** (*historique*, non contredit). Pas de
  couverture indépendante, frais complets, sorties qualifiées ni réconciliation.
- Seuils Master protégés : 50 cycles économiques qualifiés et 20 créateurs
  indépendants avant toute entrée opérationnelle — non atteints.
- Latence d'exécution (2 slots) : hypothèse non vérifiée.

## 8. Décisions et validations nécessaires (propriétaire)

| # | Décision | Recommandation |
|---|---|---|
| D1 | **Consigne active** : `AGENTS.md` de `main` dit « PAPER ONLY, aucun composant réel, première mission en lecture seule » ; celui de #89 et `LIVE_READINESS_MANDATE.md` (29/10) autorisent le développement LIVE désarmé. | Adopter la version #89 lors de l'intégration : développement LIVE autorisé, **aucune** signature réelle, aucun fonds, activation = décision séparée. |
| D2 | Pile A comme base de la référence (plutôt que reconstruire depuis `main`). | Oui : verte, contient Master + LIVE ; reconstruire serait une réécriture géante. |
| D3 | 4 workflows planifiés Helius (`HELIUS_API_KEY`, toutes les 6 h) dans #89. | Les désactiver dans la branche d'intégration ; réactiver un par un avec budget. |
| D4 | Interface unique : Streamlit Rugger Wallet, Render ou Vercel. | Une seule ; les deux autres archivées. |
| D5 | « Suivi Axiom » : sens exact ? (voir le portefeuille LIVE dans Axiom, ou exporter les positions vers Axiom ?) | Préciser ; rien n'existe aujourd'hui. |
| D6 | Agent planifié : continuer sur la pile B pendant l'intégration ? | Le mettre en pause pendant l'intégration, puis le rebaser sur la nouvelle référence. |
| D7 | Protection de `main` (GitHub Pro payant) ou risque accepté. | Décision de coût. |

## Règle de mise à jour

Toute PR qui change l'état du projet met à jour **ce fichier** (sections
concernées seulement) avec révision, commande et résultat. Les journaux détaillés
vont dans la description de la PR, pas dans un nouveau fichier d'état.

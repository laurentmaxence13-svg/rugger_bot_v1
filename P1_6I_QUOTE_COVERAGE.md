# P1.6i — Couverture des lancements connus et cotations orphelines

Date : 26 octobre 2026. Référence exacte :
`b89c4075d1c29adcd427d2f9947e59d81c81debb`.
Dépôt : `laurentmaxence13-svg/rugger_bot_v1`.
Worktree : `C:\Users\maxen\Downloads\rugger_bot_v1_p16h_workspace`.
Branche déjà présente au démarrage : `fix/p16i-coverage-final-audit`.

**Verdict P1.6i : VALIDEE.** Ce verdict concerne uniquement le correctif de
couverture. La clôture globale P1 est BLOQUEE ; voir
[P1_FINAL_AUDIT_AND_P2_GATE.md](P1_FINAL_AUDIT_AND_P2_GATE.md).

## Contrôles, sécurité et référence de retour arrière

AGENTS.md, le plan technique et le contexte factuel historique ont été consultés.
Les résultats anciens du ZIP d'octobre ne remplacent pas les vérifications du SHA
courant. Avant toute écriture :

| Commande exécutée depuis le worktree obligatoire | stdout | stderr | Code |
|---|---|---|---:|
| git rev-parse --show-toplevel | chemin exact du worktree | vide | 0 |
| git branch --show-current | fix/p16i-coverage-final-audit | vide | 0 |
| git rev-parse HEAD origin/main | SHA demandé, deux fois | vide | 0 |
| git remote get-url origin | https://github.com/laurentmaxence13-svg/rugger_bot_v1.git | vide | 0 |
| git status --porcelain=v1 --untracked-files=all | vide | vide | 0 |
| git status --untracked-files=all | working tree clean | vide | 0 |
| git ls-files | inventaire des fichiers suivis vérifié | vide | 0 |

Aucun avertissement ni Permission denied. Aucune création de branche nécessaire.
Aucune modification d'ACL, de .gitignore ou de configuration Git.
Aucun commit, push, fusion, secret lu, .env ouvert, installation, base utilisateur
ou connexion externe. Aucun ordre, signature, portefeuille financé ou argent réel.

La sauvegarde de référence est le SHA ci-dessus, complété par la copie originale :
`C:\Users\maxen\AppData\Local\Temp\rugger_p16i_2ba59cb4fc5f4f9aa0d22225e8b26fa4\baseline`.
Les sources corrigées et tests ont été exécutés dans le sous-dossier `patched` de
cette même racine temporaire. Seules des sources et fixtures de tests suivies ont
été copiées ; ni data utilisateur, ni base réelle, ni .env, ni launchlab_tx.json
racine. Les copies historiques bot/bot et tests/tests n'ont pas été auditées ou
exécutées comme sources actives.

## Cause et formule corrigée

Dans `bot/analyser/paper_engine.py:733`, paper_report calculait :

- un dénominateur constitué des mints distincts de lancements identifiés ;
- un numérateur constitué de TOUS les mints distincts de paper_prices, y compris
  ceux sans lancement identifié.

Les deux univers étaient différents. Le ratio pouvait dépasser 1. La requête
research_launches supposait également la présence de launch_candidates, même dans
un schéma de rapport ne possédant que la source recherche.

Le correctif, limité à paper_report, utilise :

```text
L = mints non NULL de launch_candidates, status='creator_identified'
    UNION mints non NULL de research_launches
Q = mints non NULL présents dans paper_prices
C = L INTERSECTION Q
O = Q MINUS L

launches_observed = |L|
launches_with_quotes = |C|
quoted_mints_total = |Q|
quoted_mints_without_identified_launch = |O|
quote_coverage = |C| / |L| si |L| > 0, sinon null
quotes_recorded = COUNT(*) de paper_prices
```

Les deux sources sont interrogées indépendamment si leur table existe. L'union
Python enlève les doublons entre sources et entre transactions d'une même source.
Les invariants sont `|Q| = |C| + |O|` et `0 <= |C| <= |L|`. Aucune utilisation de
min(1, ratio), aucun plafonnement, filtrage stratégique ou écriture en base.

L'identité connue ne prouve pas sa date : un lancement non daté avec mint identifié
appartient à L. Son observation reste distincte de l'autorisation d'entrée PAPER.
Les diagnostics existants launch_time_diagnostics sont conservés ; ils décrivent
les lignes de launch_candidates, pas une classification temporelle exhaustive de
la table recherche. Un mint dans une cotation n'est pas validé comme adresse
Solana par ce calcul ; les clés non NULL sont comptées selon le contrat existant.

## Reproduction chiffrée avant/après

Scénario synthétique effectivement exécuté sur les deux versions :
`L={a,b}`, `Q={a,x,y}`.

| Champ | Référence | Corrigé |
|---|---:|---:|
| launches_observed | 2 | 2 |
| quotes_recorded | 3 | 3 |
| launches_with_quotes | 3 | 1 |
| quote_coverage | 1,5 | 0,5 |
| quoted_mints_total | absent | 3 |
| quoted_mints_without_identified_launch | absent | 2 |

Le résultat attendu est 50 %, pas 100 % : ce scénario distingue la correction
d'une simple limitation artificielle du ratio.

## Contrat JSON et compatibilité

Le schéma nominal `paper-engine-report-v1` et tous les anciens noms de champs sont
conservés. Deux sémantiques sont corrigées explicitement :

- launches_with_quotes : ancien compte de tous les mints cotés ; nouveau compte
  des seuls lancements connus possédant une cotation. Pour retrouver l'ancien
  compte global, utiliser désormais quoted_mints_total.
- quote_coverage : ancien ratio d'univers différents ; nouveau ratio C/L.

Quatre champs sont ajoutés : quoted_mints_total,
quoted_mints_without_identified_launch, quote_coverage_scope avec la valeur fixe
`identified_launch_mints`, et market_detection_coverage avec la valeur `null`.
Ce dernier signifie INCONNU, y compris lorsque la couverture locale vaut 1.
Les consommateurs JSON stricts et les tableaux de bord externes n'ont pas été
inspectés ; ils devront accepter les ajouts et la correction sémantique documentée.

quotes_recorded compte les lignes, pas les identités. Une identité peut avoir
plusieurs prix. Dans une fixture historique autorisant un mint NULL, la ligne
compte dans quotes_recorded mais ne crée pas de mint distinct. Le schéma actif
refuse les mints NULL de research_launches et paper_prices ; cette contrainte
n'est pas modifiée en production. Les NULL légaux de launch_candidates sont exclus.

Un prix enregistré ne prouve ni fraîcheur du prix fournisseur, ni exécution,
liquidité disponible à la taille voulue, absence de slippage ou couverture du
marché. La couverture des champs fournisseur et la provenance existantes restent
séparées. Aucun volume de marché ou nombre de lancements manquants n'est inventé.

L'écriture atomique P1.6h est réutilisée sans modification : sérialisation complète,
temporaire dans le même répertoire, fermeture de son handle avant remplacement,
os.replace, retrait du temporaire en cas d'échec. Les tests conservent le rapport
précédent lors des erreurs JSON, écriture partielle et remplacement.

## Tests exécutés, résultats exacts

Python 3.13.15, pytest 9.1.1 et dépendances existantes, sans installation.
Interpréteur réutilisé uniquement :
`C:\Users\maxen\Downloads\rugger_bot_v1_paper (1)\rugger_bot_v1\.venv\Scripts\python.exe`.

Le lanceur existant tests/p16h_isolated_runner.py refuse une racine avec .git,
neutralise dotenv avant import, interdit les connexions et résolutions externes,
et désactive pyc, plugins pytest automatiques et cache pytest via l'option de
commande. Les seuls socketpair internes locaux d'asyncio sont admis avec une
exception locale au thread. Les bases sont en mémoire ou temporaires synthétiques.

| Exécution | Résultat |
|---|---|
| Baseline originale au SHA demandé | **485 passed, 1 skipped, 242 subtests passed**, 26,76 s, code 0 |
| Tests P1.6i finaux sur sources originales | **44 failed**, 2,25 s, code 1 |
| Six caractérisations d'audit sur sources originales | **6 passed**, 0,57 s, code 0 : elles confirment des défauts existants |
| P1.6i + audit + nettoyage P1.6h + supervision, ResourceWarning en erreur | **131 passed**, 3,90 s, code 0 |
| Suite active complète finale | **535 passed, 1 skipped, 242 subtests passed**, 28,72 s, code 0 |

Les échecs P1.6i sur la référence incluent l'absence des nouveaux champs, les
ratios erronés et le cas research-only sans table launch_candidates. Une première
reproduction directe a constaté launches_with_quotes=3 au lieu de 1. La formule
erronée et l'exemple 150 % → 50 % ont été vérifiés séparément.

Le skip reste `tests/test_research_pipeline.py:17`, « base utilisateur absente ».
La suite active est `tests --ignore=tests/tests`, comme la baseline ; les doublons
historiques ne sont pas ajoutés au nombre de tests. Les 50 nouveaux cas se
répartissent en 44 tests P1.6i et 6 tests de caractérisation d'anomalies P1.
Ces six réussites ne signifient pas que les propriétés de sécurité sont satisfaites.

Couverture des 20 exigences :

| Exigences | Cas exécutés |
|---|---|
| 1-7 : vide, orphelins seuls, un/deux lancements, prix répétés, plusieurs orphelins | 16 cas explicites de partitions de mints, dont partial_with_orphans_not_a_cap |
| 8-10 : union sans doublon, research-only, candidates-only | union_overlap, mixed_union et tests d'absence de chaque table ou des deux |
| 11-13 : non datés, transactions multiples d'un mint, multi-créations | duplicate_creation_identities, récupération transactionnelle de deux créations ; collecte réelle bornée et mockée de deux non-datés sans trade |
| 14 : NULL et doublons | NULL légaux candidats, fixture de prix legacy nullable, rejet NOT NULL actif de research_launches, doublons de chaque source |
| 15-16 : bornes et compteurs cohérents | 16 configurations supplémentaires de sources qui se recouvrent ; partition et ratio vérifiés dans tous les cas |
| 17-18 : finances et scanner | iterdump inchangé après chaque rapport, comparaison des sessions et fichiers/AST inchangés hors paper_report |
| 19-20 : JSON, atomicité, P1.6g/h | JSON strict sérialisable, erreurs JSON/write/replace, zéro temporaire, conservation des 71 tests de nettoyage et de toute la suite active |

Les fixtures NULL ont été alignées sur le schéma réel : les NULL interdits par
research_launches ne sont pas traités comme des états de production valides.
Seule une base synthétique de test est recréée pour représenter le cas legacy de
prix nullable. Aucune migration de schéma ou relaxation de garde en production.

## Comparaisons de non-régression

Six sessions normales avec les vrais collect_once, record_quote, rapports et
exports : vide, TP, SL, rejet, garde scanner fermée, observation non datée. Seuls
transport, cotations, décision de fixture et horloge sont remplacés. Les payloads
LaunchLab et les bases sont synthétiques.

- Capital final TP : **10,18 SOL** ; SL : **9,78 SOL** ; quatre autres cas : **10 SOL**.
- Identité exacte des tables, schémas SQLite, trades, tailles, frais, sorties TP/SL,
  décisions, statuts, audit, CSV prix et dataset, y compris leurs octets.
- Rapport de session et console identiques après retrait de la seule ligne du
  chemin temporaire du rapport. JSON périodiques identiques hors les deux champs
  corrigés et les quatre champs ajoutés, normalisés explicitement pour comparaison.
- Tous les fichiers Python actifs de production sont identiques à la référence,
  sauf paper_engine.py ; dans ce dernier, seule la définition paper_report diffère
  par AST. Aucun moteur de backtest, scanner, stratégie, TP/SL/trailing ou paramètre
  financier n'est modifié. La syntaxe du fichier reste analysable en Python 3.10 ;
  seul Python 3.13.15 a été exécuté.

Artefacts conservés dans baseline et patched :
normal_scenarios.json et normal_scenarios_normalized.json.
SHA256 normalisé commun :
`76fe78a7422a1fc1a9ce4c14ae98128e2b5970bcc34b390cf7a3901772da8aff`.
Les SHA256 bruts diffèrent comme attendu avec les champs nouveaux :
référence `9b16bb8aed90d6c818a871ef1613bfea31b49813f9bd8a6f8e1f399e7f9fca9a`,
corrigé `677fe804066dafa634e585419e5dc2d80e3d706debbb711d2cb0e5f23d469f10`.
Les fichiers SQLite physiques ne sont pas comparés octet par octet ; leur contenu
relationnel et leurs définitions le sont.

## Fichiers de la mission, reproduction et rollback

Fichier de production modifié : `bot/analyser/paper_engine.py`, uniquement paper_report.
Ajouts : `tests/test_quote_coverage.py`, `tests/test_p1_final_audit.py`,
`P1_6I_QUOTE_COVERAGE.md`, `P1_FINAL_AUDIT_AND_P2_GATE.md`.
Aucun autre fichier suivi modifié ; le lanceur P1.6h et son rapport restent intacts.

Commandes depuis une copie de sources sans .git et sans .env :

```text
python -B tests/p16h_isolated_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
python -B tests/p16h_isolated_runner.py -q tests/test_quote_coverage.py tests/test_p1_final_audit.py tests/test_paper_report_cleanup.py tests/test_scanner_supervision.py -p no:cacheprovider -W error::ResourceWarning
python -B tests/p16h_isolated_runner.py --compare
```

Pour reproduire l'avant : copier les sources au SHA demandé et y ajouter les deux
nouveaux fichiers de tests. La baseline 485 s'obtient en les excluant ; les 44
échecs de couverture et les six caractérisations d'audit se rejouent séparément.
La comparaison normalisée retire uniquement les six clés périodiques listées plus
haut ; tout autre changement de métrique, table ou fichier de sortie est rejeté.

Rollback proposé, non exécuté : conserver le diff et les quatre nouveaux fichiers
hors du worktree, puis depuis le worktree obligatoire :

```text
git restore --source=b89c4075d1c29adcd427d2f9947e59d81c81debb -- bot/analyser/paper_engine.py
```

Déplacer les quatre ajouts sauvegardés hors du worktree pour retrouver un état
propre. Aucun git clean, suppression récursive, remplacement de dossier, changement
d'ACL ou accès à une base n'est nécessaire. La branche reste locale, sans commit.

## Limites du verdict

La formule décrit les lancements connus dans les tables lues et les cotations
enregistrées ; elle ne mesure pas les lancements jamais détectés, la disponibilité
historique réelle d'un prix, sa fraîcheur ou l'exécutabilité. Les lectures du
rapport ne constituent pas un snapshot transactionnel global de tous les producteurs
concurrents. Les partitions L/Q/C/O sont mathématiquement cohérentes entre elles.
Les consommateurs externes restent non vérifiés. Le remplacement atomique P1.6h
ne fournit pas une garantie de durabilité après coupure électrique/kill brutal.
Aucune rentabilité démontrée et aucune autorisation de trading réel.

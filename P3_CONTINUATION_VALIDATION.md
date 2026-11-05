# Validation de reprise P3 — 27 octobre 2026

Base #21 `7ddddb9f73339242fbcb5b9bf10fa329c82fa700`. Livraison :
[PR #22](https://github.com/laurentmaxence13-svg/rugger_bot_v1/pull/22), non fusionnée.
Code `4f0fec80f7c62ae74778a04ae8b564a0104091e4`, arbre
`539f716e04666c126ee0c30b628d22417625951a`, identique au code testé localement.

## Défauts reproduits et corrigés

| Cause démontrée | Correction et régression |
| --- | --- |
| `_parse` remplissait sortie/route/frais avant de rejeter actualInputAmount ; une horloge invalide rejetait aussi après parsing. | `quote()` efface les valeurs utilisables si outcome != quoted, conserve le corps assaini. Deux cas dans `test_p3_quotes.py`. |
| `analyze_snapshot` abandonnait les faits mint/vault déjà décodés au contrôle supply. | Profil opt-in conserve faits, hashes, valeurs et différence avec statut unresolved ; aucun pricing débloqué. Cas synthétique de divergence réelle dans `test_p3_qualification.py`. |
| `collect_snapshot` propageait l’annulation pendant achat/vente sans reçu. | Helper partagé avec campagne persiste tentative/côté/taille/slippage/horloges avant propagation. Deux cas synchronisés par événement dans `test_p3_collection.py`. |
| Le fallback de `_record_quote` pour corps dangereux effaçait les métadonnées temporelles et HTTP. | Reçu minimal conserve timing, HTTP, taille, slippage et absence du corps ; aucun contenu dangereux recopié. Assertion causale ajoutée au test de refus existant. |

Un test complémentaire collecte un refus logique **synthétique**, exporte le journal,
supprime sa DB source et vérifie corps, taille de vente et temps dans l’archive.
Son message ROUTE_NOT_FOUND ne doit jamais être attribué aux refus réels historiques.

## Vérifications réellement exécutées

- Copie du commit #21 : 1 342 passed, 1 skipped, 242 subtests passed (4,51 s).
- Ancien code + les six cas causaux : 6 failed, attendus avant correction (0,33 s).
- Suite finale : 1 348 passed, 1 skipped, 242 subtests passed (4,24 s), warnings en
  erreur, code 0 et stderr vide. Réseau/dotenv interdits par le harnais isolé.
- Revue croisée collecte/campagne et sorties/supply, examen du diff et
  `git diff --check` : aucun bloquant identifié dans ce périmètre.
- 5 archives / 397 événements vérifiés vs toutes les valeurs de l’index Git.
  Quatre analyses v2 rejouées exactement. Quatre analyses v1 sans ordre explicite
  des comptes ne sont pas revendiquées comme rejouées.
- Oracle indépendant : 500 cas natifs SOL + 500 cas FX par produits croisés
  entiers/divmod, 1 009 rejets et frontière sous-lamport. Aucun défaut arithmétique
  démontré ; `accounting.py` et ledger historique inchangés.

Commandes reproductibles et fichiers JSON : `CODEX_CONTINUATION.md`.
Les 242 sous-tests ne s’ajoutent pas à une preuve économique. Aucun réseau marché,
scanner, boucle PAPER, transaction, nouvelle dépendance ou dépense de cette session.

## Observations réelles relues hors réseau

`validation/P3_ARCHIVED_EXIT_DIAGNOSTICS.json` distingue la nouvelle réanalyse
opt-in des résultats historiques inchangés. Les dix anciens corps de devis
fournisseur sont manquants (dont les deux refus de vente v2). Premier candidat :
plateforme UNKNOWN. Second : divergence supply -979542505800 à deux slots cohérents.
Cette cohérence exclut une simple jointure de nos lectures à des slots différents,
mais n’explique pas la cause de la divergence. Ni burn ni impossibilité de revente
après achat réel démontrés. Rentabilité : **INSUFFICIENT DATA**.

## Contrôle prospectif suivant — préparé, non exécuté

Question : une observation réelle conserve-t-elle les corps assainis, refus,
tailles et temps nécessaires au replay sans DB source ? Ce contrôle n’est pas
une étude de rentabilité et ne remplace pas une couverture indépendante.

Avant départ : conditions applicables de conservation, accès anonyme gratuit,
quota disponible et transport à établir ; fixer dans un nouveau manifeste Git
l’identité du run, le commit exécuté, registered_at_ms et son SHA256 avant tout
appel. Les anciens `plan.json`/`next_plan.json` et leurs résultats restent figés.
Ne pas présenter cette préparation comme une campagne déjà préenregistrée/exécutée.

Périmètre proposé : une fenêtre maximale de 60 s, 20 tentatives au total sans retry,
deux premiers candidats distincts WSOL issus des 100 premières lignes sort=new,
ordre reçu conservé ; échecs, exclusions et pages non téléchargées conservés.
Taille fixe 1 SOL et slippage demandé 100 bps, sans adaptation aux réponses.
Conserver aussi les candidats non qualifiés ; aucune entrée PAPER effective.
Pour chaque candidat : création vérifiée si accessible, comptes cohérents et
second état ultérieur ; devis token→SOL seulement si achat valide persisté.
La quantité hypothétique n’est pas un inventaire acquis ; l’état futur sans notre
achat ne décrit pas l’effet de cet achat. Tout manque garde le résultat inconnu.

Arrêts : budget/deadline, 401/403/429, réponse dangereuse ou schéma non compris,
incident de persistance ; aucun contournement ni nouvelle souscription. Archiver
les réponses autorisées, temps de réception/disponibilité, tailles exactes,
refus et champs manquants. Fermer le journal, exporter dans un répertoire neuf,
retenir ancre/tailles/hashes puis vérifier et rejouer sans DB originale. Pas de
corpus prolongé tant que ces contrôles ne sont pas démontrés. Une interruption
laisse son reçu et un export incomplet ne vaut jamais preuve de restauration.

Ce contrôle doit utiliser un nouveau plan/version compatible avec son périmètre ;
ne pas réutiliser l’identifiant d’un ancien run pour prétendre à une nouvelle
préinscription. Aucun appel live n’a été effectué ici. Voir le recontrôle
documentaire daté dans `P3_DATA_SOURCES.md`.

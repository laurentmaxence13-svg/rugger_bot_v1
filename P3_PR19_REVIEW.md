# Revue indépendante et correction de la PR #19

27 octobre 2026, Europe/Paris. Référence revue :
`02adb385bd11faf948a9f887686da418b794d3c9`.

La référence annoncée a été reproduite : **875 passed, 1 skipped,
242 subtests passed**, warnings en erreur, code 0 et stderr vide.

## Constat et corrections avant fusion

Trois revues distinctes ont examiné réseau/capture, journal et calculs financiers.
Les deux premières catégories de preuve ne sont pas remplacées par le total de tests.

| Sujet | Preuve | Traitement |
|---|---|---|
| Réseau : auth implicite | Avec NETRC synthétique, trust_env=True fournit une BasicAuth sans auth dans les kwargs. | Session anonyme trust_env=False, DummyCookieJar ; proxy/NO_PROXY explicites via configuration existante, sans lire netrc ni désactiver TLS. |
| Réseau : retry caché | Une déconnexion GET provoquait deux tentatives transport pour un budget logique de un. | Retry automatique désactivé ; incompatibilité transport refuse la capture avant tout envoi. |
| Corps quote/FX refusé | Une extension assainie api_key=[REDACTED] ou une URL FX invalide pouvait être rejetée par le journal sans reçu. | Reçu d'échec et digest conservés ; vente non demandée si preuve d'achat invalide. |
| Journal | Altération de chacune des sept colonnes détectée ; refus d'une DB PAPER WAL laisse DB/sidecars inchangés. | Aucun défaut bloquant démontré dans le périmètre journal fermé DELETE, disponibilité précommit déclarée. |
| Finance | 108 tests ciblés et 4 000 scénarios synthétiques indépendants : cash, frais, sortie entière et floor rationnel exacts. | Aucun défaut monétaire bloquant ; projections toujours non exécutées. |

Cinq régressions sont ajoutées. Quatre échouaient avant correction, puis passent.
Le cinquième impose le refus d'un transport sans interrupteur de retry reconnu.

Le réglage no-retry utilise un attribut privé aiohttp, faute d'option publique.
Le runtime contrôlé est aiohttp 3.14.5 ; une modification de cette interface doit
provoquer un refus, pas réintroduire silencieusement des requêtes. La compatibilité
réseau est testée séparément des fakes de collecte.

Limite financière non bloquante : les montants et P&L lamports sont exacts ; les
diagnostics Decimal de ratios/restes sont arrondis à 80 chiffres significatifs.
Un reste extrême juste inférieur à un peut donc s'afficher comme un. Ce diagnostic
n'est pas utilisé pour arrondir la sortie ni le P&L.

## Validation après correction

**880 passed, 1 skipped, 242 subtests passed**, warnings en erreur, code 0,
stderr vide. Groupe P3 : 181 tests réussis. Le skip historique de base utilisateur
absente reste inchangé. Tous les essais de revue utilisent des données synthétiques
et n'effectuent aucun accès marché, authentification réelle ou transaction.

```sh
/workspace/.cloud-env/rugger_bot_v1/venv/bin/python -B /workspace/.cloud-env/rugger_bot_v1/check.py -q tests --ignore=tests/tests -p no:cacheprovider -rs -W error
```

Les garanties P1/P2 et le ledger historique restent inchangés.
Les logs baseline/fixed de l'instance sont conservés sous
`/workspace/.cloud-env/rugger_bot_v1/p3_review19/`.

**Verdict : fusion admissible après ces corrections, pour les composants de
préparation seulement.** Aucun GO économique P3, prix exécutable ou rendement
réel ne découle de cette revue. La campagne suivante doit rester préenregistrée,
bornée, séparée et conserver échecs/rejets/gaps.

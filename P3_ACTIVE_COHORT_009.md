# Contrôle actif 009 — préparation, sources et garde-fous

28 octobre 2026, Europe/Paris. Base distante d0e57c68d3702967ee8ccfefe2e6e51713e82e99.
Aucune endurance 1000 événements relancée. Les contrôles006/007/008 ne sont pas
réexécutés. Ce contrôle pose la question nouvelle du protocole actif déjà préparé :
existe-t-il, dans le préfixe enregistré, des lancements à circulation positive
et à capacité de sortie suffisante pour un lot projeté de0,10SOL ?

## Sources et conditions d'accès

- [RPC public Solana](https://solana.com/docs/references/clusters) : adresse
  canonique `https://api.mainnet.solana.com`, lecture des comptes groupés, temps
  estimé du bloc, pages de signatures et corps publics. Les quotas effectifs
  ne sont jamais garantis par la documentation.
- [Services publics Raydium](https://docs.raydium.io/sdk-api/rest-api) :
  découverte via LaunchLab Mint API, lectures anonymes HTTPS.
- [Trade API Raydium](https://docs.raydium.io/sdk-api/trade-api) : seul
  GET /compute/swap-base-in est autorisé, montants exacts. Aucun endpoint de
  construction, simulation, signature ou envoi de transaction n'est appelé.

La documentation a été relue pendant cette session. Le préflight local confirme
proxy configuré, CA/TLS, retries désactivables, netrc et cookies désactivés.
Aucun secret n'est configuré dans le runtime, aucune valeur de.env n'est lue.
Les requêtes restent anonymes ; aucun compte facturable, wallet ou mécanisme
de paiement n'est utilisé. Le premier appel de marché fait partie du budget
unique : aucun probe supplémentaire, aucune alternance d'endpoint après erreur.
HTTP402/403/429, autre erreurHTTP, transport, timeout ou corps invalide :
reçu conservé puis arrêt global, sans retry. L'accès effectif reste inconnu
jusqu'à cet appel, et sa réussite ne certifiera pas les quotas futurs.

L'adresse canonique est choisie avant capture et figée dans le wrapper de plan.
Le plan de base et ses critères restent inchangés ; l'alias historique y est
conservé comme référence, avec remplacement de source explicite. Ce remplacement
préenregistré n'est pas un fallback et ne permet aucun appel à un second RPC.

## Protocole inchangé et publication avant acquisition

Maximum20requêtes toutes sources et erreurs comprises,60secondes monotones,
une seule exécution, aucun retry. Une lecture sort=new conserve100lignes au plus.
Les six premiers cas SOL uniques sont examinés ; les deux premiers cas actifs
ayant identité/supply/permissions et capacité de sortie du lot entier qualifiées
sont figés avant les résultats fournisseur. Taille0,10SOL, suivi15s minimum et
slot strictement plus récent. Quarts de lot préfixés uniquement après refus
logique initial HTTP200. Les compteurs, exclusions et inconnues restent conservés.
Le budget détaillé est celui de P3_ACTIVE_COHORT_PROTOCOL.md, jamais élargi.

Le runner manquant est ajouté dans bot/p3/active_cohort_campaign.py, en réutilisant
CampaignSession, les décodeurs, le provider quote-only et CaptureStore. Le helper
de bank accepte explicitement0,10SOL ; son défaut historique1SOL reste inchangé.
Les erreurs de transport conservent leur classe, jamais le texte d'exception.

Ordre obligatoire : publier le code testé ; créer un plan portant son commit
exact ; publier et relire le plan et les sources ; seulement ensuite lancer
une unique capture dans une nouvelle base dédiée. Toute réponse de marché devra
être postérieure au préenregistrement publié. Les bases utilisateur restent fermées.

## Conclusions possibles et impossibles, annoncées avant capture

OBSERVÉ : réponses réellement reçues, ordres de lignes, bytes de comptes, slots,
clocks locales, devis exacts et refus. MODÉLISÉ : prix de courbe, quantités
attendues, effet conditionnel de notre achat. INCONNU : frais propres applicables,
acheteurs indépendants, provenance/horloge manquante. REFUSÉ : critères de cohorte
ou devis rejetés, motifs conservés. Un index ne prouve pas une création ;
getBlockTime ne date pas un devis d'un autre fournisseur.

La taille de cohorte0,10SOL diffère du budget initial de référence1SOL. Aucun
devis n'est redimensionné. Sans quote propre au budget de chaque moteur, le
P&L A/B reste inconnu. Le Master conserve ses exigences de50cycles passés et
20groupes de créateurs ; elles ne sont pas abaissées pour produire un achat.
Deux candidats ne constituent pas une validation indépendante des24politiques.
Le protocole demeure development_only, sans affirmation de holdout indépendant.

La comparaison est utilisée sur les observations admissibles. Si les features
USD, la santé, les coûts ou les clocks manquent, les décisions ou résultats
restent inconnus. Aucun prixUSD/FX, historique créateur ou acheteur indépendant
n'est fabriqué. Les quatre mints déjà archivés sont identifiés dans SOURCE_REVIEW
pour distinguer nouveaux reçus et nouvelles opportunités indépendantes.

Aucun ordre réel, signature, dépense, changement actif ou fusion de PR.

## Résultat réellement obtenu

Le code testé a été publié dans4d967d0839134db878f47bfbeba3108780ca71c4.
Le plan a ensuite été publié dansd09db2998014580d2c2b47110b22471480eb24c8,
puis relu et comparé à son hash local avant le premier appel. Les sources
exécutées correspondaient aux empreintes du plan.

| Mesure | Résultat |
| --- | --- |
| Tentatives toutes sources |1 sur20 maximum |
| Fenêtre d'acquisition |8,009s sur60s maximum |
| Source tentée |Index LaunchLab, GET sort=new |
| Statut HTTP |INCONNU : aucune réponse reçue |
| Reçu d'erreur |TimeoutError,8005,542ms |
| Requêtes RPC / devis |0 /0 |
| Univers de lancements |INCONNU, pas un univers vide observé |
| Frames admissibles / décisions A/B |0 /0 |
| Cycles économiques strictement qualifiés |0 |
| P&L net et avantage Master |INCONNUS |

La limitation prouvée est un timeout de transport sur la découverte via la route
configurée. Le reçu ne permet pas d'attribuer l'échec au DNS, TLS, proxy, quota ou
serveur. Aucun429/403 n'a été observé. Aucune seconde tentative, aucun changement
de source, aucun probe ou contournement n'a été effectué. Les quotas futurs ne
sont pas certifiés. Les anciennes données ne deviennent pas de nouvelles preuves.

### Incident de nettoyage et corrections

Le journal contenait une clôture commitée à8,009s, mais le processus n'était pas
terminé : son nettoyage restait bloqué. Il a été terminé manuellement environ
200,951s après le début de la requête. La fenêtre d'acquisition a respecté la
borne, mais l'ensemble du processus n'a pas respecté60s. Cet incident est
conservé dans CLEANUP_INTERRUPTION.json; sa cause interne exacte reste inconnue.

Le rapport final, non encore publié avant ce nettoyage, a été reconstruit depuis
les4événements du journal fermé et sa chaîne vérifiée. Ce n'est pas une nouvelle
collecte. Le rapport utilise l'heure de clôture retenue, pas l'heure tardive de
lecture, et distingue univers inconnu et zéro ligne effectivement reçue.

Les corrections suivantes sont testées sans trafic de marché :

- Écriture atomique du rapport avant fermeture du transport et de l'exécuteur.
- Reconstruction pure d'un rapport depuis le journal fermé et le plan exact.
- Wrapper `tools/run_p3_active_cohort.py` : un seul enfant, arrêt demandé à58s,
  jusqu'à1s pourTERM puis1s pourKILL, sans retry. Répertoire et chemins absolus
  explicites ; aucun problème de résolution du module hors dépôt.
- Test réel d'un enfant local bloqué après écriture : rapport préservé, enfant
  terminé, aucun redémarrage. Ce watchdog n'est pas appliqué rétroactivement009.

Toute future exécution devra utiliser le wrapper et un nouveau plan publié
portant le commit corrigé. Le plan009 ne doit pas servir à relancer ce contrôle.
Une terminaison avant clôture doit garder un journal incomplet explicite, pas
inventer une clôture ou un résultat économique. Aucune base utilisateur n'est
ouverte et aucune SQLite n'est téléversée.

### Qualification et comparaison

OBSERVÉ : une tentative, ses clocks locales, son timeout et la clôture du journal.
MODÉLISÉ : aucun modèle de marché calculable à partir de ce contrôle.
INCONNU : univers, identités, activité, réserves, devis, coûts propres, acheteurs
indépendants, P&L et avantage des stratégies. REFUSÉ : poursuite du contrôle
après son premier échec ; aucune opportunité n'a été rejetée par une source
de marché reçue. Aucun refus fournisseur de vente n'est déduit de ce timeout.

Le comparateur existant a consommé l'enveloppe conservée, avec zéro frame. Son
rapport est marqué post-capture, sans test de stratégie ni holdout préenregistré :
il ne contient aucune décision, abstention observée, entrée ou sortie mesurable.
Les24politiques n'ont reçu aucune donnée indépendante nouvelle. Aucun classement
ni modification de paramètres.

L'écart de taille0,10SOL/1SOL, les frais propres inconnus et les exigences passées
du Master resteraient aussi à résoudre si le transport fonctionnait. Ces limites
étaient déclarées avant l'appel, sans transformer les quotes indicatives en fills.

### Preuves et état de reprise

`evidence/p3/active_cohort_009` contient l'export vérifié des4événements, ancré à
`fcacf5774468d680d85bb05987e691eb581759d82c25e38edbdce898eb40c78d`.
Les12bundles précédents sont inchangés ; l'index comporte13bundles et1698événements.
Les reçus de publication, résultat reconstruit, admission, comparaison, incident
et validation sont sous `validation/p3_active_cohort_009/`.

**1936tests réussis,1ignoré,242subtests**,13,21s,-Werror,stderr0. Le seultest
ignoré exige une base utilisateur absente. Aucune endurance1000événements relancée.

P3 reste ouvert :0nouvelle observation de marché et0cycle qualifié. P4 reste
sans corpus indépendant exploitable. P5 a reçu les corrections de conservation
et d'arrêt de processus nécessaires à cet incident. Prochaine action : rétablir
un accès de transport fonctionnel à la découverte, puis préenregistrer un contrôle
distinct avant toute nouvelle tentative de marché. Aucun ordre, signature,
dépense, modification de politique active ou fusion de PR.

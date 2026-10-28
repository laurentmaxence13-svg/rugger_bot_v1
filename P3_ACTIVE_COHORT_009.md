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

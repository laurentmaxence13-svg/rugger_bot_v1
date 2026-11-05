# P3-010 — transport et acquisition indépendante

28 octobre 2026, Europe/Paris. Base distante `298f3053718efbe3a1d4781e0731a53c3b205390`;
base locale `34eac75bad85cece99f20db8521ac4a3685d610f`, arbre identique.
Arbre propre à la reprise; aucune récupération, ancienne collecte ou endurance relancée.

## Avant diagnostic actif

Le chemin est celui imposé par l'environnement : HTTPS via proxy HTTP configuré,
TLS avec CA et nom d'hôte vérifiés, aucune route directe, authentification, cookie,
netrc, redirection, retry ou fournisseur de repli. Politique HTTP actuelle unrestricted,
enforced, observations_current=true; aucune identité, variable ou secret configuré.
Les champs de configuration ne prouvent pas la disponibilité d'une source.

Contrat officiel GET `/get/list`, `sort=new`, confirmé par la référence endpoint.
Le corps, les horloges, la provenance et l'exhaustivité ne sont pas garantis par la
seule description « Mints list ». Sources dans `validation/p3_transport_010/SOURCE_REVIEW.json`.
Les consultations de documentation sont séparées du diagnostic et de l'acquisition.

### Différentiel de P3-009

OBSERVÉ : TimeoutError à8s sans réponseHTTP; journal fermé puis processus bloqué.
Cause historique INCONNUE : absence de traces DNS/TCP/CONNECT/TLS/lecture sur009.
La bibliothèque effective utilise un ThreadedResolver : getaddrinfo dans l'exécuteur,
connexion proxy avec traces DNS aiohttp non transmises, tâche DNS protégée contre
l'annulation. asyncio.run attend ensuite la fermeture de l'exécuteur (jusqu'à300s).

REPRODUIT HORS RÉSEAU : getaddrinfo synthétique bloqué20s, requête expirée0,1s,
coroutine et ClientSession fermées mais asyncio.run encore bloqué. Watchdog externe
arrête ce cas, conserve le rapport et ne relance rien. Autre cas : enfant ignorant
SIGTERM, arrêté par SIGKILL. Ce mécanisme plausible n'attribue pas rétrospectivement
la cause009 au DNS. Pas de preuve historique de quota, de panne fournisseur ou de
refus d'authentification.

### Corrections

- Phases DNS du proxy observées explicitement; traces connexion, envoi d'en-têtes,
  réception d'en-têtes et classe d'erreur. Aucun message d'exception/secret/corps.
- Délais pour nouveau plan010 : total8s, connexion4s, socket3s, lecture4s,
  bornés à nouveau par le reliquat global. AF_UNSPEC et DNS système conservés.
- Traces enregistrées comme checkpoints du journal pendant la capture seulement;
  la clôture reste son dernier ancrage, aucune callback tardive après fermeture.
- Watchdog extérieur : délai d'enfant au plus58s + réserve2s TERM/KILL;
  arrêt des descendants du groupe même si l'enfant direct finit avant eux.
- Le rapport reste publié avant nettoyage; récupération009 inchangée.
- Plan010 distinct version2; comparaison0,10SOL/1SOL explicitement non redimensionnable.
  Les anciens plans et critères restent inchangés;009 ne doit jamais être relancé.

### Diagnostic autorisé, distinct d'une collecte

Plan figé `validation/p3_transport_010/DIAGNOSTIC_PLAN.json` avant exécution.
Une opération explicite de résolution du proxy, une poignée TCP au proxy, puis
au plus3HEAD vers les racines HTTPS des3hôtes figés, sans query ni lecture de corps.
Les résolutions internes nécessaires à ces connexions sont tracées; le nombre
exact de paquets DNS système reste inconnu. Aucun GET marché, RPC ou devis caché.
Plafond enfant23s + réserve2s, arrêt à la première erreur bloquante. Pas de retry.

Une réponseHTTP à la racine prouve seulement la connexionHTTPS au pair, pas la
validité du contenu de découverte, la fraîcheur des observations ou P3 économique.
Avant une éventuelle acquisition : publier un NOUVEAU plan010 associé au code
exact, le relire depuis GitHub et vérifier l'accès nécessaire.20appels/60s maximum,
watchdog obligatoire, refus et univers conservés. Sinon ne pas lancer la collecte.

## Obstacles économiques indépendants du transport

Le lot expérimental0,10SOL ne couvre pas l'achat de référence initial1SOL :
il faut des devis distincts à quantité exacte, jamais une règle de trois.
Les checkpoints causaux de features/santé/coûts propres et les clocks du fournisseur
restent requis par le comparateur. Des frais d'un autre utilisateur ne sont pas
les nôtres; absence de preuve ne signifie pas zéro. Aucun ordre ou fill exécuté.
Master exige toujours son historique qualifié; deux candidats ne valident pas24politiques.

À ce checkpoint prédiagnostic : aucune nouvelle requête de marché ou diagnostic
actif exécuté, zéro observation nouvelle, zéro cycle strict et aucun P&L admissible.
PAPER ONLY, politique active inchangée, PR22 ouverte sans fusion ni dépense.

Validation du code source : 1970 passed, 1 skipped, 242 subtests passed in 15.26s; stderr0. Tests ciblés :53réussis.

# P3-011 — voie de recherche isolée et cycle indicatif à quantité exacte

29octobre2026,Europe/Paris. P0 est sauvegardé dans36f5fbe, après téléchargement
réel et vérification de l'archive47événements/rapport depuis GitHub. Aucune010relancée.
P3-010 contient100lignes de sélection,6pools,3actifs,2capacités modélisées; aucun
JSON complet de découverte, devis externe ou cycle qualifié. Sa limite de rétention
reste explicite, sans reconstruction des champs de marché absents.

## Revue et intégration de PR24

Source examinée `bef10cc63a87f4142886b9880cd1575e02cfa8c5`, branche research/p3-offline-gate-20261028.
Le module research_gate et ses tests sont repris puis corrigés, sans fusion dePR24.
Le sélecteur STRICT, certification, parser des comptes, bridge d'inventaire strict,
protections, politiques actives et ledger restent inchangés. Aucun nouvel audit
historique de rentabilité ni interface ajouté; l'audit déclaratif annexe dePR24
n'est pas intégré au pipeline économique.

Défauts reproduits de la proposition : écran favorable détaché d'un autre mint,
pool, budget, quantité ou produit de vente modifié. Ils sont refusés par
recomputation intégrale de l'écran au budget exact et à son âge relatif. Ce test de
cohérence n'atteste pas une horloge de marché. Les vrais clocks sont liés lors de
l'acquisition. Pins publiés, chaque check et absence d'autre blocage sont requis.

RESEARCH_ONLY autorise une observation indicative lorsque **seul** le seed admin
historique de plateforme est UNKNOWN. Tout autreUNKNOWN ouFAIL de sécurité reste
bloquant. STRICT_OBSERVATION permet aussi d'étudier un pool totalement vérifié,
sans permission de trading. Même budget global de2candidats, sélection figée avant
réponses économiques. La sélection stricte complète est conservée séparément.

Application aux véritables structures de010 :2RESEARCH_ONLY,0STRICT; sélection
stricte égale à l'original et entrées inchangées. Cette analyse rétrospective de
développement n'est pas une acquisition indépendante ou un résultat de marché.

## Démonstration fonctionnelle

Tests d'intégration sur octets de comptes synthétiques décodés par le vrai parser,
PDAs publiques et devis synthétiques.4lots, budgets0,10 et1SOL distincts,8paires
immédiat/suivi>=15s. Quantités1000 et10000 sur fixture, jamais redimensionnées.
Les écarts négatifs de fixture ne sont pas des performances économiques.
Résumé et rapport compressé sous validation/p3_research_011/. Le premier essai
pour conserver la démo dans/workspace a été refusé par le harness; elle a été
reproduite dans/tmp, sans affaiblir sa protection contre les bases utilisateur.

L'absence actualInputAmount/clock ne supprime plus le Q coté en voie RESEARCH_ONLY,
mais laisse son hypothèse de remplissage explicite. Toute quantité ajustée explicite,
vente partielle, clock contradictoire ou source périmée est refusée pour la paire.
Les suppléments0/5000/100000/1000000lamports sont hypothèses, jamais frais observés.
Les frais de route inclus dans la sortie ne sont pas comptés une deuxième fois.
P&L net marché resteUNKNOWN, aucun ordre/fill/position observé n'est annoncé.

## Nouveau protocole011 préparé avant acquisition

Une seule acquisition indépendante,20requêtes/60s maximum, watchdog58s+réserve2s,
proxy géré et TLS système, sans retry/fallback/redirect/auth. Premier problème
HTTP/transport/malformed : reçu conservé et arrêt global. Une réponse HTTP200
métier refusée reste un refus, pas un prix; seuls les horizons figés continuent.

Nouvelle hypothèse prospective : l'index officiel `sort=lastTrade` examine une
activité récente plutôt que de répéter une cohorte triée par création. Ce paramètre
est documenté, aucun endpoint alternatif ou contournement.100lignes de sélection,
préfixe6SOL,2cas maximum; mêmes checks de sécurité, aucune sélection selon résultat.
L'exhaustivité globale et l'ordre causal de l'index restent non prouvés.

Les4intentions (2mints x0,10/1SOL) sont figées avant la première quote, uniquement
aux tailles où modèle et capacité de vente sur bank observée sont admissibles.
Chacune a sa quote d'achat, Qattendu et première vente entière. Le suivi commence
au moins15s après toutes les réceptions initiales, avec bank de slot supérieur,
puis vente de chaque Qentier. Aucune recherche historique ou quart de lot ne
consomme le quota. La référence éventuelle1SOL reçoit ses propres quotes, pas un
scaling. Les routes du fournisseur peuvent traverser d'autres pools que la bank
LaunchLab : aucune égalité n'est postulée; IDs de route conservés séparément.

Budget :4appels screening,8quotes initiales,2bank/time suivi,4ventes suivi,
2lectures de référence de frais. Le coût d'autrui ne certifie pas le nôtre.

Plan et source exacte doivent être publiés puis relus avant la première requête.
Les répétitions de mints/créateurs sont signalées, jamais comptées comme essais
indépendants. Paires indicatives reçues, cycles économiquement qualifiés et
transactions exécutées restent trois mesures distinctes. A/B reçoit uniquement des
frames causalement admissibles; pas de trades imposés pour remplir deux livres.
Aucune optimisation/promotion des24politiques sur deux candidats.

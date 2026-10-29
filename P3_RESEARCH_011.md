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

## Résultat réel011 —29octobre2026

Plan publié/relu `7016e3469e5a09658be12ddb3488f7b5ca0604ac`, code
`ae89a344bec3855c2cb6f26f75bab4865ac73ac0`, hash
`76f9aff77d32b7da4112c370a2ea816447379823876898ca563886846d233ce8`.
Une acquisition,20requêtes/27686ms; processus27933,295ms, fin normale, watchdog
non déclenché, aucun retry/fallback.1GET index,7lecturesRPC,12GET de devis.

100lignes de sélection conservées,6pools screenés,2RESEARCH_ONLY et0STRICT.
Les2mints et leurs2créateurs déclarés n'apparaissent pas dans les537mints du
référentiel figé. Cela ne prouve pas l'indépendance économique des acteurs.
4achats indicatifs propres,8ventesQentier,0refus.4lots x2horizons : **8paires
indicatives reçues**, pas8essais indépendants ou transactions. Aucun ledger touché.

| Token | Entrée SOL | Q atomique coté | Sortie SOL cotée | Écart conditionnel SOL | Friction |
|---|---:|---:|---:|---:|---:|
| Ev5y…SpF |0,10|604318709293|0,097250623|-0,002749377|2,749377%|
| Ev5y…SpF |1|5970080462587|0,949288793|-0,050711207|5,0711207%|
|6NPu…ocs|0,10|3114722229888|0,096915555|-0,003084445|3,084445%|
|6NPu…ocs|1|30305442885780|0,918298280|-0,081701720|8,170172%|

Les sorties immédiates et de suivi donnent les mêmes montants; ce fait reçu ne
prouve ni fraîcheur de la source ni absence d'activité de marché. Horizons réels
depuis décision d'inventaire :19,646–20,707s. Les deux sorties possibles d'un
même lot ne s'additionnent pas en P&L. Pas de résultat de portefeuille agrégé.

Les12réponses déclarent explicitementactualInputAmount égal à la requête; cela
reste une déclaration du moteur de devis, pas un spend ou fill observé.
LeurspoolId correspondent aux pools screenés, mais aucuncontextSlot/sourceTimeMs
n'est fourni. L'égalité de l'identifiant du pool ne certifie pas le même état de
réserves. Banks observées auxslots462777988/462777990/462778085.

Les frais de route explicitement rapportés représentent environ0,002477–0,002481SOL
pour0,10SOL et0,024124–0,024516SOL pour1SOL. Ils sont déjà inclus dans les sorties.
Le reliquat de l'écart n'est pas attribué arbitrairement à l'impact : états et
horloges de devis ne sont pas prouvés. Un autre trade observé a payé5003lamports
(5000base+3priorité), sans applicabilité démontrée à nos opérations hypothétiques.
Nos frais réseau/priorité/ATA/rent/échecs restent inconnus. Les sensibilités
0/5000/100000/1000000lamports gardent les quatre cas négatifs; pas de coût nul imputé.

Le modèle cohérent propre achat→revente sur la même bank observée, calculé par le
moteur existant, donne environ-2,4844% avant suppléments. Il diffère du couple de
devis observés sans notre achat. Des achats extérieurs **hypothétiques** d'environ
0,41–0,95SOL seraient nécessaires pour neutraliser la courbe dans ces états; ce
seuil calculé n'est ni une prévision de flux ni une rentabilité constatée.

### Admission économique et comparaison

**0cycle P3strict,0cycle économiquement qualifié, P&L net marchéUNKNOWN.**
Le comparateur existant reçoit son enveloppe à100lignes, mais0frame STRICT admissible.
Aucune décisionA/B, performance relative ou gagnant n'est inventé. Les budgets
0,10/1SOL ont leurs devis propres; l'écart de taille est résolu au niveau des données,
mais identité stricte,clocks,costs propres etfeatures/santé causales manquent encore.

Les24politiques ne sont pas optimisées/promues sur deux cas. Les hypothèses de
coût/taille/flux ont été figées **après analyse de développement**, pour un prochain
jeu séparé; aucun holdout lu ou réutilisé. Configuration agressive et protections
conservées. Pas d'endurance ni d'ancien contrôle relancé.

### Conservation et reproduction

142événements exportés, ancre
`40532579c596a58c0676ca55a074da302c737293b6841377b4fa00fd1bcff997`.
15bundles/1887événements au total;14anciens inchangés. Rapport reproduit exactement,
8analyses de banks et12corps de devis rejoués sans réseau niSQLite. Le JSON complet
de découverte reste absent (refus unsafe_or_oversized);100lignes/digests conservés.

`RUGGER_NO_DOTENV=1 python -B validation/p3_research_011/reproduce.py`

Preuves : evidence/p3/research_011, ADMISSIBILITY.json,COST_DECOMPOSITION.json,
COHERENT_OWN_ENTRY_MODELS.json,RESERVE_CHANGE.json,AB_ADMISSIBILITY.json et
REPLAY_VERIFICATION.json. Suite source validée :2040pass/1skip/242subtests,15,90s,
-Werror,stderr0. Aucune collecte supplémentaire après les20appels.

Prochain obstacle économique : obtenir une fraîcheur/source de cotation prouvée
ou un protocole conditionnel de bank explicitement distinct, des coûts propres
applicables et des features causales pour comparerMaster/référence. Une réponse
API et des paires de devis ne suffisent pas à certifier P3 ou un avantage net.

# P5 — sources internes et endurance hors réseau

28 octobre 2026. Les états opérationnels proviennent maintenant des chemins
existants du scanner, et non d'un fichier de heartbeats déclaré par un opérateur.
`ScannerHealth(require_observations=True)` est activé dans les points d'entrée
supervisés `main.run` et `paper_engine.run_with_scanner`. Son mode historique sans
observation demeure disponible pour les anciens appelants spécialisés.

- Chaque réponse existante `rpc_json` de récupération de transaction ou de page
  de signatures renseigne RPC sain si elle retourne le résultat dict/list attendu;
  résultat absent ou exception renseigne indisponible. Aucun appel ajouté.
- Le callback d'état WebSocket existant conserve l'abonnement confirmé et les
  déconnexions. Une notification issue de cet abonnement renouvelle sa preuve de
  réception. Elle ne peut pas établir ou rétablir l'abonnement à elle seule.
  La découverte d'un token, son prix et son ancienneté ne servent jamais de preuve
  de connexion. Aucun ping ni abonnement supplémentaire n'est envoyé.
- La fraîcheur vérifie simultanément horloge civile et monotone, plafond120s,
  cohérent avec le garde de couverture existant. Inspection d'un snapshot ne
  renouvelle aucun timestamp. Source inconnue, périmée, discontinue ou déconnectée
  interdit l'admission; la panne définitive de la durée de vie ne peut être remise
  à zéro par une nouvelle réponse ou une ligne SQL fraîche.
- Le rapport périodique PAPER inclut `operational_health`, produit depuis ces
  callbacks et le même ledger. Une couverture en rattrapage reste refusée même
  si les transports sont sains. Les contrôles de capital, coûts inconnus et
  inventaire existants restent applicables; aucun nouveau portefeuille.

Un réseau silencieux sans nouvelle preuve peut devenir périmé. Le logiciel ne
prétend pas qu'une socket restée ouverte a reçu récemment un pong. La réception
effective d'une notification ou d'un résultat RPC peut renouveler la source dans
une durée de vie encore saine; un scanner définitivement défaillant exige une
nouvelle durée de vie et une couverture de nouveau établie.

Tests ciblés: `test_internal_scanner_health.py` vérifie démarrage inconnu,
abonnement obligatoire, ancienneté civile/monotone, interruption, retour des
sources, panne persistante, cohérence SQL/rapport et les vrais wrappers du scanner
avec exactement les deux appels RPC simulés prévus. Deux fixtures historiques
de source saine ont été complétées pour inclure ces callbacks.

Endurance reproductible et résultats: `P5_ENDURANCE_METHOD.md`,
`validation/P5_OFFLINE_ENDURANCE.json`.1000cycles virtuels sur83h20min,1000jambes et1000replays
ignorés,10sauvegardes/reprises,4021invariants,750refus d'admission et reliquat0.
Ces résultats vérifient uniquement le logiciel avec frais et produits synthétiques.
Aucun réseau de marché, serveur permanent, base utilisateur ni déploiement exécuté.
L'endurance en conditions réelles24h/24 reste ouverte.

La version2 de l’endurance utilise ces callbacks internes avec transports factices;
les reçus ne sont plus produits par un dictionnaire de heartbeats utilisateur.

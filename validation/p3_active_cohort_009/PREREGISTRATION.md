# Préenregistrement du contrôle actif009

Ce plan porte le commit source exact `4d967d0839134db878f47bfbeba3108780ca71c4`
et les hashes de ses sources testées. PLAN.json et PREREGISTRATION.json doivent
être publiés puis relus sur GitHub AVANT la première requête du contrôle.
Aucune collecte n'a encore eu lieu à ce stade.

Une seule tentative globale,20requêtes/60secondes, mêmes critères actifs et budget
0,10SOL que le protocole préparé. Le premier appel vérifie l'accès effectif et
consomme son budget ; aucun probe ou retry additionnel. Arrêt global au premier
refus HTTP, timeout, erreur de transport ou corps invalide. Endpoint RPC canonique
figé, aucun fallback. Réponses et horloges réellement fournies conservées.

L'univers complet, le préfixe de six, les exclusions et les deux sélections au
maximum sont conservés. Les refus et résultats inconnus ne sont pas supprimés.
Les anciennes observations ne sont pas injectées comme nouvelles preuves ;
les mints récurrents seront signalés sans revendication d'indépendance.

Limites annoncées : 0,10SOL n'est pas le budget initial1SOL de la référence,
les frais propres restent inconnus sans source applicable, les acheteurs distincts
ne sont pas indépendants et les clocks des devis ne viennent pas du RPC voisin.
Le Master peut rester WAIT et zéro cycle strict peut demeurer le bon résultat.
Les modèles conditionnels ne sont ni des fills ni des performances certifiées.

Aucun ordre blockchain, wallet, clé privée, signature, dépense ou fusion de PR.

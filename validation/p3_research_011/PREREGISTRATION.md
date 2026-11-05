# P3-011 — préenregistrement

Code publié et relu : `ae89a344bec3855c2cb6f26f75bab4865ac73ac0`.
Arbre testé : `a12fe1efdd3b867662765fb0696b53ddd4302f98`.
Plan SHA256 canonique : `76f9aff77d32b7da4112c370a2ea816447379823876898ca563886846d233ce8`.
Horloge : `1793254826514` ms epoch.

Source officielleLaunchLab `sort=lastTrade` (paramètre documenté), RPCcanonique et
TradeAPI GETcompute. Aucun fallback, login, dépense, construction de transaction
ou wallet. Conditions et limites exactes dans PLAN.json;20appels/60s global,
watchdog58+2s obligatoire. L'accès exécuteur est demandé par le mécanisme prévu
avec proxy géré conservé. Aucun diagnostic réseau supplémentaire avant ce plan.

Critères et premier préfixe6 fixés,2candidats au total avant les prix. STRICT
conservé, seulplatform_pda historiqueUNKNOWN admis àRESEARCH_ONLY, aucunFAIL
admis. Les4intentions de taille sont figées avant toute réponse économique.
Chaque0,10et1SOL a ses devis propres et ventesQentier; aucune interpolation.
Horizon initial puis>=15s après tous les reçus initiaux, nouvelle bank à slot
supérieur. Refus HTTP200 conservés aux horizons prescrits; première erreur
HTTP/transport/malformed bloquante arrête globalement après conservation du reçu.

OBSERVÉ : réponses réellement reçues, quotes indicatives, octetsRPC, horloges
locales et champs source présents. MODÉLISÉ : propre achat, inventaireQ et
net conditionnel pour coûts hypothétiques0/5000/100000/1000000lamports.
INCONNU : sourceTime/contextSlot/actualInput/costs s'ils manquent; pas de zéro
imputé. REFUSÉ : détails du refus et reliquat théorique gardés.
Routes externes potentiellement différentes du poolscreené; aucune égalité
postulée. Aucun devis n'est une transaction ou une acquisition réelle.

Le référentiel des identités précédemment vues est figé pour annoter les
répétitions; elles ne deviendront pas essais indépendants. Aucun résultat
historique n'est utilisé comme nouvelle preuve. Ne pas optimiser les24politiques
sur cette cohorte. A/B uniquement si quantité,chronologie,costs et features
causales sont admissibles; pas de bénéfice déduit d'un livre vide.

Publier et relire ce plan avant toute acquisition. Ne jamais relancer010.

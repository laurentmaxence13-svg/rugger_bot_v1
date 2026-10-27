# Contrôle de sortie active 007 — prêt, non exécuté

Objectif expérimental : observer une vente indicative sur une banque possédant
réellement du stock net vendu et des réserves, puis comparer le premier état et
une confirmation ultérieure. Cette expérience reprend l'hypothèse historique
premier signal/confirmation, sans changer la stratégie ni les seuils actifs.
Elle ne clôture pas une position acquise et ne démontre pas une rentabilité.

Implémentation : `bot/p3/active_exit_campaign.py`. Accès publics/anonymes limités
aux mêmes lectures que le contrôle v3 ; conditions dans P3_SHORT_CONTROL_ACCESS.md.
Plafond global **20 tentatives / 60 secondes**, aucune redirection, retry ou
bascule RPC. Maximum nominal : 16 lectures si trois graphes sont examinés.

1. Une découverte sort=new, 100 lignes retenues, préfixe de 20 pools SOL uniques
   dans l'ordre reçu. Préfiltrage par une seule lecture RPC groupée de 20 comptes.
   Garder tous les refus et données manquantes, sans référence exhaustive prétendue.
2. Parmi les trois premiers pools actifs avec stock et réserve positifs, examiner
   les graphes dans cet ordre. Discriminators, liens/PDA et propriétaires doivent
   être cohérents. Une unique UNKNOWN platform_admin peut autoriser un diagnostic
   explicite, jamais l'admission. Supply/permissions/calculs refusés restent refusés.
3. Vérifier la vente sur l'état OBSERVÉ, séparément du calcul après notre propre
   achat hypothétique. Sélectionner le premier graphe passant ce contrôle.
4. Fixer et persister **q=floor(real_a/100)** avant tout devis. Ce stock agrégé
   n'est pas notre inventaire et q n'est pas redimensionné après une réponse.
   L'achat indicatif de référence reste **1 SOL / 100 bps**, indépendant de q.
5. Recherche de création bornée ; si inconnue, la trace reste diagnostique et
   non admise. Recueillir achat de référence et vente q au premier état.
6. Attendre au moins 15 secondes monotones depuis la fin du snapshot initial.
   Exiger un slot de suivi strictement supérieur. Réexaminer identité, supply,
   permissions et liquidité pour q. En cas de refus local, conserver ce refus,
   sans modifier q ni envoyer un devis contre un état désormais non qualifié.
   Sinon recueillir les deux références achat/vente q à ce second état.
7. Toutes les sorties ont execution_verified=false, position_acquired=false,
   strict_exit_qualified=false et net_pnl_lamports=null. Les devis fournisseur
   sans slot/heure source et frais complets ne deviennent pas un rendement.

La quantité de vente diffère intentionnellement du montant attendu du devis
1 SOL : elle sert à mesurer une compatibilité de sortie dans la banque observée,
pas à simuler la clôture de cet achat. Le bridge `exit_qualification.py` traite
séparément les scénarios d'inventaire attendu/minimal d'un aller-retour.

**Non exécuté après le HTTP 429 observé au contrôle 006.** Le quota courant et
son délai de reprise ne sont pas connus : l'ancien collecteur n'avait pas gardé
Retry-After. Le correctif conserve désormais ce délai ou son absence explicite ;
il ne programme aucune reprise et ne change pas de fournisseur pour contourner
une limite. Aucun appel de marché supplémentaire effectué pendant cette phase.

Après rétablissement documenté du quota, utiliser un plan source/versionné et de
nouveaux chemins exclusivement réservés, puis fermer/exporter/ancrer/restaurer
et rejouer avant toute interprétation. La limite de collecte soutenue reste active.

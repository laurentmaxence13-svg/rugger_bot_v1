# Préparation P4 — comparaison conditionnée aux données P3

Protocole de recherche préparé le 27 octobre 2026, **non exécuté**, sans budget de
collecte supplémentaire. Ce document n'active aucun modèle ni ordre.

Hypothèse issue de `MEMCOINS_HISTORIQUE_RECUPERE.md` et
`AGGRESSIVE_STRATEGY_CONTEXT.md` : une entrée au premier signal qualifié peut
gagner en précocité, mais perdre en sélection et en qualité de sortie par rapport
à une confirmation. La comparer à une entrée après au moins 15 s et un slot plus
récent, sans changer le scoring actif. Chaque entrée engage le même budget SOL
préfixé mais conserve **sa propre quantité** ; aucune petite quote commune n'est
substituée aux deux inventaires.

Avant toute donnée nouvelle, enregistrer un protocole de collecte borné et gratuit,
ses candidats dans l'ordre d'arrivée, fenêtres, règles de fraîcheur, coûts, règles
de sortie, critères d'exclusion et séparation développement/validation. Choisir
les effectifs et leur justification avant évaluation ; ne pas choisir les seuls
tokens revendables ni modifier des paramètres après consultation du holdout.

La référence est `shadow_final` avec ses règles actuelles : créateur, relais,
wallets suspects, concentration, momentum, liquidité et TP/SL/trailing. Les
comparaisons ultérieures du score ou des sorties modifient un facteur à la fois,
avec le même inventaire, mêmes frais et mêmes observations disponibles à l'instant
de décision. Des activités créateur/wallet inconnues restent inconnues. Les
inspirations de traders non vérifiées ne deviennent pas des règles attestées.

La future comparaison réutilisera le portefeuille et les jambes atomiques livrés, sans second
capital : taux de qualification, fraction liquidée, reliquat, latence, coûts,
pertes nettes et drawdown avant classement du rendement. Publier aussi les refus
et absences, regrouper les dépendances par créateur/session, garder les résultats
conditionnels séparés des exécutions. Un lot incomplet n'est pas une perte nulle.

État courant : aucun couple de cycles économiques complets indépendants. Aucun
vainqueur, rendement de stratégie ou nouvelle pondération à retenir. Les prochains
devis doivent porter sur le reliquat entier et satisfaire les conditions P3,
avant toute optimisation ou adoption de paramètres.

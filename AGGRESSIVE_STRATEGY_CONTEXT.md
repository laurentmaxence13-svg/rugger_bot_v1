# Reprise stratégique ciblée — sources réellement présentes

Actualisation fonctionnelle du 27 octobre : aucune règle ou pondération modifiée.
Le moteur shadow_final est désormais exécuté intégralement par la démo CLI.
Le contrôle 007 a testé la comparaison premier état/confirmation à q fixe sur une
banque active : deux devis de vente disponibles et slots croissants, sans gain
économique démontré. La quantité ne ferme pas l'achat de 1 SOL indépendant ; ce cas ne
justifie aucun réglage de score/TP/SL ni choix d'une stratégie. Voir la livraison
`RUGGER_V1_FUNCTIONAL_RELEASE.md` et l'analyse `validation/P3_ACTIVE_EXIT_007_ANALYSIS.json`.
Les paragraphes suivants conservent l'état de recherche antérieur.

27 octobre 2026. Lecture ciblée du dépôt courant, sans marché ni secret. Aucun
paramètre ou moteur modifié : aucune correction supplémentaire du scoring n'a
été démontrée dans le chemin de production inspecté.

## Ce qui est effectivement retrouvé

- `MEMCOINS_HISTORIQUE_RECUPERE.md` §2–3,7–8 : détection précoce LaunchLab,
  comportement créateur, relais, concentration, activité même slot, momentum,
  comparaison sniping premier bloc / confirmation et stress coûts/latence.
  Ce document est une récupération textuelle du 22 octobre, pas l'intégralité
  de l'ancienne conversation.
- FomoIsBack / Antoine Markarian / F Project apparaît uniquement dans la liste
  des pistes de recherche (§8, ligne135). Aucune règle privée, entrée, sortie,
  performance, donnée d'entraînement ou méthode vérifiée de cette personne n'est
  disponible dans le dépôt. Ne pas baptiser une nouvelle heuristique de son nom.
- `MANIFESTE_SOURCES.json` confirme la provenance ZIP/empreintes de ces notes,
  pas une validation des stratégies ni l'accès aux archives historiques externes.

## Paramètres actifs prouvés, distincts des notes historiques

`bot/analyser/final_decision_engine.py:decide` : score initial50, seuil45 par
 défaut ; bonus créateur récurrent et momentum modérément positif, veto vente
 développeur/relais, effondrement, fomo extrême et slippage extrême.
Le seuil62 mentionné dans les anciennes notes était celui d'une autre version,
non celui de ce chemin actif. Aucun changement de seuil dans cette reprise.

`bot/analyser/paper_engine.py` CLI/run : capital10SOL, position10%, max3 positions,
20 entrées/jour, perte quotidienne réalisée10%, poll15s,10 candidats/cycle par
 défaut. La configuration personnalisée du propriétaire n'a pas été lue : ce
sont les valeurs par défaut du code, pas une affirmation sur son `.env`.

`decide` : TP10%/SL8%/1800s/trailing5% à la base ; branche faible liquidité
7%/6%/900s/3,5% ; liquidité>=25000USD14%/8%/2700s/6% ; momentum constructif
12%/7%/1800s/5% ; certains risques observés7%/5%/900s/3%.
Ces valeurs sont une politique PAPER exploratoire et non des taux de réussite.
La détection par poll, cotation puis enrichissement séquentiel n'est pas une
preuve d'exécution au premier bloc ; aucun gain de latence mesuré n'est inventé.

## Expériences déjà achevées : ne pas les recommencer pour choisir un vainqueur

`P2_SYNTHETIC_PROTOCOL.md`, `QUANT_VALIDATION_REPORT.md`,
`benchmarks/p2_synthetic_v1/` : trois mondes inventés de300mints, neuf candidats
 de développement au total,27 sensibilités finales préenregistrées. Dans chaque
monde, cautious_momentum est la meilleure règle de fixture au stress figé,
mais reste négative en validation : -1,724606 / -1,134843 / -2,324606SOL.
Ce nom ne désigne ni une bascule de production vers un mode conservateur,
ni un avantage de marché. Ne pas réduire le coût de sélection après lecture
 du holdout pour sauver une règle. Le score et les seuils actifs restent ceux
ci-dessus jusqu'à preuve comparative nouvelle.

## Hypothèse prioritaire issue de ces recherches et du blocage de sortie

Tester l'effet causal de SA PROPRE entrée avant de confondre un refus de vente
avec une impossibilité après achat. Une quote de vente du stock théorique
achetée peut dépasser le stock vendu réellement par la courbe avant cet achat.
Cette hypothèse est déjà implémentée dans
`bot/p3/launchlab.py:constant_product_projection`, qui modifie explicitement
les réserves de manière contrefactuelle pour la réversion immédiate ;
`observed_sell_projection` reste séparée et n'ajoute jamais d'achat au futur
observé. `tools/analyze_p3_retention_exits.py` applique déjà une seconde méthode
par invariant aux nouvelles preuves. Aucun second calcul redondant ajouté.

Cette distinction doit précéder les comparaisons agressives de taille et
 d'horizon : les deux candidats de la collecte courte ne fournissent pas un
échantillon où optimiser TP/SL, ni une sortie future après sa propre entrée.
Une future comparaison premier signal / confirmation doit figer ses fenêtres
et ses coûts, enregistrer les absences et rejets, puis mesurer la même quantité
préfixée aux deux horizons sans choisir les seuls tokens revendables.
La preuve de rentabilité reste dépendante de sorties économiques futures,
coûts additionnels et corpus indépendant : aucune inspiration ne remplace ces
observations et aucun refus n'est transformé en prix ou en profit.

## Une hypothèse de bug écartée avant modification

`build_features` ajoute le prix courant à l'historique ; une duplication pouvait
sembler gonfler quote_count. Le chemin réel `paper_engine.collect_once` appelle
`skip_recorded_quote` AVANT les features, puis insère via `record_quote` APRÈS.
Une observation déjà stockée au même timestamp n'atteint donc pas le scoring.
Pas de défaut production reproduit : pas de patch ou de PR artificielle.

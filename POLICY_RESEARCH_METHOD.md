# Recherche structurée des politiques — shadow uniquement

28 octobre2026. `bot.policy_research` compare24 candidats figés au maximum, sans
modifier `p4_experiment.POLICY`, le portefeuille, les fonctions actives ou les
limites3positions/20entrées/parjour/perte quotidienne10%. Tous les bras utilisent
le même `_run_arm`, `record_quote` et l'inventaire natif existants, sur des livres
SQLite isolés en mémoire. Aucun second moteur de comptabilité n'est introduit.

Les trois adaptateurs existants sont conservés : early_sniping,
confirmed_momentum, adaptive_hybrid. Chacun possède huit variantes : référence
conditionnelle du moteur, quatre paires TP7/14%×SL5/8%, score/liquidité plus
exigeants, confirmation30s avec durée900s/trailing3,5%, et budget0,10SOL. Les
interactions TP/SL sont évaluées ensemble; ce plan ne constitue pas une recherche
combinatoire exhaustive. Les autres pondérations et sorties partielles restent
celles des moteurs existants; leurs modifications ne sont pas réputées validées.

Ces valeurs sont des hypothèses de recherche. Les vetos existants sont conservés;
un seuil de score ne les supprime pas. Confirmation inférieure15s et abaissement
des planchers d'admission existants sont refusés par l'interface expérimentale.
Les tailles requièrent un contexte d'achat propre au montant exact. Un devis1SOL
ne devient jamais un devis0,10SOL par multiplication. Sans contexte adapté, le
candidat conserve son absence d'entrée. Les reliquats et coûts inconnus empêchent
le classement d'un résultat économique complet.

## Plan, sélection et holdout

`make_plan(registered_at_ms=..., development_end_ms=..., holdout_end_ms=...)`
retourne les candidats, bornes, fonction objectif et règles figés. Le plan complet
et le corpus possèdent une empreinte canonique. La vérification de l'ordre des
dates ne certifie pas leur publication préalable : cette preuve doit provenir
du commit/manifeste de collecte. Les entrées sont limitées à5000frames et24bras.

`evaluate_research(corpus, plan, registry=None)` réutilise la validation causale
P4 et exclut de validation les créateurs déjà vus en développement. Une position
de développement ne peut pas utiliser des observations après la coupure pour
se fermer. Les frames au-delà de la fin de holdout ne sont pas utilisées.

L'objectif de développement est l'espérance nette par position, pénalisée de
deux fois la perte moyenne du pire5% et du drawdown réalisé multiplié par le
capital initial10SOL. Dispersion, coûts, positions et sorties non qualifiées sont
conservés. Le drawdown est réalisé, pas une estimation mark-to-market des reliquats.
Une moyenne élevée n'efface pas une perte extrême. Aucun classement admissible
n'est produit si les positions ne sont pas totalement liquidées/coûts connus.

Un candidat par stratégie est figé sur le développement, avant le replay du
holdout. Le holdout ne sert pas à choisir parmi les24candidats : il compare ces
candidats préfigés et leurs références. Le registre interdit une seconde lecture
de la même fenêtre préenregistrée, même si un prix futur du corpus est modifié.
Le registre renvoyé doit être conservé pour que cette protection survive à un
nouveau processus; la CLI n'invente pas un stockage durable ou une authentification.
Changer seulement l'heure déclarée d'enregistrement ne déverrouille pas une
fenêtre déjà évaluée. L'horizon commun de replay reste30s : les valeurs de durée
900s/1800s ne sont donc pas départagées sur des positions déjà sorties à cet
horizon. Les fixtures actuelles ne démontrent pas l'intérêt de ces paramètres.

## Suivi, versions et interdiction de promotion

`choose_shadow` crée un pointeur expérimental versionné; `rollback_shadow` revient
à son prédécesseur. Aucun de ces chemins n'accède à une politique active.
`measure_drift` regroupe des résultats de positions uniques par politique,
créateur et période, en ignorant les résultats encore indisponibles. Les résultats
économiques inconnus restent comptés; aucune adaptation automatique n'en découle.

`promotion_allowed` reste **false** dans cette livraison. Les fixtures, groupes
créateurs déclarés et estimations ne prouvent ni indépendance ni rentabilité.
Les minima de validation, coûts/sorties complets, preuves P3 et autorisation de
promotion ne sont pas satisfaits par les données disponibles. Même un candidat
positif sur fixture ne devient pas une stratégie rentable ni une politique active.

Entrée CLI : JSON `{corpus, plan, registry?}`, sortie JSON neuve :

```sh
python -B -m bot.policy_research --input work/research-input.json --output work/research-report-new.json
```

La CLI interdit réseau et lecture `.env` avant les imports du moteur. Les tests
vérifient inventaire exact, absence de scaling, cohérence du portefeuille,
quarantaine créateur, purge temporelle, invariance des candidats au futur,
lecture unique du holdout, risque extrême, drift et rollback shadow.
Un scénario ciblé conserve deux vrais contextes synthétiques distincts :1SOL
acquiert1000unités,0,10SOL en acquiert100. Les sorties portent sur le lot propre
à chaque entrée, avec15000lamports de frais additionnels identiques, et donnent
respectivement0,199985/0,019985SOL nets synthétiques. Ce test démontre le passage
du budget et l'effet relatif des frais fixes; il ne mesure pas une rentabilité.

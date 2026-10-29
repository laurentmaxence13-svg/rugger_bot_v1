# P3-010 — sauvegarde vérifiée hors réseau

Capture du28octobre2026; reprise29octobre,Europe/Paris. Aucun010relancé.

47événements;100lignes de sélection,6pools,3actifs,2avec capacité de sortie modélisée0,10SOL.
4requêtes,2342ms capture,2569,909ms processus;0devis externe,0cycle économique,0décisionA/B admissible.
Plan publié/relu430ac7c avant acquisition,code5bec177. Rapport original et6analyses reproduits.

**Limite de conservation observée :** les100lignes de champs de sélection et leurs digests sont présentes;
le JSON complet de découverte a été refusé comme unsafe_or_oversized lors du contrôle. Il est absent,
non récupéré et jamais reconstruit. Les octets des comptes RPC sont conservés et rejoués.

| Mint | Pool | Slot | Activité | Capacité modélisée0,10SOL | Identité | Supply |
|---|---|---|---|---|---|---|
|3EWcNCziEQjjsNNqgj4KzF6idG5UBjuWG3GQP2Anbonk|2KnqS9oZPo6CheEQv5zjkSPkeR5Xdu5uYM2nDa8UiCiC|462625157|unknown|None|platform_pda UNKNOWN; autres checks PASS|False|
|7t3y1f2NukpPdaSzYnU3rdLVBCyQVdhf9rJYMEwRJ9pw|DCJX5RZb4KvDQkyhXAgvEZwAxbx8FboeuwFmcksoXyYh|462625157|active|False|platform_pda UNKNOWN; autres checks PASS|True|
|DkvJvgLawc4TToQtKP8PJvNwYo9s65MQkX4y2guDdCiN|87A7ujoS6Yv9q2GZc25dJGALVYAN38VYnzBbAYMzYWHA|462625157|active|True|platform_pda UNKNOWN; autres checks PASS|True|
|AFVbiHTLLH4o8qjaVpWys6D78SL573cPaeWe21jytray|4SPadRxD88iE9imk4hwrVDtqSLdVa5yYBJysjr4yNsY7|462625157|no_observed_circulation|False|platform_pda UNKNOWN; autres checks PASS|True|
|4NsR2QMxp59geg74NmggW7BBGU9epHZJMzfNGXKxYJnG|BEPf4ESFjWigi9Uq6tSShAXHx2oi5NAdSCdxHkQm8JhL|462625157|active|True|platform_pda UNKNOWN; autres checks PASS|True|
|25mbv6mFYBq8S6kXVNefEiqomcBBuGSsRbJck5gnaxmk|DDqBcHkgj8e8pSJgXHgKfWJMvzUKuR1RfUCYtQ6C2vUf|462625157|unknown|None|platform_pda UNKNOWN; autres checks PASS|False|

Contrôles individuels complets : SIX_POOLS.json. Creator de chaque compte égal au champ index,
sans prouver indépendance économique des acheteurs ou des créateurs.

Reproduction sans SQLite/réseau :
`RUGGER_NO_DOTENV=1 python -B validation/p3_active_cohort_010/reproduce.py`

Archive `evidence/p3/active_cohort_010`, ancre `1d2afec81a12cc6abfac5f5d1afaa5cca08846f70585ab8a54d83f8a69caf66d`.
Source validée1970tests,1skip,242subtests; aucune répétition de suite nécessaire pour export de données.
P0 préserve les preuves, sans valider P3 économique. L’issue23 reste ouverte jusqu’à relecture distante.

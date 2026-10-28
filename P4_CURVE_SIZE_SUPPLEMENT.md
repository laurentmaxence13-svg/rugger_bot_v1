# P4 — tailles, coûts de courbe et qualité des sorties

28 octobre 2026. Supplément de recherche `CURVE_COST_POLICY`, hash séparé du
protocole historique. Aucun changement du budget actif de1SOL, des variantes,
scores, veto, TP/SL ou protections existants. Aucune collecte réseau.

`assess_curve_costs(frame, history=(), decision_at_ms=...)` compare0,05/0,10/0,25/
1SOL sur un bank disponible à la décision. L'outil appelle le modèle P3 entier
pour chaque taille: il ne multiplie aucune quantité ou cotation par un ratio.
Le modèle ajoute notre achat au bank contrefactuel avant sa revente entière.
L'estimation de vente sur le bank réellement observé, qui ne contient pas cet
achat, reste un résultat séparé. Son refus n'est pas une preuve d'invendabilité
après achat. Les montants, quantités et arrondis restent des entiers exacts.

Le contrat optionnel `frame.bank_state` conserve mint/pool/slot, observation et
disponibilité, provenance, pool décodé, trois taux de frais, vaults, type de courbe
et partage des frais. Identité, supply et création qualifiées peuvent rester
inconnues. Le bank doit appartenir au mint/pool/slot de la frame et être disponible
depuis au plus5s à la décision. Cette fraîcheur de disponibilité **ne certifie
pas l'heure source d'un fournisseur de devis**. Un bank futur est refusé; un
bank ancien, sans provenance ou incompatible reste explicitement inutilisable.

Les frais additionnels propres restent inconnus dans le résultat de base. Les
totaux0/15000/1000000lamports sont trois hypothèses explicites, jamais des frais
observés, même pour le scénario zéro. Chaque résultat conserve son besoin de
produits additionnels pour atteindre le seuil de rentabilité. Les scénarios
d'achats tiers0/0,1/0,5/1SOL modifient ensuite les réserves contrefactuelles avec
leurs propres frais et limites. Ils ne représentent ni une prévision ni la
reconstruction d'un bank futur. Aucun scénario n'est retenu comme gagnant.

Des contextes de devis peuvent être fournis par taille dans `size_contexts`.
Le corps d'achat doit se rejouer, porter sur le budget exact et conserver son
lot projeté. Les ventes disponibles à la décision sont liées à cette quantité,
leurs corps rejoués et les répétitions dédupliquées. La couverture maximale
reste une fraction de devis, pas une fraction liquidée. Aucun devis1SOL n'est
substitué aux trois autres tailles. Les dates/slots fournisseur inconnus restent
inconnus; aucun devis indicatif n'est crédité au portefeuille par cette analyse.

`evaluate_experiment` ajoute le supplément uniquement aux corpus portant ces
banks. Les trois variantes réutilisent leur même historique causal pour décider;
une absence de features créateur/wallet/momentum donne une intention UNKNOWN,
pas un signal fabriqué. Les traces des bras portent le hash de leur analyse de
coûts disponible à cet instant. Les sorties comparatives en ledger, sa taille
historique et ses jambes restent inchangées. Le supplément peut donc exposer
une friction excessive sans transformer une projection locale en fill PAPER
qualifié ou changer la stratégie active.

Validation ciblée sur copie jetable sans réseau/.env/base utilisateur: tailles
recalculées, effet de frais fixes, limites de fundraising, réserve tierce,
bank vide versus bank après achat, chronologie, invariance du préfixe,
absence de features et de frais propres, intégrité des corps de devis,
absence de scaling/double comptage et ledger inchangé. Les expériences sur les
banks008 sont des modèles conditionnels issus de données réelles conservées;
les observations indépendantes et les cycles économiques strictement qualifiés
ne sont pas augmentés par ces lignes de modèle.

La version2 ajoute les ventes tierces de50%/100% des tokens initialement en
circulation. Ces vendeurs ne peuvent pas utiliser notre lot hypothétique. Sans
circulation initiale, le scénario est non applicable, pas une vente inventée.
Les sensibilités haussières et baissières restent distinctes des banks observés.
Le seuil de demande tierce est recherché avec les arrondis exacts et les limites
de migration, jusqu'à10SOL hypothétiques; un lamport de moins doit échouer au
seuil retenu. Ce seuil n'est ni une prévision de flux ni une règle active.

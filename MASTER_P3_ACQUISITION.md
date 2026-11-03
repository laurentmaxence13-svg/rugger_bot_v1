# P3 — acquisition prospective exploitable par la comparaison Master

28 octobre 2026. Cette livraison prépare la conservation et l'adaptation des
observations. **Aucune nouvelle collecte de marché n'a été exécutée**, aucun
contrôle006/007/008 relancé, aucun coût propre manquant complété artificiellement.

Les fonctions nouvelles étendent `bot/p3/cohort.py`. La sélection, les critères
et les protections existants restent inchangés; aucun second moteur financier
n'est introduit. Les frames alimentent le comparateur, le ledger PAPER restant
l'unique autorité de règlement.

## Protocole figé et état de préparation

`make_acquisition_plan(registered_at_ms=..., source_revision=...)` conserve les
critères et leur empreinte, les sources documentées, **20 requêtes et60secondes
globales** toutes sources confondues, le préfixe fixe de six pools et au plus deux
candidats. Le plan ajoute des bornes de travail local :128checkpoints de features,
20observations de devis et5000événements maximum pour l'adaptateur hors réseau.
`validate_acquisition_plan` refuse un élargissement des budgets ou une observation
antérieure à l'heure déclarée d'enregistrement. Le statut demeure
`PREPARED_NOT_EXECUTED`. Une déclaration horodatée ne prouve pas sa publication :
le plan et la version source doivent être publiés avant toute collecte future.

Le partage réel des compteurs et de la deadline continue de relever de
`CampaignSession` et `NativeInventoryQuoteProvider`. L'adaptateur ne crée ni
quota, ni retry, ni source alternative implicite. Il n'autorise aucune campagne.
La disponibilité ou la gratuité actuelle des fournisseurs n'a pas été sondée.

## Producteur de features retenues

`retain_comparison_inputs(store, mint=..., pool=..., creator=...,
detected_at_ms=..., features=..., source_observation_ids=[...],
received_at_ms=..., snapshot_analysis_observation_id=..., token_decimals=...)`
écrit un checkpoint `master_frame_inputs_v1` dans le `CaptureStore` dédié existant.
Il accepte les features du scanner/cache déjà disponibles; il n'effectue aucun
appel de source. Les références doivent déjà être commitées, disponibles à cette
heure et de provenance compatible. Identité, schéma et fraîcheur des features
sont vérifiés avant append. Le checkpoint doit précéder la décision et ses
résultats futurs. Les ordres d'IDs protègent aussi les événements à même timestamp.

Ce producteur est testé et prêt à raccorder à un futur protocole d'acquisition.
**Aucun nouveau collecteur réseau ni branchement automatique de production n'est
activé dans cette livraison.** Les bases et le portefeuille utilisateur ne sont
ni ouverts, ni migrés, ni exportés par ces fonctions.

## Adaptation aux frames de comparaison

`build_comparison_corpus(selection, events, as_of_ms=...,
integrity_verified=True, expected_tail=...)` reçoit la sélection complète et un
export intégral du journal. Le résultat contient :

- `corpus = {data_kind, frames}` : `synthetic` ou `market_observation`, au singulier;
- `denominator` : toutes les lignes de l'univers, refus et exclusions conservés;
- `candidates` : frames produites ou état `UNKNOWN`, avec raisons explicites;
- les références des features, snapshots, transactions de création, devis et coûts;
- les refus de devis et le nombre d'observations futures exclues.

L'adaptateur reconstruit les enregistrements et réutilise effectivement
`CaptureStore._verify_records` pour vérifier la chaîne par rapport à l'ancre
fournie. L'ancre reste un engagement externe de l'appelant : une hash-chain ne
constitue ni signature, ni authentification du fournisseur. Les déclarations de
provenance ne sont pas une preuve indépendante de leur vérité.

Une frame n'utilise que des features retenues et leurs sources antérieures. Sans
features exploitables ou créateur/détection connus, le candidat reste au
dénominateur `UNKNOWN`; aucune feature n'est fabriquée à partir des futurs prix.
Les acheteurs indépendants demeurent inconnus : un nombre de swaps n'est jamais
converti en nombre de wallets indépendants.

## Marché observé, modèle et devis séparés

La bank conserve les réserves observées originales. L'achat hypothétique du bot
ne modifie jamais ces réserves. Les analyses retenues sont converties dans le
contrat de modèle existant; les coûts de courbe et les effets conditionnels
continuent de relever des fonctions P3/P4 existantes.

Lorsque les bytes RPC d'origine et leurs adresses ordonnées sont retenues,
l'adaptateur rejoue `analyze_snapshot` avec le profil publié et contrôle leur
cohérence avec les faits. Les certifications sont celles du replay. Sans bytes,
les états d'identité et de supply restent `None`, avec la portée explicite
`upstream_analysis_claim_only`. Une analyse déclarée certifiée ne remplace donc
pas les bytes absentes. Une contradiction entre analyse et bytes écarte la bank.

La création exige une observation `launch` reliée à la transaction brute
antérieure. Le parseur LaunchLab existant doit retrouver exactement mint, pool,
créateur et payer, avec mêmes signature et slot, transaction réussie. Un booléen
de création isolé ne suffit pas. Une preuve obtenue après une décision ne réécrit
pas sa bank passée.

Les devis indicatifs gardent leur montant exact, leur body, leurs timestamps et
leur lien au buy d'origine; jamais de scaling. Les refus de vente sont conservés.
Un slot RPC ou un blockTime estimé ne complète **jamais** les champs temporels
absents du fournisseur de devis. Une sortie indicative ne devient pas un fill.

## Coûts propres et inconnus

Seul un checkpoint `own_position_costs` déjà disponible, lié au buy précis,
`proxy=False` et `applicable_to_projected_position=True`, peut fournir des frais.
Il doit porter un `SolFeeBreakdown` valide et une provenance cohérente. Un coût
estimé reste estimé; un coût synthétique ne devient pas observé. Le checkpoint
est une déclaration d'applicabilité, pas une authentification d'un coût exécuté.
Les frais de tiers/références et les coûts arrivés ultérieurement sont ignorés
pour la décision antérieure. Les champs inconnus restent `None`.

Les méthodes légitimes et leurs limites restent détaillées dans
`P3_SOURCE_ACCESS_METHOD.md` : RPC groupé pour la bank, blockTime pour une heure
de chaîne estimée distincte, coûts de tiers comme proxies, rent distinct du frais
consommé. Aucune construction, simulation ou signature de transaction n'est
ajoutée pour combler un manque. Un autre fournisseur sans clock contextuelle ne
résout pas cette preuve par simple changement de nom.

## Validation et limites

55tests ciblés réussis,0,88s, warnings en erreur, sur copie jetable sans réseau,
`.env`, historique Git ou base utilisateur :

```sh
python -B tools/offline_check.py -q tests/test_p3_master_acquisition.py tests/test_p3_cohort.py tests/test_p3_prospective_report.py tests/test_p3_prospective_campaign.py -p no:cacheprovider -W error
```

Cas reproduits : univers complet, buy/sell de quantités propres, refus et coûts
inconnus, futures features et coûts sans influence passée, ordre d'IDs à même
milliseconde, corruption/ancre erronée, faux créateur, transaction de création
contradictoire, replay des bytes RPC et identité amont trompeuse. Les tests sont
entièrement construits, même lorsqu'ils exercent une étiquette `live`.

**P3 reste ouvert :0nouvelle observation de marché,0cycle économique strictement
qualifié, aucune rentabilité prouvée.** La prochaine acquisition doit encore
apporter les features sourcées, clocks de devis, coûts applicables et sorties
liées aux quantités, sous le protocole préenregistré et ses budgets. Le corpus
indépendant et les groupes de créateurs ne sont pas créés par cet adaptateur.

## Santé retenue et frontière comparative

`retain_comparison_inputs(..., health_observation_id=...)` accepte une référence
vers un checkpoint `operational_health_v1` déjà commité, payload `{health: ...}`,
issu de la supervision locale. Schéma, disponibilité, fraîcheur de 5 s et états
des services sont contrôlés. Un état ready contradictoire ou futur est refusé.
L'absence de checkpoint ne devient pas une permission. L'adaptateur transmet ce
contexte dans frame.health comme attestation locale, sans authentification du
fournisseur externe.

`master-compare` accepte une enveloppe `acquisition` complète : univers, refus,
inconnus et ancre de capture restent dans le rapport. Aucun hook réseau activé.

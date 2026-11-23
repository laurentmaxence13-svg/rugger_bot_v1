# w1decomp 0.2 — R-2 : décomposition DESCRIPTIVE des pertes W1 (EXPLORATOIRE)

RUGGER 01, 23/11/2026. Directive stratégique finale du propriétaire, chantier R-2.

**v0.2** = 0.1 (e4af0d1) avec les corrections de l'audit R02 3e714683 :
- K-1 : tests qui tuent les 3 mutants survivants de R02 (D3c inversé, « sous l'entrée » non strict, réussite non
  stricte). Les 3 mutants sont ajoutés au runner.
- K-2 : sha COMPLET du ledger C1 ancré dans la commande.
- K-3 : le .md publie D3 (n, IC, interprétable), avec en tête l'avertissement de multiplicité. D2 et D3c portent
  l'étiquette « postérieur à la décision : jamais une variable de décision ».

Décisions de R02 : D2 et D3a sont ADMIS. E = 5 est compté hors N. Toute hypothèse inspirée de D2 ou de D3 = N + 1,
testée sur des données nouvelles.

- C'est un script seul, sur pièces synthétiques. RIEN n'a été exécuté sur W1.
- R02 l'audite. R03 l'exécute ensuite une seule fois, sous A2 (5aff3383, point 1).
- Aucune règle ni aucun paramètre n'est tiré de W1.

## Entrées, toutes vérifiées par sha256 avant la lecture d'une seule ligne

- `ledger.json`, le ledger W1 ancré : verdict PASS, aucun écart, `w1_report` nul.
- Le bundle L1, avec le sha que le ledger a enregistré.
- L'export des pools W1, avec le sha ancré de son MANIFEST. Seuls les pools qui portent une position de la
  population sont rejoués en timeline, par le code gelé : `collector.summarize` puis `hrr.usable_timeline`.

## Population

C'est la règle de w1loss 0.3 (audité, importé et non modifié) :
- essai L1 ;
- bras `master` et `placebo_random` ;
- pools créés dans la plage d'évaluation ;
- cycles clôturés et vérifiés.

## Liste FERMÉE de 5 ventilations

E = 5, compté à part de N, comme w1loss.

**D1 — Coûts en % de la mise**, à partir de l'identité exacte du ledger :
- brut ;
- impact (aller-retour de nos ordres) ;
- frais de courbe, tx, échecs ;
- loyer : 2 039 280 lamports, constante de `statelab.exits`.

Le document publie aussi :
- la part de chaque poste dans le coût total ;
- le net [SL] (moteur gelé sans loyer) et le net [LP] (loyer perdu, ajout additif) ;
- les IC.

**D2 — Trajet du prix après l'entrée.**
- Référence : le spot après l'événement d'atterrissage de notre achat (événements réels seulement, notre ordre
  exclu).
- Écarts relatifs aux décalages 0, 1, 2, 4, 8, 16, 32, 64, 128, 256 et 512 slots, tant que la position est
  détenue : n, moyenne, médiane, part sous l'entrée.
- Décalage du maximum avant la vente.
- Premier passage strict sous l'entrée.

**D3 — Types de pools, en classes fixées d'avance :**
- D3a : nombre d'événements réels avant l'entrée ;
- D3b : heure UTC de création, par blocs de 4 h ;
- D3c : pool arrivé ou non à la frontière de migration.

**Pare-feu HW1.**
- Aucune variable d'état HW1 n'est utilisée : ni progression, ni quote levée, ni réserve, ni signature du
  créateur, ni classe d'âge.
- D2 mesure un trajet APRÈS l'entrée d'une position déjà clôturée : c'est un résultat, jamais une variable de
  décision. **À valider par R02.**

**Sortie** : `DECOMPOSITION_W1.json` et `.md`. Aucun pool, créateur ni signature n'y figure (testé). Un répertoire
existant est refusé.

## Preuves

- 10 tests : réponses connues pour D1 à D3, ancres, liste blanche de sortie, pare-feu, publication de D3 et des
  avertissements. Le chargeur est testé sur le pack de fixtures du dépôt.
- **27/27 mutants détectés**, avec la garde de base : les 23 de R01, les 3 de R02 et 1 sur l'avertissement.

## Commande pour R03, une seule fois

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<statelab_pkg>:<v3lab_pkg>:<v4sim_pkg>:<w1aux_v78>:<w1_loss_analysis>:<w1decomp_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m w1decomp.decomp --ledger <ledger.json> --ledger-sha256 4da5fbfb2339ee0bbaf46df66d0aed5d11ea0aa6002f11d00a97e0d1b83c3528 --bundle <L1.json.gz> --pools <export W1> --manifest-sha256 ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e --evaluation-min 467678545 --evaluation-max 469291345 --out <NOUVEAU répertoire>`

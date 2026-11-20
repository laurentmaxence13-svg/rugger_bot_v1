# feeage 0.1 — taux de frais LaunchLab selon l'âge du pool, comptage de POPULATION (préalable de C-D)

Conditions 3 et 4 de RUGGER 02 (3cd2ffa2). **Écrit, non exécuté.** R02 audite l'outil, puis R03 l'exécute :
- d'abord sur **P0 développement**, données sur lesquelles R02 a demandé la réponse à la question 3 ;
- puis sur **W1**, seulement si R02 l'admet pour le comptage de la condition 4, qui est un fait de population.

## Questions traitées

- **Q3** : le taux de frais d'un pool baisse-t-il avec son âge ? L'outil compte :
  - les pools dont le palier ne change jamais ;
  - ceux dont il change, et parmi eux ceux qui ne remontent jamais ;
  - les paires « premier palier → dernier palier » ;
  - les paliers par classe d'âge.
- **Q4** : combien de pools atteignent un âge ≥ 450 slots ? Parmi eux, combien ont le palier de 2 500 ppm à leur
  PREMIER événement tardif ? Le résultat est aussi ramené par jour, à 215 ms par slot.

## Garanties

- **Champs lus** : seulement le slot, le sens et les montants de chaque événement d'échange, ses quatre champs de
  frais, et le slot de création (via `creation_facts`, gelé).
- **Taux** : `implied_fee_rate_ppm` gelé, gardé seulement si le frais vaut au moins 1 000 lamports, puis arrondi au
  palier de 500 ppm le plus proche.
- **Rien d'autre** : aucune valeur, aucun P&L, aucune réserve, aucune progression, aucun signataire. Testé : le code
  ne nomme aucun de ces champs.
- **Sortie** : `FEE_AGE_POPULATION.json`, des comptes seulement. Hors N.

## Commande (R03)

    PYTHONPATH=<checkout aff97638>:<fee_age_population> RUGGER_NO_DOTENV=1 python -B -m feeage.population \
        --pools <dossier des pools exportés> --manifest-sha256 <sha ancré du MANIFEST.json> --label P0 --out <OUT>

## Preuves

- 6 tests sous CPython 3.12.3 avec `-W error`, dont une exécution sur le pack gelé : 3 pools, aucun changement de
  palier.
- Défauts volontaires : 9 détectés sur 9 (`MUTATIONS_feeage_v0_1.json`).

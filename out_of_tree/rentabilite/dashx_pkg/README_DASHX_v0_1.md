# dashx 0.1 — R-3 : tableau de bord étendu sur les sorties DÉJÀ ancrées (EXPLORATOIRE)

RUGGER 01, 23/11/2026. Directive stratégique finale du propriétaire, chantier R-3.
- C'est un script seul : rien n'a été exécuté sur une sortie réelle.
- R02 l'audite. R03 l'exécute ensuite une seule fois.
- Il ne fait aucun rejeu, aucune nouvelle évaluation et ne lit aucune donnée de pool.

## Entrées

Chacune est vérifiée par son sha256. Une entrée absente laisse ses lignes en « NON MESURÉ ».

| Entrée | Ancrage | Lignes |
|---|---|---|
| ledger W1, plus le bundle L1 (sha enregistré par le ledger) | ledger ancré | MASTER W1, placebo W1 : **la seule source par position** |
| `VENTILATION_W1.json` (w1loss) | da1e5758 | C-A : MASTER au palier 12 500 ppm |
| `LATELAB.json`, découverte | 7351512d | L1, L3, placebo de la moitié 1 |
| `LATELAB.json`, crible | 20aba3f5 | crible L1, placebo de la moitié 2 |
| `LATESEL.json` | f3c6c9e3 | T1, T3′ |
| `CDGATE.json` | 2b173f10 | C-D, placebo du palier bas |

C-B, C-C, C-E et CPMM R-CP1 sont listés avec « aucune position » et sans aucun chiffre.

## Colonnes, fixées d'avance

- Positions et pools : pools distincts, ou grappes de créateurs pour les sorties agrégées (étiqueté).
- Brut, net avec son régime ([SL] ou [LP]), taux de réussite.
- Gain moyen gagnant et perte moyenne perdante.
- Profit factor : somme des P&L positifs / |somme des P&L négatifs|.
- Espérance : net moyen par position.
- Drawdown maximal du net cumulé, positions dans l'ordre de leur vente, en unités de mise.
- Frais de courbe et tx moyens, latence (lue dans le document), échecs (frais modélisés ; 0 = non mesuré).
- IC à 95 %, comparaison au placebo, robustesse :
  - les deux moitiés chronologiques ;
  - la moyenne sans les 5 meilleures ;
  - la part des 5 meilleures dans les gains ;
  - le net à 10 slots s'il existe.
- Statut, verdict.

**Ce qui reste NON MESURÉ, et pourquoi.** Les sorties latelab, latesel, cdgate et w1loss sont des AGRÉGATS : elles
ne contiennent pas les positions individuelles. Il n'y a donc, pour ces lignes :
- ni gain moyen gagnant, ni perte moyenne perdante ;
- ni profit factor ;
- ni drawdown.
Ces valeurs ne sont jamais recalculées ni estimées. Les recalculer demanderait un nouveau rejeu, c'est-à-dire une
nouvelle exécution sur W1 : c'est hors du mandat.

**Verdict.** Vocabulaire fermé, R-0.1 et ordre du § 2.2 (2792655a) :
- placebo : aucun verdict ;
- n < 30 ou ligne non interprétable : INCONCLUSIF ;
- sinon, borne haute < 0 : NÉGATIF ;
- sinon : INCONCLUSIF.
Tout autre mot lève une erreur (testé).

**Sortie** : `TABLEAU_DE_BORD.json` et `.md`. Aucun pool ni créateur n'y figure (testé). Un répertoire existant est
refusé.

## Preuves

- 6 tests, sur des documents synthétiques à réponses connues.
- **22/22 mutants détectés**, avec la garde de base.

## Commande pour R03, une seule fois

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<w1_loss_analysis>:<dashx_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m dashx.board --out <NOUVEAU répertoire> --ledger <ledger.json> <sha> --bundle <L1.json.gz> --evaluation-min 467678545 --evaluation-max 469291345 --ventilation <VENTILATION_W1.json> <da1e5758…> --latelab-discovery <LATELAB.json> <7351512d…> --latelab-screen <LATELAB.json> <20aba3f5…> --latesel <LATESEL.json> <f3c6c9e3…> --cdgate <CDGATE.json> <2b173f10…>`

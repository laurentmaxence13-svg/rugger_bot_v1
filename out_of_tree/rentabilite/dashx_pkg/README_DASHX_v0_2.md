# dashx 0.2 — R-3 : tableau de bord étendu sur les sorties DÉJÀ ancrées (EXPLORATOIRE)

RUGGER 01, 23/11/2026.
- Base : dashx 0.1 (d673e9d). Corrections K-1 à K-4 de l'audit R02 5c5d666c.
- Définitions gelées appliquées : `DEFINITIONS_INDICATEURS_GELEES_R02_v1_0.md` (b31a3c47).
- C'est un script seul. R03 l'exécute une fois, APRÈS la revérification de R02.

**En tête de la sortie** : « EXPLORATOIRE ; données W1 ; régimes [SL]/[LP] non comparables entre lignes ; NON MESURÉ =
non calculable sans nouveau rejeu ».

## Ce qui change par rapport à la 0.1

- **K-1.** Deux tests tuent les survivants de R02 :
  - le drawdown est trié par VENTE, et un ordre par entrée donnerait un autre chiffre ;
  - r = 0 est une perte, jamais un gain.
- **K-2.** Profit factor = Σ r⁺ / |Σ r⁻| en NET (NON MESURÉ s'il n'y a aucune perte). La version en lamports est
  publiée à part, sous le nom `profit_factor_lamports`.
- **K-3.** Les sha COMPLETS attendus sont dans le code (`EXPECTED_SHA256`). Toute autre valeur bloque l'exécution
  (testé) :

| Entrée | sha256 attendu |
|---|---|
| ledger C1 | 4da5fbfb2339ee0bbaf46df66d0aed5d11ea0aa6002f11d00a97e0d1b83c3528 |
| ventilation w1loss | da1e575890ae19fd512e17f43283c5f32d5887f71e5d8c9e8e915bce2488873e |
| latelab, découverte | 7351512d84916e64923b5292e1e51d1563d0a35e7865fa0f5a513ca6d217ec8f |
| latelab, crible | 20aba3f5712ee442cfbbcd67d90398e7ae0e010683d0042d11c07cf61d8bd0f0 |
| latesel | f3c6c9e38336029388d88713388984e2c0a52fbec27b9f3a6ae3a575ee7fbf64 |
| cdgate | 2b173f104b6ca83cc1867f8abaa8dd3cd31a13d213b85772470edd1b75153cfa |

- **K-4.** L'avertissement est la 3e ligne du .md (testé).

**Deux IC pour le MASTER.**
- Celui de w1loss : 2 000 tirages, graine 20261120.
- Celui de la lecture ancrée ea152a32 / 3aa36aa3 : [−6,69 % ; −1,95 %].
- Le document écrit « concordants » (à 5e-5 près, l'arrondi publié) ou « DISCORDANTS ». Il ne remplace jamais l'un
  par l'autre en silence.

**Alignements sur b31a3c47.**
- **Positions** : comptées, plus les lignes ouvertes non valorisées publiées à part ; refus de garde NON MESURÉ sur
  W1.
- **Pools** : nombre distinct, part du 1er et des 5 premiers.
- **Brut** : impact propre inclus, soit market_move − slippage. Le mouvement de marché hors impact est publié à côté.
- **Réussite** : r > 0. Gain moyen : r > 0. Perte moyenne : r ≤ 0.
- **Espérance** : identité vérifiée à 1e-9.
- **Drawdown** : en mises ET en SOL, par ordre de sortie, puis entrée, puis pool.
- **Frais** : en % et en lamports, ventilés. Le loyer n'est pas dans r_i en [SL] ; le WSOL est NON MESURÉ.
- **Robustesse** : liste FERMÉE des 7 rubriques, toutes publiées ; ce qui manque est NON MESURÉ.

## Preuves

- 8 tests.
- **27/27 mutants détectés**, avec la garde de base, dont les 2 de R02.
- Un mutant équivalent est retiré et déclaré : l'identité de l'espérance tient par construction.

## Commande pour R03, une seule fois

Depuis l'arbre gelé, SANS `-I` :

`env -i PYTHONPATH=<wt_w1>:<w1_loss_analysis>:<dashx_pkg> PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 python3.12 -B -m dashx.board --out <NOUVEAU répertoire> --ledger <ledger.json> 4da5fbfb2339ee0bbaf46df66d0aed5d11ea0aa6002f11d00a97e0d1b83c3528 --bundle <L1.json.gz> --evaluation-min 467678545 --evaluation-max 469291345 --ventilation <VENTILATION_W1.json> da1e575890ae19fd512e17f43283c5f32d5887f71e5d8c9e8e915bce2488873e --latelab-discovery <LATELAB.json> 7351512d84916e64923b5292e1e51d1563d0a35e7865fa0f5a513ca6d217ec8f --latelab-screen <LATELAB.json> 20aba3f5712ee442cfbbcd67d90398e7ae0e010683d0042d11c07cf61d8bd0f0 --latesel <LATESEL.json> f3c6c9e38336029388d88713388984e2c0a52fbec27b9f3a6ae3a575ee7fbf64 --cdgate <CDGATE.json> 2b173f104b6ca83cc1867f8abaa8dd3cd31a13d213b85772470edd1b75153cfa`

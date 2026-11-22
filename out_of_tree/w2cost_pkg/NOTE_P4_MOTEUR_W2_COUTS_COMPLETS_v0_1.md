# P4 — Proposition d'un moteur W2 « coûts complets » (v0.1) — PROPOSITION, NON ADOPTÉE

RUGGER 01, 22/11/2026. Tâche P4 (R04, 21:35Z). Si on l'adoptait, des hypothèses gelées du Dossier B v1.9
changeraient. **La décision appartient au propriétaire.** Rien n'est adopté et rien n'est exécuté : fixtures
seulement, aucune donnée W1 ni W2.

## 1. Ce qui est proposé : un paramétrage unique (`w2cost.proposal.PARAMETERS`, sha c5e99089…)

**Assemblage** (paquets déjà au PASS de R02) :
- papercost 0.1 (2937aa3) ;
- rtgate 0.2 (22c595b), avec COMPLETE exigé, sinon le pool est exclu ;
- la garde de landslip 0.1 (8e432a5) ;
- mevsens 0.1 (a94a660), en sensibilité.

**Primaire** :
- garde d'achat de 20 000 ppm ; H-1 sur les deux jambes ; 0 échec ;
- loyer perdu ; WSOL à 5 000 par transaction ;
- positions ouvertes marquées et comptées ; non valorisables comptées à 0 ;
- N-6 : « none ».

**Publié à part** :
- compte fermé ;
- garde de 50 000 ppm ; garde de vente de 5 % ;
- 1 échec par transaction ; WSOL à 105 000 ;
- les 6 scénarios N-6 ;
- **le net gelé, toujours, à côté** (condition de R02).

Ce sha est celui qu'un gel ancrerait, avant toute donnée W2.

## 2. Différences avec le moteur du Dossier B v1.9

| Point | Dossier B v1.9 (gelé) | Proposition |
|---|---|---|
| Moteur d'A0 (MASTER) et A1 (placebo) | Chaîne dayj → `hrr.run_replay` → `replay` gelé (W1) | Même chaîne ; seul `hrr.replay` est remplacé par `papercost.CostedTrade` (identité prouvée en mode neutre) |
| Moteur de C-B | Sondes `statelab.study.probe` sur **v4sim** (M-P), horizons fixes, rangées exportées | **INCHANGÉ par papercost**, qui ne passe pas par `hrr.replay`. Pour la garde et H-1 sur C-B, il faudrait une couche NOUVELLE relisant le même export : code nouveau, audit nouveau, et changement des rangées de C-B |
| Moteur de C-E | cdgate (`run_rule` gelé), mode compte fermé | Inchangé par papercost (même raison) |
| Atterrissage | Certain à +4 slots | +4 slots, pire cas dans le slot (H-1) ; échecs en sensibilité (+4 slots par renvoi, facturés) |
| Glissement (N-5) | Aucune garde | Garde de 2 % ; sous le seuil, aucune entrée et 105 000 facturés |
| Loyer (N-1/N-2) | A0/A1 : supposé rendu gratuitement (`replay.py` l. 24) ; C-B : perdu | Perdu en primaire pour tous ; compte fermé publié à part |
| WSOL (N-7) | Non modélisé | Forfait de 5 000 par transaction |
| Positions ouvertes (N-8) | Exclues du P&L (`open_at_window_end`, marque à part) | Marquées à la valeur exacte et COMPTÉES |
| Non valorisables | Hors P&L (A0/A1) ; −coût − loyer (C-B) | Comptées à valeur nulle partout |
| Complétude du flux | Timeline vérifiée par la chaîne des réserves en lot | Même chose, plus rtgate : un pool INCOMPLET est exclu |
| MEV (N-6) | Non modélisé | Sensibilité seulement (mevsens), jamais en primaire |

## 3. Impact sur n_min et la puissance (formule du Dossier B § 6.1, fixtures seulement)

- **Formule.** n = ((z₁₋α + z₀,₈₀) · σ / δ)², avec σ = 13,7 %, δ = +2 %, α = 0,05/3. Elle donne **414**, retrouvé
  par `n_min()`.
- **Garde du plancher.** Sous coûts complets, l'effet détectable devient δ − surcoût par cycle. Le résultat n'est
  **jamais inférieur à 414** : un plancher protégé, codé et testé.
- **Mesure sur fixtures** (`fixture_impact`). Les 3 pools publics, chaque événement servant d'entrée forcée, sortie
  après 5 événements :
  - 110 entrées au gelé, dont 16 refusées par la garde (part d'entrée 0,855) ;
  - surcoût moyen face au moteur d'A0 : +1,68 % de la mise ;
  - moteur seul (garde et H-1, à comptabilité égale) : −0,36 %. C'est un effet de SÉLECTION de la garde, qui écarte
    des entrées perdantes en début de courbe sur ces 3 pools. Il n'est **pas** utilisé pour réduire n_min.
  - Ces chiffres décrivent 3 pools publics. **Ce ne sont pas des estimations pour W1 ou W2.**

| Cas (σ gelé de 13,7 %) | Surcoût retenu | Effet restant | Cycles | Décisions à une part d'entrée de 0,855 |
|---|---|---|---|---|
| Gelé (Dossier B) | 0 | 2,00 % | **414** | 414 |
| C-B (déjà en loyer perdu) : + WSOL seul | 0,01 % | 1,99 % | 418 | 490 |
| A0 en compte fermé : nettoyage + WSOL | 0,115 % | 1,885 % | 466 | — |
| A0 en loyer perdu, δ défini sur le net GELÉ | 2,05 % (loyer + WSOL) | < 0 | **jamais détectable** | — |
| A0, surcoût moyen des fixtures | 1,68 % | 0,32 % | 16 681 | 19 521 |

**Lecture.** Si δ = +2 % reste défini sur le net gelé d'A0 (loyer rendu gratuitement), le loyer perdu suffit à
rendre l'effet indétectable. Adopter le moteur coûts complets implique donc une décision sur la DÉFINITION de δ :
- (i) +2 % net des coûts complets : n_min reste 414 (plancher), et la barre d'entrée économique est plus haute ;
- (ii) +2 % net du gelé : W2 est sous-puissante pour A0, sauf en compte fermé (466).

## 4. Décisions du propriétaire (aucune n'est prise ici)

1. Adopter ou non le paramétrage unique, avant toute donnée W2.
2. S'il est adopté : la définition de δ, option (i) ou (ii) ci-dessus.
3. Pour C-B : faut-il une couche « garde + H-1 » sur les rangées statelab ? Elle serait nouvelle et à auditer, et
   elle changerait les rangées de C-B.
4. Dans tous les cas, le net gelé et le net coûts complets sont publiés côte à côte (R02).

## 5. Preuves

- `w2cost` 0.1 : 5 tests (formule, plancher, paramétrage non adopté, exclusion rtgate, impact sur fixtures
  déterministe).
- 10/10 mutants, avec la garde de base du lanceur (R02, 21:34Z).

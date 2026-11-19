# Voie B (verdict officiel W1 sur Google Cloud) : projection à partir des durées MESURÉES — v0.3, 19/11/2026

**La voie B est SUSPENDUE depuis votre décision du 15/11 (b9e596e3). Cette note n'engage aucune dépense** : elle
chiffre ce que coûterait le verdict officiel, pour votre décision le moment venu.

Aucun résultat de W1 n'est utilisé ici : seulement des durées, des dates de fichiers et des comptages relevés par
RUGGER 03 dans la lecture préliminaire (message du 18/11 à 17:47Z), et une borne calculée sur le code pour le
ledger (acceptée par RUGGER 02 le 18/11, registre 0c51450f). Chiffres recalculés par RUGGER 02.

## 1. Ce qui a été mesuré (session de RUGGER 03 : 4 vCPU Intel Xeon 2,30 GHz, 4 processus de calcul)

| Étape de la lecture préliminaire | Durée mesurée |
|---|---|
| selfcheck | 23 s |
| export (en flux) | 2 199 s, soit 37 min |
| série SOL/USD (en flux) | 852 s, soit 14 min |
| trials, 5 rejeux légers (bras V2) | environ 10 s chacun |
| trials, 8 rejeux lourds (bras L1), sans interruption | 7,19 à 8,03 h chacun ; moyenne 7,69 h (6 rejeux non interrompus) |
| trials, total net des interruptions | environ 60 h de calcul sur 4 processus, soit **239 à 257 heures-processus** |
| interruptions (3 redémarrages du conteneur, 1 blocage de nuit) | intervalles sans nouveau résultat : 15,7 h au total (dernier fichier avant l'arrêt → premier fichier après la reprise, relevés R03), dont environ 11 h 45 de blocage de nuit ; ces intervalles contiennent aussi du calcul refait (1 h 22, 27 min et 1 h 12 après les trois reprises) |

Borne basse (239) : les 8 rejeux lourds aux durées mesurées entre fichiers, hors fenêtres d'arrêt ; les deux rejeux
interrompus (R10 7,66 h, R13 5,94 h) y sont des minorants. Borne haute (257) : les 8 rejeux lourds à la plus longue
durée observée sans interruption, 8,03 h, soit 8 × 8,03 h × 4 processus.

Le rejeu officiel fait **exactement le même calcul** : mêmes fonctions gelées, mêmes 13 rejeux. Sa durée est donc
connue à la vitesse de la machine près.

## 2. Projection sur la machine prévue (n2-highmem-16 : 16 vCPU, soit 8 cœurs physiques, 128 Go ; le paquet fixe 8 processus)

En supposant chaque processus aussi rapide que chez R03. La machine a 8 cœurs physiques pour 8 processus ; la vitesse
réelle par processus reste à mesurer par le selfcheck sur la machine (§ 5) :

| Étape officielle | Projection |
|---|---|
| selfcheck, gate | quelques minutes |
| export (version gelée, tout en mémoire) | 0,5 à 1 h |
| série (version gelée) | environ 0,25 h |
| **trials** | **30 à 32 h** (239 à 257 heures-processus / 8) ; le plus gros pool, environ 95 min, ne limite pas |
| evaluate | non mesuré : 1 à 3 h (estimation) |
| ledger | **≤ 130 h en séquentiel ; inconnu sous la borne ; option P1** (voir § 2 bis) |
| attentes des ancrages de R02 (7 étapes) | 2 à 4 h si chaque ancrage arrive dans la demi-heure |
| **Total, sans le ledger** | **environ 34 à 41 h** |

## 2 bis. Le ledger : une borne haute seulement

Le ledger refait, sur **un seul processus**, l'observation du MASTER jusqu'à chaque décision d'entrée, pool par
pool et pour chacun des 4 bundles L1 ; son coût croît comme le carré du nombre d'événements du pool. D'après le code
seul, sans lire aucun résultat, il fait au plus le travail d'observation des 4 rejeux L1 correspondants :
**≤ 4 × 8,03 h × 4 processus ≈ 128 heures-processus, plus environ 1 h de lecture, soit ≤ 130 h en séquentiel**
(borne acceptée par R02, 0c51450f). Il fait sans doute bien moins (il saute les pools sans entrée et s'arrête à la
dernière décision d'entrée), mais on ne peut pas le dire sans lire des résultats : **aucun chiffre central**. Le
premier essai chez R03 a tourné plus de 2 h, le second tourne depuis le 18/11 à 19:54Z.

**Option P1** (autorisée par R02 à l'écriture seulement, audit et PASS requis avant tout usage) : le même ledger,
réparti par pool sur plusieurs processus, fichiers identiques octet pour octet. Borne divisée par le nombre de
processus, plus deux passes de lecture (environ 1 h, estimation) : **≤ 17 h environ avec 8 processus**. Sur la voie B,
elle demanderait en plus un amendement du paquet cloud (audit de R02 et votre accord).

## 3. Conséquence : l'enveloppe accordée ne suffit pas

L'accord du 15/11 (8cfead0e) fixe 48 h au plus et 60 USD au total ; le paquet audité (423dfd43) applique une date
limite à lancement + 40 h et refuse plus de 48 h.

- Avec 40 h, la date limite tomberait **avant la fin** de la chaîne dès que le ledger dure plus de quelques heures
  ou qu'un ancrage tarde : la machine serait supprimée avec le calcul en cours.
- **Avec une telle borne sur le ledger, l'enveloppe de 48 h et 60 $ est encore plus insuffisante.** Bornes hautes
  de la chaîne (34 à 41 h sans le ledger, plus le ledger) :
  - ledger séquentiel (paquet actuel) : **jusqu'à 164 à 171 h** de machine, soit jusqu'à environ 178 à 186 $ HT,
    **214 à 223 $ TTC** ;
  - ledger P1 sur 8 processus (amendement) : **jusqu'à 51 à 58 h**, soit jusqu'à environ 57 à 64 $ HT,
    **68 à 77 $ TTC**.
  Ce sont des bornes hautes, pas des prévisions : la durée réelle du ledger est inconnue sous la borne.
- Calcul : tarif relevé le 14/11 (1,048112 $/h, à revérifier), plus le disque de 200 Go (environ 0,03 $/h × la
  durée), plus le stockage et le téléchargement (environ 1,5 $), plus 20 % de TVA.

## 4. Options, pour la décision du propriétaire

| Option | Durée de machine | Coût TTC estimé | Ce qu'elle demande |
|---|---|---|---|
| A. Même paquet, enveloppe élargie (date limite relevée, plafond relevé) | jusqu'à 164 à 171 h avec le ledger séquentiel ; jusqu'à 51 à 58 h avec P1 | jusqu'à 214 à 223 $ ; avec P1, jusqu'à 68 à 77 $ | nouvel accord du propriétaire (durée et montant) ; amendement du paquet (la limite de 48 h est codée ; P1 en plus si retenu) ; audit de R02 |
| B. Machine deux fois plus grande (n2-highmem-32, 16 processus) | 25 à 35 h sans le ledger ; le ledger séquentiel n'en profite pas (≤ 130 h) ; avec P1 sur 16 processus, ≤ 9 h environ | sans P1 : non borné utilement ; avec P1 : jusqu'à environ 88 à 114 $ (2,096 $/h × 34 à 44 h, disque et stockage, plus 20 %) | amendement du paquet (nombre de processus, P1) ; audit ; accord |
| C. **Réutiliser sur la machine les 29 549 résultats par pool déjà calculés chez R03** | trials réduit à la relecture des archives (environ 1 h) : **environ 5 à 10 h de machine plus le ledger** | **environ 8 à 15 $ plus le ledger** | voir ci-dessous |

**Option C, détail.** Le module de calcul parallèle audité (w1aux v7.4, `parallel.py`) range chaque résultat par
pool sous une clé qui dépend du code gelé, du module lui-même, de l'empreinte sha256 de l'archive du pool, de la
série SOL/USD, de l'historique des créateurs et du rang de l'appel. Si l'export et la série officiels produisent
exactement les mêmes fichiers que les versions en flux (identité prouvée sur le pilote et les jeux de référence,
pas encore sur W1 entier), toutes les clés coïncident et la machine réutilise les résultats au lieu de les
recalculer ; **si un seul fichier diffère, les clés ne coïncident pas et la machine recalcule** : le défaut est sûr.
Les bundles restent assemblés par le code gelé sur la machine, et R02 peut exiger qu'une partie des pools (par
exemple les plus gros) soit recalculée sur la machine pour comparaison.
Avis de RUGGER 02 : option **admissible seulement comme amendement du paquet cloud, avec votre accord**. Elle ne
touche ni le protocole figé ni le code gelé. Conditions fixées par R02 :
1. audit complet de l'amendement (`--checkpoint` est aujourd'hui un argument interdit, et le répertoire n'est
   jamais transféré) ;
2. export et série officiels identiques octet pour octet aux versions en flux (empreintes ebe1959d et 7458f615),
   sinon recalcul intégral ;
3. répertoire de résultats transféré tel qu'ancré (environ 0,52 Go : 519 361 664 octets de résultats et un index de
   4 201 890 octets, ancré 5c7d36fc) et revérifié sur la machine avant usage ; ce transfert relève de votre accord
   sur la voie B (8cfead0e, aujourd'hui suspendu), pas de l'accord du 17/11, qui ne concerne que la sauvegarde ;
4. recalcul sur la machine d'un échantillon fixé à l'avance (le dixième des pools les plus lourds d'un rejeu L1,
   plus un tirage aléatoire réparti sur les 13 rejeux, graine publiée) : un seul écart, et tout le répertoire est
   rejeté ;
5. faiblesse publiée : le contrôle de déterminisme interne de la chaîne comparerait alors deux calculs faits chez
   R03 ;
6. provenance déclarée dans le rapport officiel.

**Recommandation de R02, que je partage : préférer A ou B, avec un calcul intégral sur la machine.** Les résultats
déjà calculés chez R03 servent alors de **reproduction indépendante gratuite** : on compare après coup, fichier par
fichier, les résultats de la machine et ceux de R03, ce qui est une preuve plus forte que l'option C. L'option C
reste l'option économique, avec ses conditions.

## 5. Ce qui n'est pas vérifié

- La vitesse d'un processus sur n2-highmem-16 par rapport à la machine de R03 (processeurs différents) : la
  projection suppose la même vitesse. Un essai de quelques minutes sur la machine (selfcheck) la donnerait.
- La durée d'evaluate (jamais exécuté à cette échelle) et celle du ledger : pour le ledger, une borne haute
  seulement (§ 2 bis) ; l'option P1 n'est pas encore auditée.
- Le tarif horaire et les taxes, à revérifier dans le calculateur par le propriétaire.
- L'option C n'a pas été essayée : l'égalité des clés entre deux machines n'est démontrée que par construction.

# Voie B (verdict officiel W1 sur Google Cloud) : projection à partir des durées MESURÉES — v0.1, 18/11/2026

**Brouillon soumis à RUGGER 02. Aucun résultat de W1 n'est utilisé ici** : seulement des durées, des dates de
fichiers et des comptages relevés par RUGGER 03 dans la lecture préliminaire (message du 18/11 à 17:47Z).

## 1. Ce qui a été mesuré (session de RUGGER 03 : 4 vCPU Intel Xeon 2,30 GHz, 4 processus de calcul)

| Étape de la lecture préliminaire | Durée mesurée |
|---|---|
| selfcheck | 23 s |
| export (en flux) | 2 199 s, soit 37 min |
| série SOL/USD (en flux) | 852 s, soit 14 min |
| trials, 5 rejeux légers (bras V2) | environ 10 s chacun |
| trials, 8 rejeux lourds (bras L1), sans interruption | 7,19 à 8,03 h chacun ; moyenne 7,69 h (6 rejeux non interrompus) |
| trials, total net des interruptions | environ 60 h de calcul sur 4 processus, soit **240 à 257 heures-processus** |
| interruptions (3 redémarrages du conteneur, 1 blocage de nuit) | 15,7 h perdues ou mortes, plus du calcul refait |

Le rejeu officiel fait **exactement le même calcul** : mêmes fonctions gelées, mêmes 13 rejeux. Sa durée est donc
connue à la vitesse de la machine près.

## 2. Projection sur la machine prévue (n2-highmem-16 : 16 vCPU, 128 Go ; le paquet fixe 8 processus)

En supposant chaque processus aussi rapide que chez R03 (à vérifier, voir § 5) :

| Étape officielle | Projection |
|---|---|
| selfcheck, gate | quelques minutes |
| export (version gelée, tout en mémoire) | 0,5 à 1 h |
| série (version gelée) | environ 0,25 h |
| **trials** | **30 à 32 h** (240 à 257 heures-processus / 8) ; le plus gros pool, environ 95 min, ne limite pas |
| evaluate | non mesuré : 1 à 3 h (estimation) |
| ledger | **à compléter** par la durée mesurée chez R03 (étape suivante de la lecture préliminaire) |
| attentes des ancrages de R02 (7 étapes) | 2 à 4 h si chaque ancrage arrive dans la demi-heure |
| **Total, sans le ledger** | **environ 34 à 41 h** |

## 3. Conséquence : l'enveloppe accordée ne suffit pas

L'accord du 15/11 (8cfead0e) fixe 48 h au plus et 60 USD au total ; le paquet audité (423dfd43) applique une date
limite à lancement + 40 h et refuse plus de 48 h.

- Avec 40 h, la date limite tomberait **avant la fin** de la chaîne dès que le ledger dure plus de quelques heures
  ou qu'un ancrage tarde : la machine serait supprimée avec le calcul en cours.
- Il faut compter **de l'ordre de 45 à 60 h** de machine, ledger compris (fourchette à resserrer avec la durée
  mesurée du ledger).
- Coût au tarif relevé le 14/11 (1,048112 $/h, à revérifier) : 45 h → 47 $ HT ; 60 h → 63 $ HT ; plus le disque de
  200 Go (environ 0,03 $/h, soit 1,4 à 1,6 $) et le stockage et le téléchargement (environ 1,5 $). **Total : environ
  50 à 66 $ HT, soit 60 à 79 $ TTC avec 20 % de TVA.** Au-dessus du plafond de 60 $ dans presque tous les cas.

## 4. Options, pour la décision du propriétaire

| Option | Durée de machine | Coût TTC estimé | Ce qu'elle demande |
|---|---|---|---|
| A. Même paquet, enveloppe élargie (date limite à 60 h, plafond relevé) | 45 à 60 h | 60 à 79 $ | nouvel accord du propriétaire (durée et montant) ; amendement du paquet (la limite de 48 h est codée) ; audit de R02 |
| B. Machine deux fois plus grande (n2-highmem-32, 16 processus) | 25 à 35 h | du même ordre que A (le prix par heure double, la durée est presque divisée par deux ; les attentes coûtent plus) | amendement du paquet (nombre de processus) ; audit ; accord |
| C. **Réutiliser sur la machine les 29 549 résultats par pool déjà calculés chez R03** | trials réduit à la relecture des archives (environ 1 h) : **environ 5 à 10 h de machine plus le ledger** | **environ 8 à 15 $ plus le ledger** | voir ci-dessous |

**Option C, détail.** Le module de calcul parallèle audité (w1aux v7.4, `parallel.py`) range chaque résultat par
pool sous une clé qui dépend du code gelé, du module lui-même, de l'empreinte sha256 de l'archive du pool, de la
série SOL/USD, de l'historique des créateurs et du rang de l'appel. Si l'export et la série officiels produisent
exactement les mêmes fichiers que les versions en flux (identité prouvée sur le pilote et les jeux de référence,
pas encore sur W1 entier), toutes les clés coïncident et la machine réutilise les résultats au lieu de les
recalculer ; **si un seul fichier diffère, les clés ne coïncident pas et la machine recalcule** : le défaut est sûr.
Les bundles restent assemblés par le code gelé sur la machine, et R02 peut exiger qu'une partie des pools (par
exemple les plus gros) soit recalculée sur la machine pour comparaison.
Ce qu'elle demande :
- l'avis de R02 sur le principe : un résultat calculé hors de la chaîne officielle peut-il entrer dans le verdict
  officiel, avec quelle preuve (identité des clés, recalcul d'un échantillon) ;
- un amendement du paquet cloud (`--checkpoint` est aujourd'hui interdit dans les arguments d'étape, et le
  répertoire n'est jamais transféré) et son audit ;
- le transfert du répertoire de résultats vers le bucket (taille à mesurer par R03 ; l'accord actuel couvre 4,7 Go
  de données), donc l'accord du propriétaire ;
- inconvénient : le verdict officiel dépendrait de fichiers produits dans la session de R03 ; leur intégrité est
  vérifiée (sha256 de chaque fichier dans l'index), mais ce n'est plus un calcul de bout en bout sur une seule
  machine.

## 5. Ce qui n'est pas vérifié

- La vitesse d'un processus sur n2-highmem-16 par rapport à la machine de R03 (processeurs différents) : la
  projection suppose la même vitesse. Un essai de quelques minutes sur la machine (selfcheck) la donnerait.
- La durée d'evaluate (jamais exécuté à cette échelle) et celle du ledger (mesurée bientôt chez R03).
- Le tarif horaire et les taxes, à revérifier dans le calculateur par le propriétaire.
- L'option C n'a pas été essayée : l'égalité des clés entre deux machines n'est démontrée que par construction.

# Verdict officiel W1 (B1) : coût, durée et routes — v0.4, 20/11/2026 (RUGGER 01, pour R04 ; audit R02 requis)

**Statut.** La voie B (Google Cloud) est SUSPENDUE depuis la décision du 15/11 (b9e596e3). Cette note n'engage aucune
dépense. Elle remplace la v0.3 (ddf5f216) sur les points ci-dessous. Tout ce qui n'est pas repris ici reste valable,
notamment les mesures du § 1 et le détail de l'option C.

Aucun résultat de W1 n'est utilisé ici : seulement des durées. Ce qui reste à confirmer est marqué « ⚠ ».

## 0. Ce qui change depuis la v0.3

1. **Le ledger a maintenant une durée MESURÉE** (R03, horodatages, 20/11). La v0.3 ne donnait qu'une borne : ≤ 130 h
   en séquentiel.
   - Le ledger reprenable v7.6 a tourné chez R03 sur W1, un seul processus, 2 344 appels. Il a duré **11 h 31 min
     05 s**, du 19/11 03:18:45Z au 19/11 14:49:50Z.
   - Un seul lancement, sans redémarrage. Mémoire : un plateau de 1,35 à 1,41 Go, avec un pic à 2,39 Go.
   - La relance avec la correction C1 a repris les 2 344 résultats en cache et a duré 313,5 s.
2. **Le paquet cloud de référence échouerait au ledger.**
   - Le paquet v2.6 (423dfd43) embarque w1aux **v7.4**. Son ledger signale à tort les 93 lignes C1 et donne FAIL.
   - La chaîne officielle s'arrêterait alors avant le dossier.
   - Il faut donc un **amendement C1** du paquet : w1aux v7.7, `ledger_c1` (audité par R02, PASS a03e12d0) et
     l'appel `--c1` dans la chaîne officielle. Cet amendement demande l'audit de R02 et l'accord du propriétaire.
   - L'accord du 20/11 couvrait la correction pour la chaîne exploratoire. Son extension à la chaîne officielle
     reste à confirmer.

## 1. Durées projetées sur n2-highmem-16 (8 processus), en supposant la vitesse par processus de R03 ⚠

| Étape | Durée |
|---|---|
| selfcheck, export, série | ≈ 1 à 1,5 h |
| trials (239 à 257 heures-processus / 8) | 30 à 32 h |
| evaluate (jamais mesuré) | 1 à 3 h (estimation) |
| ledger séquentiel (mesuré chez R03 : 11 h 31) | ≈ 11,5 h |
| ancrages R02 (7 étapes) | 2 à 4 h |
| **Total, calcul intégral, ledger séquentiel** | **≈ 46 à 52 h** |
| Total avec le ledger P1 sur 8 processus (≈ 1,5 à 2,5 h) | ≈ 36 à 43 h |

## 2. Options chiffrées

Calcul du coût :
- tarif relevé le 14/11 : 1,048112 $/h, à revérifier par le propriétaire ;
- disque de 200 Go : ≈ 0,03 $/h ;
- stockage et téléchargement : ≈ 1,5 $ ;
- TVA : 20 %.
Le plafond proposé correspond à la borne haute, plus 15 % de marge.

| Option | Machine | Coût HT | Coût TTC | Plafond proposé | DEADLINE à régler | Amendements du paquet |
|---|---|---|---|---|---|---|
| **A1** : calcul intégral, ledger séquentiel | ≈ 46 à 52 h | ≈ 51 à 58 $ | **≈ 61 à 70 $** | **80 $ TTC** | lancement + **60 h** | C1 ; limite de 48 h → 60 h |
| **A2** : calcul intégral, ledger P1 | ≈ 36 à 43 h | ≈ 40 à 48 $ | **≈ 48 à 57 $** | **66 $ TTC** | lancement + **50 h** | C1 ; P1 ; limite de 48 h → 50 h |
| **C** : réemploi des 29 549 résultats trials et du cache ledger de R03 | ≈ 5 à 10 h | ≈ 7 à 12 $ | **≈ 8 à 15 $** | **17 $ TTC** | lancement + 12 h | C1 ; `--checkpoint` et transfert ≈ 0,52 Go + cache ledger ; 6 conditions de R02 (v0.3 § 4) |

**Comparaison avec l'accord du 15/11** (60 $ au plus, DEADLINE à lancement + 40 h, 48 h au plus) :
- A1 dépasse les deux limites ;
- A2 tient dans le montant au point haut (57 $), mais pas dans les 40 h : la DEADLINE doit passer à 50 h ;
- C tient largement dans les deux.

**Recommandation de R02 (v0.3), que je maintiens : A (calcul intégral).** Les résultats de R03 servent alors de
reproduction indépendante gratuite. A2 coûte moins que A1, mais P1 n'est pas encore exécuté sur données réelles ;
A1 est la plus simple à auditer.

## 3. Route locale conforme (sans dépense) ? — OUI EN PRINCIPE, mais c'est une décision de méthode (R02)

- **Ce qui existe déjà chez R03 (chaîne exploratoire)** : mêmes fonctions gelées, mêmes identités que dayj (le
  module `explore` refuse tout changement d'identité), bundles et ledger C1 ANCRÉS par R02. Le ledger reprenable a
  tourné sans incident, et sa mémoire tient en 1,4 Go.
- **Ce qui manque pour un verdict « officiel »** :
  1. l'étape `evaluate` gelée, jamais appelée par `explore`, exécutée sur les bundles ancrés ;
  2. un amendement déclaré : les bundles exploratoires ancrés valent entrées officielles.
- **Coût** : 0 $. **Durée** : evaluate, 1 à 3 h (estimation), plus les ancrages.
- **Faiblesses** :
  - pas de reproduction indépendante : tout a été calculé dans le même conteneur ;
  - le conteneur a déjà redémarré trois fois ;
  - c'est un écart au paquet officiel de l'accord du 15/11.
- **Mon avis** : c'est la route la moins chère. À soumettre à R02, qui dira si elle est admissible ; je ne la
  recommande pas avant son avis.

## 4. Ce que le propriétaire aurait à faire

**Option A, cloud**, d'après la marche à suivre du paquet v2.6 (`MARCHE_A_SUIVRE_PROPRIETAIRE.md`), avec les
amendements ci-dessus :
1. donner un accord écrit : option, montant maximal TTC, DEADLINE maximale ;
2. vérifier le tarif dans le calculateur ;
3. régler `DEADLINE` juste avant le lancement ;
4. lancer `create_vm.sh launch`. La dépense commence ici.
5. transmettre les lignes de confirmation à R04 ;
6. laisser la suppression automatique à la DEADLINE.

**Route locale** : un seul accord écrit, pour l'amendement « bundles ancrés = entrées officielles » et l'exécution
d'evaluate par R03. Aucune dépense.

**Prérequis : la sauvegarde W1** (état donné par R03 le 20/11) doit être terminée avant toute route.
- Lots 1 à 5 : 724 objets envoyés, sans échec (R02 cc59695a). Le propriétaire doit encore exécuter le bloc de
  vérification (30db3a77).
- Lot 6a : 11 965 objets envoyés sur 31 921. L'envoi s'est arrêté sur une erreur HTTP 503, puis le jeton a expiré.
- Lot 6b : non envoyé.
- La reprise est prête (resume6.sh, PASS 23b3f520). Elle attend que le propriétaire fournisse un NOUVEAU jeton par
  le formulaire sécurisé ; l'ancien est considéré comme compromis.
- Ensuite : le contrôle de comptage final (count.sh v2, 32 655 objets attendus), puis le retrait du secret.
- Un **lot 7** reste à préparer et à faire auditer par R02 : ledger C1, lecture, ledger en échec, et sorties de
  w1loss et de w1migr.

## 5. Non vérifié

- La vitesse par processus sur n2-highmem-16 : un selfcheck de quelques minutes la donnerait.
- La durée d'evaluate.
- Le tarif.
- P1 sur données réelles.
- L'option C n'a jamais été essayée.

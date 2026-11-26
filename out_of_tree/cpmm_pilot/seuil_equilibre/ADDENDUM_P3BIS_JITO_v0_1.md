# Additif à la note « seuil d'équilibre » v0.1 (sha 9bf23a09) — pourboires Jito (précision R02, 13:55Z)

La note n'est pas modifiée : son sha reste la graine du recoupement de R02.

R02 rappelle que meta.fee ne contient pas les pourboires Jito. P3bis les mesure donc aussi :
- méthode : par transaction, la hausse de solde des 8 comptes de pourboire Jito publics, lue dans pre/postBalances ;
- les 8 comptes sont présents dans les clés des pages 6e27bf5 (2 097 à 3 277 occurrences chacun) ;
- sortie : p3bis_r01.json 2d971bac36db01ee42672216cfce636e06351d2500c819adfb2fae29514613fb. Elle remplace 24eaa1f2,
  dont les autres champs sont identiques.

Frais (meta.fee) + pourboire, swaps de 0,05 à 0,2 SOL côté WSOL, en médiane (achat / vente) :

| pool | frais + pourboire | part des tx avec pourboire | pourboire médian, quand il est payé |
|---|---|---|---|
| AEZjoU | 12 858 / 10 735 | 60 % / 64 % | ≈ 3 300 |
| G8kgi7 | 43 018 / 55 777 | 2,5 % / 2,4 % | 10 000 / 63 229 |
| GdxFyc | 105 000 / 105 000 | 0 % / 0 % | — |

Pour comparaison, le modèle gelé compte 105 000 par transaction. La conclusion de la note ne change pas :
- le fixe gelé est prudent sur deux pools sur trois ;
- le levier (2 transactions au lieu de 4) reste chiffré à 0,42 % → 0,21 % à 0,1 SOL et à 105 000 par transaction,
  pour une nouvelle expérience seulement ;
- pour G2-3, il ne comble pas l'écart entre les frais du pool (0,50 %) et le brut observé.

**Réserve R02 (14:04Z), à lire avec la note.** Ces frais sont ceux qu'ont payés D'AUTRES acteurs, en médiane. Notre
latence gelée de 4 slots peut exiger une priorité plus haute, plutôt de l'ordre du p90 : 410 000 de meta.fee sur G8kgi7.
D'où la formulation retenue : « fixe gelé prudent par rapport à la médiane observée ; non démontré pour une exécution à
4 slots ». Tout levier tiré de là reste réservé à une nouvelle expérience.

**Liste pour le recoupement de R02 (14:02Z)** : DECISIONS_21_G23_v0_1.json, produite par decisions21.py.
- Contenu : les 21 décisions primaires triées par (pool, indice de swap), avec pour chacune l'état d'achat (base,
  quote), on_input, le mouvement réalisé, et les seuils en conventions A et B à 0,1 SOL et à 5 SOL (frais 0,25 %).
- Tirage de R02 : random.Random(0x9bf23a09).sample(range(21), 5).

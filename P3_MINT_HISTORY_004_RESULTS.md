# Lecture historique bornée 004 — résultat

Préenregistrement distant : `d7474cf9fc26706752bbd3d1a7b56763c4e7559b`.
Plan canonique : `576793f828c0f772e0cbd4aebcfdce0b97d2d285db095ca4270fd2d8f89ce5da`.
Source déclarée : `b0eef8e464c3dfec1c28cd998b41bd3d66d0dad2`.

Exécution unique : **8/8 requêtes, 4 695/30 000 ms**, aucun retry. Une page mint
BNbNt…iTFm de **37 signatures** ; sept transactions réussies du préfixe fixé
(slot croissant puis signature) téléchargées et conservées. Aucun burn SPL parsé
sur le mint cible dans ces sept transactions. **Cela ne prouve pas une absence
de burn** : **26 transactions éligibles restent non téléchargées**.

La page contient la création historique. La borne basse préenregistrée était
strictement supérieure au slot 461979373 : une autre transaction au même slot
reste donc aussi hors sélection ; l'ordre transactionnel à l'intérieur de ce
slot n'est pas inféré par le tri des signatures.

Comparaison hors réseau avec la page pool ancienne : cinq références au mint
sont absentes de cette page pool reçue. Leurs slots sont 461979636, 461979675,
461979692, 461980644 et 461981360. Leurs signatures sont dans `qualification.json`.
Ce sont des pistes supplémentaires pertinentes pour les burns autonomes ;
leurs instructions n'ont pas été téléchargées et on ne peut pas encore affirmer
qu'elles ne référencent pas le pool ou qu'elles contiennent un burn.

Journal dédié fermé, exporté et relu : **19 événements**, ancre
`4f115ac378f61427ad26f41a6da25675a43e9c4fc739aab7990edcb9eec7fbc2` ;
archive gzip **17 487 octets**. Aucun fichier SQLite exporté. Résultats et preuves
locaux sous `/workspace/work/history-control-004/`.

**La divergence de supply de 979 542 505 800 unités reste non réconciliée.** Aucun
contrôle n'a été modifié. Aucun appel supplémentaire après épuisement du budget.
Une expérience distincte devrait préenregistrer l'examen des cinq références
supplémentaires avant toute nouvelle requête ; elles ne doivent pas être
substituées rétroactivement au préfixe de sept transactions du contrôle 004.

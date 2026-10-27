# Contrôle historique 006 — arrêt fournisseur et réconciliation partielle

Préenregistrement distant : `57eef76d2598bf55c78ff41c141ff6448e572050`.
Plan canonique : `ad170961e06d9199119da1b3a6ae1d7abc3c5c35cc71b10469d101475a70c0a8`.
Source : `43fb90ee9dec2721bada12ed7c50b9745a41da24`.

Exécution effectuée une fois par l'agent principal : **11 requêtes, 6 216 ms**.
Dix corps de transactions historiques reçus. La onzième tentative reçoit
**HTTP 429**, `reason=http_429`, sans erreur JSON-RPC ; arrêt immédiat avant le
second sous-lot, aucun retry ni basculement d'endpoint. Le reçu donne
`endpoint_kind=historical_alias`, latence **247,785736 ms**, request_id
`57eb61ac-269f-4090-9f64-c696eb80d147`.

Cette limitation fournisseur interdit de poursuivre automatiquement les lectures
sur cette même source/quota. Aucune nouvelle requête n'a été effectuée pour
cette qualification.

## Nouveau fait établi

Transaction `2RqoQg7RLKND91yZy3igvu9pgfrv4uw75ELgyc44WGfEMNiM3RPmK9MtQSdoecF4ASrGqL1oEKpb7xekqfzQZJ1H`,
slot **461979685** : burnChecked interne de **483 733 206 530** unités atomiques
du mint BNbNt…iTFm, depuis le même compte token public `6nVJP…959eL` que les deux
burns observés au contrôle 005. La transaction référence le pool : cela confirme
qu'un examen limité aux signatures absentes de la page pool ne suffit pas.

Deux méthodes concordent : lecture des instructions SPL parsées et somme exacte
des soldes du mint sur tous les comptes affectés avant/après la transaction.
Cette seconde méthode neutralise les transferts entre comptes du même mint ;
elle ne réutilise pas le montant de burn pour calculer la baisse des soldes.

| Élément | Unités atomiques |
|---|---:|
| Deux burns du contrôle 005 | 29 386 275 175 |
| Nouveau burn du contrôle 006 | 483 733 206 530 |
| **Total de trois burns prouvés** | **513 119 481 705** |
| Déficit historique mint/pool | 979 542 505 800 |
| **Résiduel non expliqué** | **466 423 024 095** |

La différence de supply n'est donc pas intégralement réconciliée. Aucun garde
n'a été modifié ou levé.

## Couverture et chronologie

Les archives combinées contiennent **23 corps sur les 35 transactions réussies**
éligibles de la page mint connue, création incluse. Les **23 contrôles de soldes
entiers concordent** avec burns moins mintTo. Aucun nouveau mintTo après la
création parmi ces corps.

L'autre transaction au même slot que la création est désormais conservée :
création transactionIndex **50**, autre transactionIndex **91**. Elle est
postérieure dans ce slot et ne contient pas de burn ; son bilan token est nul.
Cette ambiguïté de frontière précise est levée, sans supposer que le tri
lexicographique des signatures constitue un ordre on-chain.

**Douze corps manquent** : un refus HTTP 429 et onze lectures non tentées après
cet arrêt. Liste exacte avec slots et raisons dans `validation/P3_MINT_HISTORY_006_REMAINING.json` ;
la sélection originale du contrôle 006 n'est pas modifiée rétrospectivement.
La page d'un fournisseur n'est pas une preuve indépendante d'exhaustivité.

Journal dédié fermé, exporté et vérifié : **25 événements**, gzip **27 426 octets**,
ancre `7a62d2a496d274bb1dcaa099ae8115a2223a5abcfef2509b30c875d09f7fe7bb`.
Aucun SQLite exporté. Reproduction hors réseau :

```sh
python -B tools/verify_p3_history_006.py
```

Verdict économique : **INSUFFICIENT DATA**. Le refus fournisseur, les douze
signatures manquantes et le résiduel sont conservés pour une reprise autorisée
respectant la politique de quota ; aucun contournement ou nouvel essai immédiat
n'est justifié.

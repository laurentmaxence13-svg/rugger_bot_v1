# Contrôle prospectif 008 — préenregistrement

28 octobre 2026. Plan machine : `benchmarks/p3_prospective_inventory_v1/plan.json`.
Code publié et testé : `39fe7fd072b7076da49c88b4550cc08dcdbb57dc`.
Une seule collecte publique anonyme, gratuite, sans portefeuille, transaction,
ordre, retry ni changement de fournisseur. Aucun contrôle006/007 répété.

Les trois premiers mints/pools distincts du préfixe sort=new, cotés SOL, sont
figés avant toute lecture de leurs résultats. L'ordre, exclusions, créateurs
déclarés, refus et absences restent conservés ; aucun remplacement après échec.
Chaque achat indicatif de1SOL conserve Q attendu, minimum et Q//4 avant la vente.
Ni acquisition réelle ni transfert vérifié ne sont présumés.

| Lecture autorisée | Maximum |
| --- | ---: |
| Index public,100 lignes maximum |1|
| Trois pools racines groupés |1|
| Graphe initial groupé + blockTime |2|
| Trois achats1SOL,100bps |3|
| Trois ventes initiales de Q entier |3|
| Diagnostic Q//4 après provider_rejected HTTP200 initial uniquement |3|
| Graphe de suivi + blockTime |2|
| Trois ventes de Q entier au suivi |3|
| Une page limite1 de signatures du premier pool + sa transaction réussie |2|
| **Plafond GLOBAL toutes sources** |**20**|

Le suivi attend au moins15s depuis la fin du premier graphe et exige un slot
strictement supérieur. Deadline globale60s monotones, délai de résolution proxy
compris. Aucun probe santé additionnel. Tous les appels partagent le même compteur
et la même deadline. Une réponse HTTP200 provider_rejected/route_unavailable est
conservée puis le programme préfixé continue ; seul provider_rejected déclenche
Q//4. Première erreur HTTP, transport, timeout ou corps invalide : reçu persisté,
arrêt global, aucun fallback. Les erreurs de quota ne sont jamais réessayées.

La création n'est pas recherchée dans ce budget : UNKNOWN. blockTime est une
estimation de production du bank, jamais l'heure du devis fournisseur. Les
frais meta.fee de l'autre transaction restent une référence non applicable à
notre position. Coûts propres, ATA/rent, priorité et échecs inconnus restent null.
La projection locale de l'effet propre d'entrée garde son scénario contrefactuel ;
elle ne modifie pas le bank futur observé ni le stock fournisseur.

Rapport : candidats reçus/analysés, entrées projetées, full/partial/refus, couverture
maximale par horizon sans addition des quotes, slots, source times manquants,
frais par provenance, latences mesurées, cycles admissibles et P&L inconnu si requis.
Le bridge strict existant n'est pas assoupli. Ce premier contrôle technique peut
produire zéro cycle qualifié ; trois tokens ne constituent aucune preuve statistique.
P4 : tous en développement instrumental, groupe créateur conservé, aucun holdout
inventé. Validation future chronologique après gel du modèle, créateurs disjoints.

Exécution unique après publication de ce plan :

```sh
python -B -m bot.p3.prospective_campaign --network --plan benchmarks/p3_prospective_inventory_v1/plan.json --db /workspace/work/prospective-inventory-008.sqlite --output /workspace/work/prospective-inventory-008.json
```

Le journal neuf sera exporté fermé en JSONL.gz+manifest, sans téléverser SQLite.
Replay hors réseau sur ces exports et conservation des anciennes ancres.

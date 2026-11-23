# PAPER_LIVE — valeurs exactes à fournir par le propriétaire pour D-1 à D-7 (v0.1)

RUGGER 01, 23/11/2026. Référence : protocole PAPER_LIVE v0.2 (1386a40), jugé CONFORME par R02.
- Sans ces valeurs, rien n'est lançable (BLOQUÉ PAR LE PROPRIÉTAIRE).
- Avec elles, le banc `plbench` (SIMULATED_FEED, testé sur fixtures) donne la chaîne prête, le jour même.
- La seule autre étape préalable est l'ancrage de T0 par R02.

Chaque ligne demande une valeur précise. « Exemple » montre seulement la forme attendue : ce n'est pas une
recommandation. Les montants et les fournisseurs relèvent du propriétaire.

## D-1 — Hôte 24 h

| Champ | Forme | Exemple de forme |
|---|---|---|
| Fournisseur et type de machine | texte | « VM <fournisseur> <type> » |
| Région | texte | « europe-west1 » |
| Disque alloué aux journaux | Go, entier | 200 |
| Plafond de dépense de l'hôte sur 14 j | montant TTC | « ≤ N € » |
| Qui peut s'y connecter | liste de rôles | « R03 seul » |
| Horloge synchronisée (NTP) | oui / non | oui (exigé par l'arrêt 6) |

## D-2 — Source du flux

| Champ | Forme |
|---|---|
| Fournisseur | texte |
| Type d'abonnement : `logsSubscribe` + `getTransaction` par transaction, OU abonnement au niveau transaction (avec instructions internes) | un des deux |
| Niveau d'engagement : `confirmed` (rollback géré par rtgate `retract`) ou `finalized` | un des deux |
| Offre ou plan, avec ses quotas (requêtes/s, crédits) | texte + chiffres |
| Conditions d'utilisation archivées | sha256 du texte |

## D-3 — Plafond de crédits / de dépense de la fenêtre

| Champ | Forme |
|---|---|
| Plafond de crédits sur 14 j | entier |
| Plafond de dépense associé | montant TTC |
| Accord sur l'arrêt dur à 98 % (arrêt 1), sans reprise sans nouvel accord | oui |

## D-4 — SOL/USD en direct

| Champ | Forme |
|---|---|
| Source : compte Pyth on-chain (adresse) ou service Hermes (URL de base, sans clé) | texte |
| `max_age_ms` (règle R7 de W1 : de 1 000 à 120 000) | entier |
| `max_confidence_ppm` (de 1 à 10 000, ou aucun) | entier ou « aucun » |
| Accès réseau autorisé vers cette source | oui |

## D-5 — Secret du fournisseur

| Champ | Forme |
|---|---|
| Où la clé est stockée (secret de l'hôte, jamais lisible par un agent ni écrit dans un journal) | texte |
| Qui la fait tourner (rotation), et quand | texte |
| Confirmation du retrait du secret Helius de l'environnement R03 (état unique § 2) | oui + date |

## D-6 — Interface unique d'affichage

| Champ | Forme |
|---|---|
| Choix unique : Streamlit (Rugger Wallet), Render ou Vercel (décision D4) | un des trois |
| Les deux autres sont archivées | oui |
| Rappel : PAPER_LIVE s'affiche en PROSPECTIVE_PAPER, jamais en REAL ; le test T-14 étendu est obligatoire avant branchement | — |

## D-7 — Texte d'autorisation à écrire dans la session de l'exécutant

Modèle à recopier, puis à compléter avec les valeurs ci-dessus :

> « J'autorise R03 à exécuter une seule fois le PAPER_LIVE du protocole v0.2 (1386a40), pendant 14 jours à partir du
> T0 ancré par R02, en PAPER seulement, sans aucun ordre ni aucune signature, sur l'hôte <D-1>, avec la source
> <D-2>, le plafond <D-3> et la source SOL/USD <D-4>. Tout arrêt dur du § 7 est définitif sans nouvel accord. »

## Après les valeurs (rien d'autre n'est à décider par le propriétaire)

1. R02 ancre T0 et le sha du code (paperstream e86f66b0, rtgate 0d7ff001, papercost dd120b86, landslip guard
   27336325, ainsi que le code d'acquisition du flux, À ÉCRIRE pour la source D-2 et à auditer).
2. Le banc `plbench` est relancé sur fixtures avec le même sha. Il doit passer S-1 à S-6.
3. Démarrage. L'étiquette devient PAPER_LIVE pour les seuls cycles du flux réel. Les cycles ne comptent pour 50/20
   qu'après le `cycle_receipt` de R02.

**Ce qui reste à écrire** une fois D-2 connu : l'adaptateur d'acquisition (websocket + `getTransaction`, ou
abonnement transaction) vers le format des événements de rtgate. Ce code est nouveau, il doit être audité, et il n'est
pas écrit tant que la source n'est pas choisie (pour ne pas coder un fournisseur au hasard).

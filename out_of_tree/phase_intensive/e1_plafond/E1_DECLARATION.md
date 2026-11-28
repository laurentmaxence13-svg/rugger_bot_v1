# E1 — Plafond d'opportunité sur W1 LaunchLab (R01, 28/11/2026) — déclaration avant lecture

**EXPLORATOIRE W1 — CONDITION NÉCESSAIRE SEULEMENT, JAMAIS SUFFISANTE.** E[|m|] − c mesure la VOLATILITÉ accessible
à un oracle qui connaîtrait le signe, pas un avantage. Rien ici ne valide ni ne choisit une stratégie. Un plafond fermé
au coût réel ferme la piste ; un plafond ouvert ne prouve rien et ne fait que désigner une hypothèse à tester sur des
données NEUVES. Jamais une transaction du Master.

Ce fichier consolide la déclaration du 28/11 vers 12:20Z, son additif LaunchLab et les corrections E1-a à E1-f de R02,
avec ses trois précisions LaunchLab. Il est commité avant toute exécution. Graine = int(sha256(ce fichier)[:8], 16).

## Données

- Seulement l'export W1 LaunchLab ancré : sha256 du MANIFEST = ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e.
  Le script refuse tout autre MANIFEST, et tout répertoire ou MANIFEST dont le nom ou la sha commence par 9f19ccac
  (holdout P0, jamais ouvert). Les sha256 des fichiers sont contrôlées avant lecture.
- Ni pool ni fenêtre pilote. Les pilotes sont des pools CPMM ; au-delà d'une migration, rien n'est lu (voir Couverture).
- La sha256 de la liste triée des pools retenus est publiée, avec les pools exclus et leur raison (sans adresse dans
  la sortie : seulement des comptes par raison).
- Chronologie : collector.summarize puis historical_research_replay.usable_timeline, gelés. Un pool que
  usable_timeline exclut est compté par raison et n'est pas utilisé. Un pool sans block_time sur un événement est exclu.

## Entrées

- Début de couverture : creation_block_time si la plus ancienne transaction stockée est la création de ce pool
  (creation_facts), sinon le premier événement observé, et l'âge est alors « inconnu ».
- Fin de couverture, par ordre de priorité : fin de collecte du pool fournie par l'inventaire de R03 (fichier JSON
  {pool: horodatage}), sinon le dernier événement observé. Le motif est publié. Pour un pool migré, la couverture
  s'arrête au block_time de la transaction frontière (boundary_slot).
- Tirage : blocs de 7 200 s à partir du début de couverture ; un instant uniforme dans les 3 600 premières secondes de
  chaque bloc (espacement ≥ 3 600 s) ; au plus 20 blocs par pool, tirés au hasard s'il y en a plus. Seuls les instants
  ≤ fin de couverture sont gardés. Générateur : random.Random('%d:%s' % (graine, pool)).

## Mesure

- Prix P(τ) : spot (virtual_quote + real_quote) / (virtual_base − real_base) de state_after() du dernier événement
  dont block_time ≤ τ ; avant tout événement, state_before() du premier.
- m(h) = P(t+h)/P(t) − 1, h ∈ {30, 120, 300, 900, 1 800, 3 600 s}.
- Censure, uniquement si t+h dépasse la fin de couverture. Motifs publiés séparément : fin de collecte, dernier
  événement (biais vers le haut, prudent pour « fermé » seulement), migration.
- Un pool sans échange sur ]t ; t+h] n'est PAS censuré : son prix est celui de l'état après son dernier échange.
  Le nombre de ces entrées « sans échange » est publié par horizon.
- Secondaire : excursion maximale |P/P(t) − 1| sur les événements de ]t ; t+h] et sur P(t+h) (borne d'oracle).

## Coût réel d'un aller-retour W1 à 0,1 SOL : c_eff (fonctions gelées)

- Sur l'état à t : buy_exact_in(état, 100 000 000, taux) puis sell_exact_in des jetons reçus, à mouvement nul, en
  convention B : le pire de la vente sur l'état après notre achat et de la vente sur l'état sans notre achat. Si la
  vente sur l'état sans notre achat est impossible (inventaire de courbe insuffisant), la convention A est employée et
  comptée.
- Taux = palier du pool : médiane des taux implicites gelés (replay._event_rate) de ses événements.
- Transactions : 2 × (base_fee_lamports + priority_fee_lamports) de ReplayParams gelé. Loyer perdu : 2 039 280
  lamports (SPL_RENT_LAMPORTS, N-1).
- c_eff = (100 000 000 − produit de la vente + transactions + loyer) / 100 000 000. Publié aussi sans le loyer.
- Une entrée où l'achat ou la vente est refusé par la courbe (par exemple, achat qui franchit la migration) a c_eff
  indisponible ; elle est comptée à part et exclue des cellules c_eff.
- La grille c ∈ {0,5 ; 0,95 ; 1,5 %} est publiée pour information seulement : aucun « ouvert » n'y est annoncé.

## Métriques par cellule (segment × classe × horizon)

- n entrées non censurées, n pools, n de Kish (Σn_p)²/Σn_p².
- p10, p50, p90 de m ; part de m > 0.
- Pour chaque c de la grille : part de |m| > c, de m > c, de m < −c, E[|m|] − c avec IC 95 % par bootstrap groupé par
  pool (2 000 tirages, numpy default_rng(graine)).
- Au coût réel : moyenne de c_eff, part de |m| > c_eff, E[|m| − c_eff] avec IC 95 % bootstrap et IC simultané de
  Bonferroni : estimateur ratio groupé par pool, erreur type robuste aux grappes, z = Φ⁻¹(1 − 0,05/(2K)), où K est
  le nombre de cellules rapportées au coût réel. Même chose pour l'excursion, publiée sans critère.
- Le nombre K et le nombre attendu à tort sous l'hypothèse nulle au seuil non corrigé (0,025 × K) sont publiés.

## Segments, fixés avant lecture

- tous : une seule classe.
- âge à l'entrée : < 1 h, 1–6 h, 6–24 h, 1–7 j, > 7 j, inconnu. Les premières heures de vie sont < 1 h et 1–6 h.
- réserve = SOL réel dans la courbe (real_quote à t) : < 1, 1–5, 5–20, 20–50, ≥ 50 SOL.
- progression de la courbe (progress_ppm à t), déciles fixes 0–10 %, …, 90–100 % : descriptif.
- palier de frais du pool, arrondi aux 500 ppm.
- activité = nombre d'événements sur ]t − 600 ; t] : 0, 1–2, 3–9, ≥ 10.
- proximité de la migration (block_time frontière − t) : pool non migré, ≥ 6 h, 1–6 h, < 1 h.
- Une cellule n'est rapportée que si elle compte au moins 30 pools. Sinon elle est marquée « n insuffisant », sans
  chiffre.

## Critère de lecture (descriptif)

Une cellule a un plafond OUVERT au coût réel si les deux conditions suivantes sont réunies :
- la borne basse de l'IC simultané de E[|m| − c_eff] est > 0 ;
- la part de |m| > c_eff est ≥ 25 %.

Sinon, elle est FERMÉE.

Si aucune cellule n'est ouverte, la phrase publiée est : « aucun segment n'offre de plafond ouvert au coût réel W1 :
l'approche directionnelle à court terme sur ces courbes est à revoir ».

La sortie ne contient aucune adresse de pool, de créateur ni de signature.

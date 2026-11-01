# 2026-11-01 — première campagne prospective longue Helius (PAPER ONLY)

**Source:** [GitHub Actions run 41256274821](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41256274821), artifact `rugger-creator-campaign-41256274821` (4 windows; no financial execution). SHA-256 de chacune des 4 sources JSON contrôlé contre `prospective_41256274821_summary.json`, concordance **4/4**.

| Fenêtre | Durée WebSocket observée | Logs réussis retenus | Indices Initialize attribués à LaunchLab | Reçus cryptographiquement vérifiés | Créations signées | Limite de 100 logs atteinte avant la fin |
|---|---:|---:|---:|---:|---:|---|
| 1 | 57,577 s | 100 | 0 | 2 non-créations | 0 | Oui |
| 2 | 36,400 s | 100 | 0 | 2 non-créations | 0 | Oui |
| 3 | 60,599 s | 27 | 0 | 2 non-créations | 0 | Non |
| 4 | 60,623 s | 26 | 0 | 2 non-créations | 0 | Non |
| **Total** | **215,199 s** | **253** | **0** | **8 non-créations** | **0** | **2 fenêtres tronquées** |

Les 253 événements **ne sont pas** 253 créations vérifiées. Seulement 8 transactions ont été examinées comme candidates confirmées avec preuve cryptographique; toutes sont des non-créations. Les 245 autres événements n'ont pas été vérifiés individuellement pour la présence d'une création et ne prouvent donc pas l'absence de créations dans le flux. L'absence d'indice textuel `Initialize` sur cette période peut aussi provenir d'une limite de filtrage et mérite une mesure indépendante.

Autres observations: 0 signature répétée entre fenêtres, 0 créateur signataire qualifié, 0 gel S1 exploitable, 0 modèle de sortie S2 et **0 cycle économique PAPER vérifié**. Aucun P&L Master ni avantage Master/référence démontrable.

**Actions après audit:**

1. Élever le maximum par fenêtre de 100 à 200 événements (la capacité du collecteur bas niveau est déjà 200) pour éviter la coupure avant 60 s.
2. Enregistrer séparément deux **indices non fiables**: ancien préfixe `Instruction: Initialize...` et nouveau `Initialize` attribué à une invocation LaunchLab; ne promouvoir aucun des deux en preuve de création.
3. Compléter les étapes par un contrôle d'intégrité du flux, les motifs exacts de refus RPC/S1 et les éventuelles projections S2; ne pas compter un trader tiers comme un fill Master.
4. Préserver le budget Helius (≤10 RPC par fenêtre) et ne relancer que des expériences ayant un objectif de diagnostic.

**État:** protocole prolongé et correctifs implémentés dans la PR #55; aucune conclusion de profit ne peut être tirée de cette campagne.

# RUGGER 04 — supervision autonome : mécanismes, architecture, état

Préparé le 2026-11-04 par RUGGER 01 (mandat permanent du propriétaire).

**Mise à jour du 2026-11-04 :** la partie « R04-cloud » existe. RUGGER 04 est
désormais une session Claude Code Cloud indépendante et en lecture seule
(`session_016VkauFz4mBdySC1PoMsRCf`), que RUGGER 01 peut avertir par
`send_message` (`PROTOCOL.md` §9).

**Statut : la supervision autonome n'est pas acquise.** Elle ne le sera qu'après
deux preuves :
- une notification réellement reçue par le propriétaire ;
- un cycle complet, sans relais humain, du réveil de RUGGER 04 jusqu'à la notification.

## 1. Mécanismes réellement disponibles (vérifiés depuis une session Claude Code Cloud)

| Mécanisme | Statut | Preuve ou limite |
|---|---|---|
| `send_message` entre sessions Claude Code Cloud | **vérifié** | 10 réveils réels dans S-001 à S-003, chacun traité en quelques secondes |
| Réveiller une conversation claude.ai (RUGGER 04 actuel) | **aucun outil disponible** | `send_message` ne vise que les sessions Claude Code ; aucun outil de cette session ne peut écrire dans une conversation claude.ai. Que claude.ai propose lui-même des tâches planifiées n'est pas vérifiable d'ici : c'est à demander à RUGGER 04 (test P-002) |
| Lecture de GitHub par RUGGER 04 | **validée selon le propriétaire** (2026-11-04) | RUGGER 04 est devenu une session Claude Code Cloud. Il a lu le dépôt privé de test, les fichiers, les issues, les branches et les commits, et a vérifié le registre (101 événements, aucune anomalie). L'ancienne conversation claude.ai n'est plus le canal de supervision |
| `PushNotification` (session Claude Code → appareils du propriétaire) | **envoi accepté** | le 2026-11-04 à 00:28, la plateforme a répondu « Mobile push requested » ; **réception non confirmée** |
| Tâche planifiée avec notification push ou e-mail (`create_trigger`, nouvelle session à chaque exécution) | disponible, **non créée** | c'est une routine : autorisation du propriétaire requise |
| Abonnement aux événements d'une PR | vérifié (#101) | une seule session par PR ; inutile pour la supervision |
| Notifications natives de GitHub | **inopérantes** | tous les agents écrivent sous l'identité du propriétaire, et GitHub ne notifie pas une personne de ses propres actions |
| GitHub Actions avec e-mail ou webhook externe | exclu | demanderait un secret ou un service tiers, et activerait un workflow |

## 2. Architecture retenue

RUGGER 04 reste le **superviseur logique**. Il est réalisé en deux parties qui lisent
la même source : #103 et le registre T-REG.

```
agents R01/R02/R03 ──événement + réveil journalisé──▶ registre GitHub (#104…)
        │                                                   │
        └── pointeur journalisé ──▶ R04-cloud (session Claude Code, réveillable)
                                      1. accept-pointer
                                      2. r04-verify (lecture complète de GitHub)
                                      3. supervise  → notifications dues, sans doublon
                                      4. PushNotification ──▶ téléphone / app du propriétaire
                                      5. bloc `treg-notify` dans #103 (journal, source du dédoublonnage)
R04-chat (claude.ai) ◀── lit le corps de #103 et les blocs treg-notify, à la demande
```

- **R04-cloud.** Une session Claude Code dédiée, en lecture et notification
  seulement, sans push de code. Elle est déclarée comme successeur
  (`downstream`) de chaque tâche `report` et réveillée par pointeur journalisé
  quand une tâche est bloquée ou un audit en échec. Elle ne fait aucune autre
  écriture que ses blocs `treg-notify` dans #103.
- **R04-chat.** La conversation claude.ai actuelle, interface du propriétaire.
  Elle synthétise à partir de GitHub (`R04_PROCEDURE.md`, niveaux A et B) sans
  qu'on lui transmette de rapport.
- **Règles de notification** (`treg.py supervise`, lecture seule, testées) :
  - `step_done` : une tâche `report` est terminée ;
  - `audit_failed` : `changes_requested` ;
  - `decision_needed` : une tâche est bloquée, et seul le propriétaire peut agir ;
  - `stalled` : un réveil utile n'est pas journalisé après 15 minutes, ou une tâche prête n'est pas réservée ;
  - `integrity_alert` : `r04-verify` a répondu `DIVERGED`.

  Chaque notification porte une clé stable. Les clés déjà journalisées dans #103
  ne sont jamais renvoyées.
- **Filet de sécurité, en option.** Une tâche planifiée peu fréquente, avec
  notification push, qui exécute `supervise` et ne notifie que s'il y a quelque
  chose. Elle couvre le cas où aucun agent n'est réveillé. C'est une
  **routine : décision du propriétaire.**

**En attendant R04-cloud**, RUGGER 01 exécute `supervise` à la clôture de chaque
tâche `report` et à chaque réveil, envoie `PushNotification` et journalise un
bloc `treg-notify` dans #103. Le canal est le même, mais RUGGER 01 n'est pas
indépendant : ce n'est donc pas la cible.

## 3. Interventions réellement nécessaires du propriétaire (une seule fois chacune)

1. Confirmer la réception de la notification de test du 2026-11-04 à 00:28 UTC
   (« RUGGER T-REG: S-003 terminé… »).
2. Créer, ou laisser RUGGER 01 créer, la session R04-cloud, puis lui donner
   **dans sa propre session** son mandat : lecture de GitHub, `r04-verify`,
   `supervise`, `PushNotification` et blocs `treg-notify` dans #103 ; aucune
   autre écriture. Une autorisation ne peut pas venir d'un autre agent.
3. Optionnel : autoriser le filet de sécurité planifié et choisir sa fréquence.
4. Une fois : faire passer à RUGGER 04-chat le test P-002 (lecture de #103,
   `r04-verify` s'il exécute du code, et ses éventuels mécanismes de tâche
   planifiée), puis faire contrôler sa réponse par RUGGER 02.

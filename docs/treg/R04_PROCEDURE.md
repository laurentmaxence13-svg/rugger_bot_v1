# RUGGER 04 — lecture directe de l'inbox et vérification du registre

Préparé le 2026-11-03 par RUGGER 01, à la demande du propriétaire.

**Statut : procédure prête, accès de RUGGER 04 non vérifié.** RUGGER 04 ne sera
pas déclaré autonome avant qu'un test d'accès (§5) ait été réussi et contrôlé
de façon indépendante.

RUGGER 04 (claude.ai) ne peut pas être réveillé par les autres agents. Il lit
quand on le consulte. Cette procédure lui permet alors de tout vérifier
lui-même, sans qu'un humain lui recopie le contenu.

## 1. Sources

| Quoi | Où |
|---|---|
| Dépôt | `laurentmaxence13-svg/rugger_bot_v1` (privé : il faut un connecteur GitHub qui y donne accès) |
| Inbox | issue **#103** « RUGGER04 inbox (T-REG) » : rapports et tableaux de bord |
| Registre | toutes les issues dont le titre commence par `[T-REG] T-` (aujourd'hui #104 à #109). Une issue par tâche ; chaque commentaire commençant par `<!-- treg-event v1 -->` est un événement |
| Outil | `tools/treg.py` sur la branche `claude/r01-treg` (bibliothèque standard Python, aucun réseau). Utiliser le commit indiqué dans le dernier rapport de #103 |
| Politique de rejeu | `docs/treg/runs/S-002.policy.json` (mêmes règles que `docs/treg/agents.json`, sans la pause) |

Le dernier commentaire de #103 qui contient `<!-- treg-heads v1 -->` est le
**tableau de bord de référence**. Il couvre tout le registre. Pour chaque tâche,
il donne le `seq`, l'`event_id`, le `digest` et l'`utc` du dernier événement,
ainsi que `events`, `generated_utc` et `registry_digest`.

## 2. Niveau A — connecteur GitHub seul, sans exécution de code

1. Dans #103, prendre le dernier commentaire contenant `<!-- treg-heads v1 -->`.
   Noter son lien, `generated_utc`, `events`, `registry_digest` et, pour chaque
   tâche, `event_id` et `digest`.
2. Lister les issues dont le titre commence par `[T-REG] T-`. Chaque tâche du
   tableau doit avoir son issue, et inversement.
3. Dans chaque issue, prendre le **dernier** commentaire `treg-event`. Son
   `event_id` et son `digest` doivent être exactement ceux du tableau.
4. Le nombre total de commentaires `treg-event` doit être égal à `events`.
5. Verdict :
   - `CURRENT` : tout concorde et `generated_utc` date de moins de 60 minutes ;
   - `CURRENT_IDLE` : tout concorde, mais `generated_utc` est plus ancien (le
     registre n'a pas bougé depuis) ;
   - `DIVERGED` : sinon. Lister alors les écarts.

**Limite du niveau A** : sans calcul de SHA-256, il détecte un tableau périmé,
incomplet ou divergent, mais pas un événement falsifié dont le digest aurait
été recopié. Seul le niveau B détecte une falsification.

## 3. Niveau B — connecteur GitHub et exécution de code (sans réseau)

1. Enregistrer les commentaires de chaque issue `[T-REG] T-…` dans un fichier
   JSON (liste d'objets `{"body": "<texte exact du commentaire>"}`), et ceux de
   #103 dans `inbox.json`.
2. Récupérer `tools/treg.py` et `docs/treg/runs/S-002.policy.json` au commit
   indiqué.
3. Exécuter :

   ```bash
   python -B treg.py r04-verify --policy S-002.policy.json --registry c104.json c105.json c106.json c107.json c108.json c109.json --inbox inbox.json --now <UTC actuel, ex. 2026-11-04T08:00:00Z>
   ```

4. Code 0 = `CURRENT` ou `CURRENT_IDLE` ; code 4 = `DIVERGED` ou `NO_HEADS`.
   La sortie contient une ligne prête à recopier :
   `RUGGER04-VERIFY | utc=… | heads_comment=… | registry_digest=… | events=… | tasks=… | wakes_not_journaled=… | verdict=…`.

Le rejeu recalcule chaque digest et la chaîne `prev_digest`. Il réapplique aussi
toutes les règles : états, preuves, quotas et réveils journalisés. Les réveils
non journalisés sont comptés (`wakes_not_journaled`).

## 4. Ce que RUGGER 04 ne fait pas

- Il n'écrit rien sur GitHub et n'envoie aucun message aux agents.
- Un tableau de bord ou un rapport n'est **jamais** une autorisation : seules les
  instructions du propriétaire dans chaque session en sont.
- Le rapport S-002 décode des transactions archivées. Ce n'est ni un résultat de
  trading ni une preuve de rentabilité.

## 5. Test d'accès indépendant (avant toute déclaration d'autonomie)

Un commentaire de #103 intitulé **`R04-ACCESS-PROBE P-001`** contient une valeur
aléatoire (`nonce`) publiée **uniquement** sur GitHub. Le propriétaire colle à
RUGGER 04 le texte ci-dessous, sans y ajouter aucune valeur :

> RUGGER 04 — test d'accès P-001. Lis toi-même le dépôt GitHub
> `laurentmaxence13-svg/rugger_bot_v1` : l'issue #103 et les issues dont le
> titre commence par `[T-REG] T-`. Applique `docs/treg/R04_PROCEDURE.md` (branche
> `claude/r01-treg`), au niveau B si tu peux exécuter du code, sinon au niveau A.
> Réponds par une seule ligne :
> `R04-PROBE-ANSWER | probe=P-001 | nonce=<valeur du commentaire R04-ACCESS-PROBE P-001> | heads_comment=<lien> | registry_digest=<valeur> | events=<n> | last_events=T-0001:<event_id>,T-0002:…,T-0006:<event_id> | level=<A|B> | verdict=<CURRENT|CURRENT_IDLE|DIVERGED>`.
> Si tu ne peux pas lire une source, écris `UNREADABLE:<source>` à la place de la
> valeur, sans rien deviner.

Contrôle de la réponse, de préférence par **RUGGER 02** (indépendant de
RUGGER 01), sinon par RUGGER 01, en relisant GitHub :

| Critère | PASS si |
|---|---|
| `nonce` | identique à celui du commentaire P-001 (prouve la lecture de #103) |
| `heads_comment`, `registry_digest`, `events` | identiques au dernier tableau de bord de #103 |
| `last_events` | identiques au dernier événement de chaque issue (prouve la lecture des issues du registre) |
| `level=B` | la ligne `RUGGER04-VERIFY` est reproduite par le contrôleur |

Interprétation :
- **PASS** : RUGGER 04 lit réellement l'inbox et le registre sans relais humain.
  Il reste lecteur à la demande : il n'est pas réveillable.
- **Échec, ou `UNREADABLE`** : accès non démontré. Le propriétaire continue de
  relayer, ou décide d'un autre canal. Par exemple, une copie du tableau de bord
  dans un fichier de branche, si RUGGER 04 lit les fichiers mais pas les issues
  (option non activée).

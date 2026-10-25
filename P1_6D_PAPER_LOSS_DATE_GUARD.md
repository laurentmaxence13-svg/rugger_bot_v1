# P1.6d — Garde de dates du contrôle de perte journalière PAPER

## Référence et périmètre

Contrôles préalables réussis : branche active main, HEAD et main exactement
`acccf8d800290b2fbb838daaef68053b7afafc2e`, aucun changement local signalé par
le statut Git complet. AGENTS.md et le plan technique ont été relus.

Correctif local sur `fix/p16c-paper-loss-date-guard`. Aucun commit, push ni
fusion ; le HEAD et main restent à la référence.

Fichiers modifiés/créés :

- `bot/analyser/paper_trader.py` : neuf lignes ajoutées dans entry_allowed.
- `tests/test_paper_loss_date_guard.py` : 21 nouveaux tests synthétiques.
- `tests/test_atomic_entry_limits.py` : horodatages de deux fixtures rendus causaux.
- `tests/test_research_pipeline.py` : horodatages d'une fixture rendus causaux.
- `P1_6D_PAPER_LOSS_DATE_GUARD.md` : ce rapport.

Aucun changement du capital initial 10 SOL, de l'allocation, des plafonds de
perte, des scores, modèles, stratégies, TP/SL, prix, frais, rotation P1.6a ou
parsing P1.6b. Les autres anomalies P1.6c sont laissées intactes.

## Cause et preuve avant correction

Dans la référence, paper_trader.py:328-338 agrège les clôtures après filtrage
`exit_time >= day_start AND exit_time <= now`. Une date NULL n'appartient pas
à cet ensemble. Le compteur des PnL manquants est lui aussi limité à cet
ensemble et ne voit donc pas la clôture sans date.

Le test `test_null_exit_time_cannot_bypass_realized_loss` a été créé et exécuté
sur la copie contenant le module original, avant sa modification :
**1 failed, 20 deselected**, 0,25 s. L'assertion attendait False et recevait True.

Scénario synthétique :

1. Capital initial 10 SOL ; entrée de 1 SOL au prix 1.
2. Sortie au prix 0,02 ; rendement brut -98 %, coût total 2 %, PnL -1 SOL.
3. Capital réalisé 9 SOL ; avec date de clôture renseignée, l'entrée suivante
   est refusée à la frontière de perte journalière de 10 %.
4. Retrait de la seule date de clôture dans la fixture : le contrôle original
   renvoie True, alors que PnL et capital n'ont pas changé.

Les données de ce scénario sont intégralement synthétiques. Aucune base réelle
n'a été lue, réparée ou modifiée.

## Politique FAIL-CLOSED retenue

Le garde ajouté à paper_trader.py:329-337 s'exécute uniquement dans la branche
déjà existante où la limite est active : valeur non None et strictement positive.
Il lit toutes les clôtures, avant le filtrage journalier.

Pour chaque ligne closed, les conditions nécessaires sont :

- entry_time, exit_time et pnl_sol sont des nombres stockés int/float et finis ;
- `0 <= entry_time <= exit_time <= int(now)`.

Si l'une échoue, entry_allowed renvoie False. Cela couvre dates absentes,
négatives, non numériques, infinies, sorties antérieures à l'entrée ou futures,
ainsi que PnL absent/non numérique/non fini. Une clôture de gain sans date est
aussi refusée : le garde ne suppose pas que seuls les perdants importent.

Les horodatages UNIX numériques fractionnaires valides restent acceptés ; les
bornes de journée et de contrôle restent celles existantes, à la seconde UTC.
Une chaîne numérique convertie par l'affinité SQLite en nombre est évaluée dans
son type stocké ; aucune coercition de texte invalide n'est ajoutée.

Le contrôle porte sur tout l'historique closed, y compris les jours précédents.
Une ligne incomplète ne peut pas être déclarée sans effet sur la reconstruction
du capital de début de journée. Aucun exit_time, PnL, statut, prix ou capital
historique n'est écrit par ce garde. Il ne tente aucune réparation ni déduction
de date à partir de l'entrée, de la détection ou d'autres événements.

Avec un historique valide, l'agrégation journalière et la formule existante sont
inchangées : capital de début de jour = capital réalisé courant - PnL du jour ;
refus si PnL du jour <= -capital de début de jour × limite/100.

Avec une limite explicitement désactivée (`None`, zéro ou valeur négative selon
la politique existante), ce nouveau garde n'est pas exécuté. Les autres limites
et contrôles existants continuent de s'appliquer : une désactivation du contrôle
journalier ne désactive pas le contrôle de capital ni le plafond de positions.
Les paramètres hors contrat non finis ne sont pas redéfinis par ce correctif.

## Appels, verrou SQLite et sorties

Les appels ont été examinés dans paper_engine.collect_once, paper_trader.run et
_record_quote. La vérification du collecteur est une permission préliminaire.
Le contrôle décisif reste celui de _record_quote, désormais paper_trader.py:727,
dans la transaction d'insertion/réservation ouverte par record_quote
(`BEGIN IMMEDIATE` ou savepoint appartenant à l'appelant).

Le nouveau garde est donc réévalué sous le même verrou que l'entrée. Un test
avec deux connexions force une invalidation de date en cours de transaction,
puis fait attendre l'entrée sur le verrou. Après commit du rédacteur, l'entrée
voit la date NULL et est refusée sans altérer le capital ni l'historique.

La branche de gestion d'une position open est antérieure au chemin de nouvelle
entrée. Elle ne passe pas par ce garde. Le suivi et les clôtures restent donc
possibles avec allow_entry=False ou lorsque l'historique interdit de nouvelles
entrées. Test exécuté : position ouverte + ancienne clôture sans date ; la
position ferme au TP, son PnL est appliqué une fois, puis les nouvelles entrées
restent refusées. La fermeture conserve les contrôles d'intégrité financière
qui existaient déjà : elle n'est pas autorisée à ignorer un PnL historique
manquant ou un capital non réconcilié.

## Tests exacts

Copie isolée : `C:/Users/maxen/AppData/Local/Temp/rugger_p16d_k_awhgmi`.
Python 3.13.15 et pytest 9.1.1 existants ; aucun ajout de dépendance.
Le module original est sauvegardé sous paper_trader.before.py ; le commit de
référence est une seconde version de retour arrière.

Le lanceur externe au dépôt neutralise load_dotenv, les connexions et DNS,
désactive les plugins externes automatiques et l'écriture de pyc. La paire de
sockets locale interne d'asyncio Windows reste autorisée. Toutes les bases
sont synthétiques temporaires/en mémoire. Aucun .env, secret, base réelle,
service RPC/WS/API ou bot réel utilisé.

Commande baseline et suite finale, dans cette copie :

```text
<python de la .venv> -B audit_runner.py -q tests --ignore=tests/tests -p no:cacheprovider -rs
```

| Exécution | Résultat exact | Durée pytest |
|---|---|---:|
| Baseline originale avant changement | 253 passed, 1 skipped, 202 subtests passed | 12,83 s |
| Régression de date NULL contre le module original | 1 failed, 20 deselected, échec attendu | 0,25 s |
| Nouveaux tests après correction et correction de leur fixture de timeout | 21 passed, 22 subtests passed | 0,31 s |
| Première suite complète avec les anciennes fixtures non causales | 3 failed, 271 passed, 1 skipped, 224 subtests passed | 13,02 s |
| Suite finale avec fixtures causales | **274 passed, 1 skipped, 224 subtests passed** | **12,78 s** |

Le premier essai ciblé avait aussi révélé une erreur de la nouvelle fixture
« zéro net » : un prix +2 % ne déclenche pas le TP de 10 %. Cette fixture attend
désormais le timeout existant à 3600 secondes pour fermer, puis avance le temps
avant de vérifier l'entrée suivante. Aucun seuil ou comportement de production
n'a été changé pour faire passer ce test.

Les trois échecs de la première suite complète étaient des fixtures existantes
qui revenaient en arrière : deux boucles entraient à 160 après une clôture à
200, et le scénario TP/SL entrait le second trade à 1060 après la clôture du
premier à 1070. Les temps avancent désormais à chaque opération. Les assertions
de plafond journalier et de TP/SL restent identiques ; l'ultime entrée refusée
est aussi datée après les clôtures pour tester réellement le plafond.

Le test ignoré est `tests/test_research_pipeline.py:17`, « base utilisateur
absente », conformément à l'isolement. Les 202 sous-tests de référence restent
inclus ; 22 sous-tests supplémentaires couvrent les cas de données invalides
et la désactivation. Les sous-tests ne s'additionnent pas aux tests parents.
Les 23 tests indépendants de P1.6c restent hors dépôt et ne sont pas comptés.

| Scénario obligatoire | Preuve exécutée |
|---|---|
| Sans pertes / PnL net nul | Entrées autorisées, capital initial 10 SOL conservé |
| Perte sous le seuil | -0,22 SOL : entrée autorisée, capital 9,78 SOL |
| Perte exactement au seuil | -1 SOL : entrée refusée, capital 9 SOL |
| Perte au-delà | -1,02 SOL : entrée refusée, capital 8,98 SOL |
| Plusieurs pertes | -0,52 puis -0,49296 SOL : refus, capital 8,98704 SOL |
| exit_time NULL | Refus dans entry_allowed et record_quote ; historique/PnL/capital inchangés |
| pnl_sol NULL | Refus même pour une clôture du jour précédent |
| Mélange valide/incomplet | Une clôture de gain sans date suffit à refuser |
| Clôture d'un jour précédent | Non comptée comme perte du nouveau jour si historique complet |
| Clôture interjournalière | Perte affectée au jour de sortie |
| Dates invalides / futures | NULL, texte, valeurs négatives/infinies/NaN et ordre entrée-sortie invalide refusés |
| PnL invalide | NULL, texte, infinis et NaN refusés |
| Désactivation explicite | None/0/-1 : comportement précédent conservé ; autres limites actives |
| Redémarrage et rejeu | Refus conservé après réouverture du fichier ; aucune double entrée ou double PnL |
| Positions ouvertes | Clôture au TP malgré garde négative ; application unique du PnL |
| Atomicité | Permission préliminaire périmée refusée sous transaction ; concurrence de deux connexions testée |
| Transaction appelante | Rollback restaure la date de fixture et annule les écritures dépendantes |
| P1.6a/P1.6b | Leurs tests sont inclus sans modification dans la suite complète |

## Comparaisons financières avant/après

Le script comparison.py de la copie charge le module sauvegardé puis le module
corrigé. Douze cas comparent exactement permission, message, quatre tables
paper_prices/paper_trades/paper_portfolio/paper_decisions et paper_report.
Les neuf cas avec historique valide sont identiques ; les trois cas de garde
désactivée avec date NULL sont également identiques.

| Cas | Capital réalisé avant = après | Entrée suivante avant = après |
|---|---:|---|
| Aucun historique | 10 SOL | Autorisée |
| Perte inférieure | 9,78 SOL | Autorisée |
| Frontière -1 SOL | 9 SOL | Refusée |
| Perte supérieure | 8,98 SOL | Refusée |
| Pertes cumulées | 8,98704 SOL | Refusée |
| Perte du jour précédent | 9 SOL | Autorisée |
| Fermeture aujourd'hui d'une entrée de la veille | 9 SOL | Refusée |
| Gain | 10,18 SOL | Autorisée |
| Timeout à PnL net nul | 10 SOL, à l'arrondi flottant près | Autorisée |
| Date NULL, limite None / 0 / -1 | 9 SOL, chaque cas | Autorisée selon la politique explicitement désactivée |

Les empreintes de snapshots et valeurs exactes sont dans comparison.json.
Les tests de refus comparent les lignes complètes paper_trades et
paper_portfolio avant/après : aucun PnL, statut ou capital n'est réécrit.
Une cotation refusée à l'entrée peut rester enregistrée, comme auparavant :
le garde interdit l'entrée, pas l'observation d'un prix valide.

## Limites restantes

- Le garde refuse conservativement toute clôture datée de façon inexploitable,
  même si elle concerne probablement un jour ancien. Seule une mission de
  qualification historique séparée pourrait lever cette incertitude ; aucune
  réparation automatique n'est introduite.
- Il ajoute une lecture de tout l'historique closed à chaque contrôle actif.
  Aucune mesure de coût sur une grande base réelle n'a été effectuée.
- Le contrat booléen de entry_allowed reste inchangé ; aucun nouveau champ de
  diagnostic ou système d'alertes n'est ajouté dans cette correction minimale.
- Les dates futures peuvent venir d'une horloge ou de données incohérentes :
  elles provoquent un refus, sans décalage de date ni correction de l'horloge.
- Le contrôle valide les dates et le caractère exploitable du PnL, sans
  remplacer tous les contrôles d'intégrité du ledger ou un audit des sources
  historiques. Il n'invente pas les pertes inconnues.
- Les anomalies distinctes de collecte, permission enregistrée, fermeture du
  fetcher en erreur de rapport, ratio de cotation et export de recherche
  singulier ne sont pas corrigées. Ce patch ne vaut pas GO global pour P2.

## Rollback précis

Après vérification qu'aucun changement ultérieur de ces fichiers n'est à
préserver, retirer uniquement ce correctif :

```powershell
git restore --source=acccf8d800290b2fbb838daaef68053b7afafc2e -- bot/analyser/paper_trader.py tests/test_atomic_entry_limits.py tests/test_research_pipeline.py
Remove-Item -LiteralPath '.\tests\test_paper_loss_date_guard.py', '.\P1_6D_PAPER_LOSS_DATE_GUARD.md'
```

Commandes documentées, non exécutées. La branche peut être conservée.
Ce rollback réintroduit le défaut de contrôle des pertes ; il ne remet aucune
base ou portefeuille à zéro. Aucune migration de schéma n'est nécessaire et
aucune base réelle n'a été touchée pendant cette mission.

Preuves locales de la copie : baseline.txt, regression-before.txt,
targeted-after.txt, validation-complete.txt, comparison.py, comparison.json,
paper_trader.before.py, audit_runner.py et sitecustomize.py.

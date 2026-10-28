# Endurance PAPER hors réseau — temps virtuel

28 octobre 2026. `bot/offline_endurance.py` sollicite le portefeuille natif existant
via `record_quote`, `settle_exit`, le garde opérationnel et la sauvegarde SQLite.
Aucune seconde comptabilité ni nouveau moteur de trading. Aucun appel de marché.

```sh
python -B -m bot.offline_endurance --output work/endurance-new --cycles 1000
```

Le dossier doit être neuf; budget entier2..1000 cycles, sans sommeil réel. La CLI
installe les interdictions réseau et `.env` avant les imports du moteur. Tous les
prix, devis, horodatages, heartbeats et coûts sont **synthétiques**. Une seule
position projetée de 1 SOL est répartie en N ventes partielles exactes. Chaque devis
déjà réglé est rejoué à une décision ultérieure, sans nouvelle réalisation.

Quatre phases alternent: sources saines, RPC périmé, urgence, WebSocket déconnecté.
Le garde bloque les nouvelles permissions dans les trois dernières; la gestion
de la position existante reste opérationnelle. Le parent teste séparément les
callbacks internes réels et le refus effectif de nouveaux candidats.

Dix sauvegardes online committed-only sont vérifiées puis **rouvertes comme
prochain livre actif**. Cela simule le choix manuel d'une copie de reprise: ces
fichiers de fixture deviennent donc modifiables après restauration, ce ne sont
pas dix archives immuables. Quantité restante, version, jambes et capital doivent
être identiques avant et après chaque reconnexion. Aucune base utilisateur lue.

Exécution conservée dans `validation/P5_OFFLINE_ENDURANCE.json`:1000 cycles,
1000 jambes,1000 replays sans double crédit,750 refus d'admission,10 sauvegardes et
10 reprises,4011 contrôles d'invariants, reliquat 0. Produits de fixture 1,05 SOL,
frais explicites 0,010005 SOL, P&L synthétique 0,039995 SOL et capital 10,039995 SOL.
Les montants vérifient uniquement les opérations du logiciel: ils ne mesurent
ni une espérance de stratégie ni un résultat de marché.

Tests ciblés: 8 passed, incluant budget invalide, conservation d'un dossier
préexistant et répartitions non divisibles des produits. Cette endurance ne
constitue pas un test d'exploitation24h/24, de latence réseau ou de marché réel.

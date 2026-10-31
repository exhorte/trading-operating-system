# Modèle temps réel du cockpit

Réécrit le 2026-10-09 (ADR 0016). Le cockpit se comporte comme un cockpit en direct : il s'abonne au flux du cœur et affiche le dernier état connu, sans interroger en boucle des endpoints REST.

## Les couches (`lib/websocket`, `lib/realtime`, `lib/api`)

```text
CockpitSocket      transport : connexion, jeton, reprise avec attente croissante, trames brutes
   ▼
CockpitController  orchestre : décide des lectures REST à refaire (resync, commandes, autonomie), envoie les gestes humains
   ▼
CockpitStore       état : un réducteur pur ; appliquer une trame rend la liste des effets à exécuter, il n'en exécute aucun
   ▼
useCockpit()       les écrans lisent l'état dérivé du compte actif ; useApi() lit une opération du cœur et la garde fraîche
```

Le store ne contient aucune règle de trading : il range ce que le cœur diffuse (`risk.state_updated`, `account.snapshot`, `position.*`, `autonomy.*`…) et dérive ce que l'écran affiche. Les ticks ne servent qu'aux prix affichés.

## États de connexion

| État | Sens |
|---|---|
| `connecting` | première tentative en cours |
| `connected` | le flux est établi **et** le cœur bat (`system.heartbeat` toutes les 2 s) |
| `reconnecting` | lien perdu, reprise automatique (attente 1 s → 10 s) |
| `stale` | lien ouvert mais plus de battement du cœur depuis 8 s : aucune décision n'est prise sur donnée périmée |
| `degraded` | lien et battement ok, mais le cœur signale une santé haute ou critique (`system.health_changed`) |
| `disconnected` | arrêté ou refusé (jeton, Origin) — le message dit pourquoi |

Il n'y a plus d'état « mock » : pour regarder le cockpit sans courtier, on lance le cœur en mode simulé (`MT5_ENABLED=false`), qui sert un compte de démonstration par le **même** chemin que le vrai.

## Instantané + événements

1. Se connecter, avec le jeton du cockpit (`/api/cockpit-token`, même origine).
2. Recevoir `system.snapshot` — première trame — et remplacer l'état.
3. Appliquer chaque trame suivante ; un identifiant déjà vu est ignoré.
4. Marquer l'état périmé quand le battement manque.
5. Après chaque reconnexion, repartir d'un nouvel instantané ; `{"type":"resync"}` le demande à tout moment.

Les lectures qui ne sont pas des événements (journal, analyse, limites d'un compte, calendrier) passent par `useApi("opération", …)`, qui garde la dernière réponse, la rafraîchit à l'arrivée d'un événement qui la concerne (`refreshOn`) ou sur une horloge (`pollMs`), et ne laisse jamais la réponse à une question périmée atterrir sur la suivante.

## Groupes d'abonnement

Compte et équité · positions et ordres · état de risque · contexte de marché · propositions de la stratégie · état de l'agent d'exécution · commandes · alertes et incidents. Tous les comptes par défaut ; un abonnement restreint à des comptes les limite (les faits globaux passent toujours).

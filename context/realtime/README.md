# Temps réel

Réécrit le 2026-10-09 (ADR 0016). À lire avant de toucher aux flux du cockpit, au lien avec l'agent MT5, aux commandes d'exécution ou aux contrats d'événements.

## Règle de fond

Ce qui change sous les yeux du trader passe par **un** WebSocket du cœur (`/ws`) ; les lectures et les gestes humains passent par REST. Pas de SignalR, pas de pont, pas de seconde enveloppe : un événement du domaine est une trame telle quelle.

## Fichiers

- `event_contracts.md` — la trame, les 54 événements, les messages du client, la contre-pression.
- `dashboard_realtime_model.md` — comment le cockpit se branche : transport, contrôleur, store, états de connexion.
- `mt5_wire_protocol.md` — le lien local entre le cœur et l'agent MQL5 (TCP, une ligne JSON par message).

L'architecture complète est dans `docs/architecture/python-native-architecture.md` (§ 9 : intégration du cockpit).

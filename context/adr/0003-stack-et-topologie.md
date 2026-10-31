# ADR 0003 — Stack et topologie

> **Amendement du 2026-10-09 (ADR 0016).** La pile décrite ci-dessous est remplacée : le backend .NET (`Contracts`, `Gateway`, `Host`, `Persistence`), SignalR, le WSS « lean » traduit par le Gateway et l'observateur Python n'existent plus. Un monolithe Python (FastAPI, REST + WebSocket) porte le métier ; le cockpit n'a plus de dépendance `@microsoft/signalr`. Tiennent toujours : le dépôt unique et le monolithe modulaire, le frontend Next.js / React / TypeScript / Tailwind, PostgreSQL/TimescaleDB sur le port hôte 5433 (le schéma s'applique désormais par migrations numérotées), et l'absence de tout identifiant de compte partagé. Voir `docs/architecture/python-native-architecture.md`.

Date : 2026-09-04. Statut : accepté. Consolide les anciens ADR 0002, 0003, 0009 et 0011, sans changement technique.

## Contexte

La stack a été choisie et validée en live pendant la série 1. Le pivot ne la remet pas en cause : reconstruire la chaîne temps réel coûterait des semaines pour un gain nul.

## Décision

Dépôt unique, monolithe modulaire.

- **Frontend** — Next.js / React / TypeScript / Tailwind, dans `app/` et `components/`. Le cockpit est sombre, dense, opérationnel.
- **Backend** — .NET sous `backend/`, solution `TradingOs.slnx` : `Contracts`, `Gateway`, `Host`, `Persistence`.
- **Temps réel** — SignalR côté cockpit ; WSS + JSON versionné « lean » côté MT5, traduit côté serveur par le Gateway. Le navigateur ne parle jamais directement au wire MT5.
- **Persistance** — PostgreSQL/TimescaleDB via `docker-compose.yml`, port hôte **5433**, schéma appliqué de façon idempotente au démarrage.
- **Bord MT5** — observer Python en lecture seule attaché au terminal déjà authentifié de l'utilisateur. **Aucun identifiant n'est jamais partagé avec le projet.**
- **HTTP** — surface secondaire : santé, export d'audit, administration. Les flux de trading passent par le temps réel.

## Conséquences

- Extraction de services seulement si opérationnellement justifiée. Ce n'est pas le cas aujourd'hui et ne le sera probablement jamais en usage personnel.
- Toute nouvelle dépendance runtime frontend doit se justifier ; à ce jour la seule est `@microsoft/signalr`.
- L'observer reste le point de fragilité connu (un stall observé le 28/07/2026). Piste si le problème revient : conteneurisation via `gmag11/MetaTrader5-Docker`.

# Stack

Réécrit le 2026-10-09 (ADR 0016) : ce qui est réellement utilisé, rien d'« à terme ». Chaque dépendance est justifiée ; une brique qui n'a pas de besoin écrit n'est pas dans la liste.

## Cœur — `python/`

| Brique | Rôle |
|---|---|
| Python ≥ 3.12 (développé en 3.14) | langage du cœur |
| FastAPI + uvicorn | REST et WebSocket du cockpit (`127.0.0.1:8000`), schéma OpenAPI |
| pydantic 2 + pydantic-settings | modèles du domaine, schémas d'API et d'événements, configuration (`.env`) ; `SecretStr` pour tout secret |
| psycopg 3 (async, pool) | PostgreSQL ; SQL explicite, pas d'ORM |
| MetaTrader5 (Windows) | lu dans **un processus enfant par terminal**, sur une liste blanche de fonctions de lecture ; aucun appel d'ordre côté Python |
| httpx | calendrier FRED |
| keyring | coffre Windows pour les identifiants, en option (`CREDENTIAL_STORE=windows`) |
| pytest, pytest-asyncio, ruff, mypy `--strict` | tests, lint, types |
| mcp (optionnel) | serveur MCP en lecture seule pour l'assistant |

## Cockpit — racine du dépôt

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS 4 · shadcn/ui sur Radix · lucide-react · Vitest · ESLint. **Lire la documentation locale de Next sous `node_modules/next/dist/docs/` avant de supposer une API** (`AGENTS.md`). Le client de l'API est typé par `lib/api/generated.ts`, généré depuis les schémas du cœur (`python -m trading_os gen-types`) ; un test Python échoue si le fichier est périmé.

## Agent d'exécution

MQL5 (`tools/mt5-execution-agent`) : un seul `OrderSend`, derrière un plafond de mode compilé à `OBSERVE` (ADR 0010). Compilé avec MetaEditor ; la compilation propre (0 erreur, 0 avertissement) est une gate.

## Infrastructure

PostgreSQL + TimescaleDB (un conteneur Docker, volume existant, `127.0.0.1:5433`). C'est le seul service Docker : le cœur et le cockpit tournent sur l'hôte Windows (le paquet MetaTrader5 est Windows-only). Pas de Redis, de RabbitMQ, de Seq ni de Prometheus : un événement interne est un appel de fonction (dispatcher en mémoire), l'audit est une table, les journaux vont sur la console.

## Stratégie d'architecture

Un **monolithe modulaire** : un processus, des frontières de code nettes (`domain/` pur → `services/` → `infrastructure/`, derrière `api/` et `runtime/`), vérifiées par des tests d'architecture. On n'extrait un service que si une contrainte technique forte le justifie — comme le processus enfant de lecture MT5 (module global, appels bloquants, plantages natifs).

## Stratégie de transport

REST pour les lectures et les gestes humains, **un** WebSocket pour tout ce qui change sous les yeux (ticks, états de compte, risque, commandes, incidents). Voir `docs/architecture/python-native-architecture.md` § 9.

# Vue d'ensemble du système

Réécrit le 2026-10-09 (ADR 0016). La description complète — composants, flux, sécurité, pannes — est dans `docs/architecture/python-native-architecture.md` ; ce document en donne la carte.

## Ce que c'est

Un poste de travail personnel pour un trader intraday, **Python-native** : un seul processus Python (le *cœur*) porte tout le métier — comptes, données de marché, stratégie, risque, exécution, positions, réconciliation, journal, autonomie, supervision. Le cockpit Next.js n'affiche et ne commande que par son API. L'agent MQL5 est l'exécutant local et le garde-fou, jamais le cerveau.

```text
cockpit Next.js ── REST + WebSocket ──▶ cœur Python (FastAPI, 127.0.0.1:8000)
                                          │
              ┌───────────────────────────┼────────────────────────────┐
              ▼                           ▼                            ▼
   processus enfant MT5          lien agent (TCP 9765)        PostgreSQL / TimescaleDB
   (lecture seule)                      │                       (Docker, 127.0.0.1:5433)
              ▼                           ▼
             MT5  ◀────────────────  EA TradingOsAgent ───▶ courtier (Exness | FTMO)
```

## Le flux d'une décision

```text
bougie clôturée ─▶ stratégie (S01) ─▶ intention de trade ─▶ Risk Engine ─▶ décision de risque
                                                                   │ refusée : journalisée, rien ne part
                                                                   ▼ approuvée
                                          moteur d'exécution : commande PENDING persistée ─▶ envoi selon le mode
                                          OBSERVE rien · PAPER simulé · CONFIRM/ARMED/AUTONOMOUS ─▶ agent ─▶ MT5
                                                                   ▼
                                          accusé ─▶ rapport ─▶ réconciliation avec MT5 ─▶ journal
```

Jamais `stratégie ─▶ exécution`. Le Risk Engine est le point de contrôle unique (ADR 0007) ; aucune règle ne passe par l'interface.

## Responsabilités par couche (`python/trading_os/`)

| Couche | Rôle |
|---|---|
| `domain/` | Règles pures, sans E/S : comptes et profils, marché et analyse ICT/SMC, stratégie S01, risque, exécution et machine à états, autonomie, journal et conformité. |
| `services/` | Un service par capacité, qui orchestre le domaine et l'infrastructure ; état en mémoire propre. |
| `infrastructure/` | Tout ce qui touche au monde : `mt5/` (processus de lecture, lien agent), `database/` (migrations, dépôts, journal d'événements), `news/` (FRED), `security/`. |
| `api/`, `app/` | FastAPI, WebSocket, garde jeton + Origin, schémas ; l'assemblage. |
| `runtime/` | Cycle de vie, superviseur, battement, ordonnanceur. |
| `cli/`, `mcp/` | Outils (lecture seule) : export/import de bougies, revue hebdomadaire, serveur MCP. |

## Communication

Le cockpit parle au cœur par REST (opérations nommées, types générés depuis le schéma OpenAPI du cœur) et par **un** WebSocket (`/ws`) : une trame par événement, un instantané en première trame, une file bornée par client. Il n'y a ni bus distribué, ni pont, ni traducteur de protocole : un événement du domaine devient une trame telle quelle. Le cœur et l'agent se parlent par un socket TCP local, une ligne JSON par message.

## Ce qui n'existe plus

La passerelle .NET, SignalR, l'observateur Python, l'exportateur de bougies et le worker de détection S01 comme processus séparés, et le moteur de risque évalué dans le navigateur. Raisons et inventaire : `docs/architecture/python-native-migration-report.md`.

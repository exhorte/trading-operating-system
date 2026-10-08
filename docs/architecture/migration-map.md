# Migration map — Trading OS vers une architecture Python-native

> Phase 0 de la mission « restructuration radicale » — **audit**. Produit le 2026-10-07 sur la branche
> `refactor/python-native-architecture` (point de départ : commit de snapshot `e53a4ac`).
> Chaque affirmation de ce document a été recoupée avec le code ; quand le rapport d'audit existant
> (`docs/project/trading-operating-system-blueprint.md`, lui-même déclaré « ÉBAUCHE PARTIELLE ») ou la mission
> diffèrent du code, **le code l'emporte** et l'écart est consigné au § 1.

Légende des décisions : **KEEP** (reste, éventuellement avec imports adaptés) · **MIGRATE** (la logique passe dans le cœur Python,
la source est ensuite supprimée) · **REWRITE** (la capacité reste, l'implémentation est refaite sur la nouvelle architecture) ·
**DELETE** (supprimé, remplacé par un autre mécanisme ou sans remplaçant) · **UNKNOWN** (usage non établi : décision à prendre,
avec son échéance). Les phases sont celles de la mission : P2 cœur · P3 compte + MT5 · P4 risque · P5 exécution · P6 frontend ·
P7 suppression radicale.

## 0. Résumé chiffré (417 fichiers suivis par git au snapshot `e53a4ac`, hors ce dossier `docs/architecture/`)

| Décision | Fichiers | Lignes |
|---|---:|---:|
| **KEEP** | 166 | 28038 |
| **MIGRATE** | 128 | 12761 |
| **REWRITE** | 56 | 17029 |
| **DELETE** | 63 | 7150 |
| **UNKNOWN** | 4 | 713 |

## 1. Écarts entre la mission, le rapport existant et le code (constatés, pas supposés)

| # | Constat vérifié dans le code | Conséquence pour la migration |
|---|---|---|
| E-01 | **Le Risk Engine n'est pas en C#** : c'est du TypeScript pur (`lib/risk/`, 623 lignes) évalué **dans l'onglet du navigateur** (`lib/realtime/signalr-client.ts` : `evaluateRiskState`, `detectNewLockout`). Côté .NET il n'existe que `RiskTodayRepository`, `AccountSettingsGuard` et la détection de violation T02c. | « Migrer le Risk Engine vers Python et supprimer les implémentations C# » = **porter le TypeScript** (51 tests) ; il n'y a presque rien à supprimer en C# pour le risque. Le déplacement côté serveur est exactement ce que l'ADR 0015 (I6) et le garde-fou « verrous appliqués côté moteur » exigeaient. |
| E-02 | `signalr-client.ts` (699 lignes) n'est pas qu'un transport : il contient la logique de risque, la publication des verrous, le calcul du contexte de marché, l'hydratation (4 appels REST) et la détection de changement de compte. | Cette logique **migre en Python** ; le nouveau client frontend ne fait que REST + WebSocket + rendu. |
| E-03 | Le Gateway .NET a **deux** entrées : le client WebSocket vers l'observateur Python (8765) **et** un serveur TCP pour l'agent MQL5 (9765, NDJSON). | Supprimer le .NET ne supprime pas le lien EA : l'EA n'a que cette voie (sockets/WebRequest). Le cœur Python doit **servir** ce lien (`infrastructure/mt5/ea_link.py`), protocole inchangé → l'EA et ses préréglages restent valides. |
| E-04 | Le pipeline S01 est une chaîne de **trois processus** reliés par des fichiers : `export_m1_candles.py` → `*.jsonl` → `run-setup-detection.ts` (sonde 60 s) → table `setup_proposals`. | C'est le modèle même de « worker A → worker B → pont » à supprimer : un `StrategyRuntime` intégré lit MT5 directement. |
| E-05 | **Aucun ordre réel n'a jamais été émis.** L'unique `OrderSend` est dans `ExecuteOrder` (EA), inatteignable : `g_mode`/`g_mode_ceiling` sont des `const` `MODE_OBSERVE` (`TradingOsAgent.mq5:92,98`). L'observateur Python n'a aucun `order_send` *par construction*. | La migration **ne crée aucun second chemin d'ordre** : le cœur Python commande l'agent (même chemin, autre émetteur) ; le travailleur MT5 du cœur n'expose en liste blanche **aucune** fonction d'ordre. Le plafond de mode reste `OBSERVE` par défaut et ne se relève que par un geste de l'utilisateur. |
| E-06 | Le paquet `MetaTrader5` est **Windows-only**, **un terminal par processus** (module global) et ses appels natifs sont **bloquants**. | (a) Le cœur Python **ne peut pas tourner dans un conteneur Linux** : cible Docker réelle = base + (optionnel) cockpit ; le cœur tourne sur l'hôte Windows. (b) Multi-comptes simultanés ⇒ un travailleur par terminal (processus enfant à liste blanche) ; ça isole aussi un appel natif bloqué du cœur (dead-man, heartbeat). |
| E-07 | La persistance .NET est **perdante par conception** (`DropWrite`, TD-07) et diffuse avant d'écrire. | Le cœur écrit les faits d'exécution **avant d'agir** (commande `PENDING` persistée avant envoi ; base indisponible ⇒ refus, échec fermé) ; seuls les ticks passent par une file bornée. |
| E-08 | `lib/realtime/mt5-translate.ts` et `lib/execution/command-builder.ts` n'ont **aucun appelant hors tests** (code mort) ; `lib/contracts/execution/index.ts` et `lib/accounts/index.ts` sont des barrels inutilisés. | Supprimés sans migration (leur seul contenu utile — idempotence, états — est déjà prévu côté Python). |
| E-09 | La base réelle vit dans un volume Docker **externe** (`trading_operating_system_algorithmique_tradingos-pgdata`, 26 tables vérifiées le 2026-09-25) ; les conteneurs `tradingos-*` sont arrêtés depuis le 2026-09-28 ; `e-commerce-db-1` (autre projet) tourne sur 55432. | **Aucune migration destructive appliquée automatiquement** : `0001_baseline.sql` est compatible avec les tables existantes, les ajouts sont additifs, la suppression d'`envelopes` est un script séparé à lancer à la main. Les tests d'intégration utilisent une base jetable, jamais `tradingos`. |
| E-10 | Aucune référence à Alpaca, SnapTrade, « broker adapter » ni à un fournisseur de données externe dans les fichiers suivis (`git grep`). | Invariants 4 et 5 déjà vrais ; à ne pas dégrader. |
| E-11 | Le cockpit n'appelle `SubmitCommand` **nulle part** (seul `scripts/dev-submit-command.ts` le fait, avec `riskApprovalId: "dev-harness"`) ; le hub ne vérifie ni approbation de risque ni verrou (C-01 du rapport). | La nouvelle `POST /api/execution/commands` exige une `RiskDecision` approuvée et liée au compte ; le harnais de contournement disparaît. |
| E-12 | `.claude/CLAUDE.md` impose des **accords nommés** avant tout élargissement du chemin d'exécution et interdit à l'assistant de déclencher ordre/armement/autonomie ; la règle « aucun identifiant de compte n'est jamais stocké » doit être **réécrite par un ADR avant tout code** de stockage. | L'ADR 0016 amende explicitement cette règle (mission § 14 : `CredentialStore`) ; je ne manipule aucun identifiant réel et ne déclenche aucun ordre. |

## 2. Cartographie : composants, processus, ports

### 2.1 Processus avant / après

| Avant (démarrage manuel de ~10 composants) | Après |
|---|---|
| `terminal64.exe` (MT5 + EA `TradingOsAgent`) | inchangé (hôte Windows) |
| `python mt5_observer.py --symbol …` (WS 8765) | **supprimé** — remplacé par `Mt5Client` dans le cœur |
| `python export_m1_candles.py` (JSONL) | **supprimé** — `MarketDataService` lit MT5 |
| `node tsx scripts/run-setup-detection.ts` (S01) | **supprimé** — `StrategyService` intégré |
| conteneur `tradingos-backend` (.NET : 5080 + 9765) | **supprimé** — cœur Python natif (API `127.0.0.1:8000`, lien EA `127.0.0.1:9765`) |
| conteneur `tradingos-timescaledb` (5433) | conservé (même volume, mêmes données) |
| `next dev -H 127.0.0.1` (3000) | conservé |
| `tsx tools/mcp-server` / `weekly-review` | réécrits en Python (lecture seule) |

### 2.2 Ports

| Port | Avant | Après |
|---|---|---|
| 3000 / 3001 | cockpit (backend / mock) | cockpit (3000) ; 3001 si le mode simulé est conservé |
| 5080 | API + hub SignalR (.NET) | **supprimé** → 8000 (FastAPI : REST + WebSocket `/ws`) |
| 8765 | observateur Python (WS) | **supprimé** |
| 9765 | lien agent MQL5 → Gateway .NET | **conservé** (défaut de l'entrée `InpGatewayPort` de l'EA et préréglages de l'utilisateur) — désormais servi par le cœur Python |
| 5433 | TimescaleDB (hôte) | conservé |
| 55432 | autre projet (`e-commerce-db-1`) | hors périmètre — ne pas toucher |

### 2.3 Variables d'environnement (mesurées dans les fichiers suivis)

| Avant | Après |
|---|---|
| `Cockpit__ListenUrl`, `Cockpit__AgentBindAny`, `Cockpit__AgentPort`, `Cockpit__ObserverUrl`, `Cockpit__DashboardOrigin`, `ConnectionStrings__TradingOs`, `Fred__ApiKey` | `API_HOST`/`API_PORT`, `EA_LINK_HOST`/`EA_LINK_PORT`, `ALLOWED_ORIGINS`, `DATABASE_URL`, `FRED_API_KEY` |
| `TRADINGOS_COCKPIT_TOKEN`, `Cockpit__CockpitToken` | `TRADINGOS_COCKPIT_TOKEN` (inchangé : même `.env`) |
| `TRADINGOS_AGENT_TOKEN`, `Cockpit__AgentToken` | `TRADINGOS_AGENT_TOKEN` (inchangé : l'EA lit `MQL5\Files\tradingos_agent.token`) |
| `TRADINGOS_OBSERVER_TOKEN`, `Cockpit__ObserverToken` | **supprimé** (plus d'observateur) |
| `TRADINGOS_DB`, `TRADINGOS_CANDLES_DIR`, `TRADINGOS_ACCOUNT_ID`, `TRADING_OS_ACCOUNT_ID` | **supprimés** (config unique `DATABASE_URL` ; compte actif en base) |
| `NEXT_PUBLIC_REALTIME_SOURCE`, `NEXT_PUBLIC_BACKEND_HUB_URL`, `NEXT_PUBLIC_MT5_WS_URL`, `NEXT_PUBLIC_MOCK_ACCOUNT_ID` | `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_WS_URL` |
| — | `TRADING_ENV`, `MT5_ENABLED`, `TRADING_MODE` (plafond de mode, défaut `OBSERVE`), `ACTIVE_ACCOUNT_ID`, `LOG_LEVEL` |

### 2.4 Docker

| Service | Avant | Après |
|---|---|---|
| `timescaledb` | `timescale/timescaledb:latest-pg17`, volume et réseau **externes** aux noms hérités | conservé ; volume externe inchangé (les données de l'utilisateur) |
| `backend` (.NET) | construit depuis `backend/` | **supprimé** |
| cœur Python | — | **hors Docker** (MetaTrader5 = Windows) ; image optionnelle sans MT5 pour les tests |
| cockpit | hors Docker (`next dev`) | inchangé |

## 3. Cartographie des dépendances

### 3.1 Dépendances externes (mesurées)

| Pile | Paquet | Utilisé par | Décision |
|---|---|---|---|
| npm | `@microsoft/signalr` | `lib/realtime/signalr-client.ts`, `scripts/dev-submit-command.ts` (2 fichiers) | **supprimé** |
| npm | `@modelcontextprotocol/sdk`, `zod` | `tools/mcp-server/index.ts` seulement | **supprimés** (MCP réécrit en Python) |
| npm | `pg`, `@types/pg`, `tsx` | `scripts/*.ts`, outils | **supprimés** |
| npm | `next`, `react`, `radix-ui`, `lucide-react`, `class-variance-authority`, `cn`, `tailwindcss`, `vitest`, `eslint`… | cockpit | conservés |
| NuGet | `Npgsql 10.0.3`, `Dapper 2.1.79`, `Microsoft.Extensions.Hosting.Abstractions`, `xunit`… | `backend/` | **supprimés avec `backend/`** |
| pip | `MetaTrader5>=5.0.45`, `websockets>=12.0` | observateur | `MetaTrader5` conservé ; `websockets` seulement si utilisé par l'API (FastAPI/Starlette en fournit) |
| pip (nouveaux) | `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `psycopg[binary,pool]`, `httpx`, `keyring`, `pytest`, `pytest-asyncio`, `ruff`, `mypy` | cœur | ajoutés (`python/pyproject.toml`), chacun justifié dans l'architecture |

### 3.2 Graphe d'imports TypeScript (qui utilise quoi, hors tests, entre zones)

| Zone `lib/…` | Importée par | Lecture pour la migration |
|---|---|---|
| `domain` | analysis(23) setup(21) accounts(14) risk(13) compliance(6) realtime(6) contracts(6) app(4)… | tout dépend du domaine : on le porte **d'abord**, les types TS passent en types générés |
| `analysis` | setup(12) app(4) realtime(3) compliance(2) mock scripts mcp weekly | porté avec vecteurs d'or ; `compliance` utilise `analysis/sessions` |
| `risk` | components(5) realtime(4) scripts(2) mock(2) compliance(1) app(1) tools(2) | l'évaluation sort du navigateur |
| `accounts` | components(27) app(5) realtime(5) scripts(2) mock risk | profils/politiques → Python ; vues/hook → frontend |
| `contracts` | realtime(13) mock(3) components(3) accounts cockpit app | remplacés par les types générés |
| `compliance` | components(8) app(4) tools(5) journal account-analysis | calcul côté serveur ; MCP/revue hebdo l'appellent |
| `realtime` | components(24) app(11) accounts(2) account-analysis compliance journal tools/shared | le seul gros chantier frontend (transport + store + provider) |
| `setup` | scripts(2) components app | exécuté par le `StrategyRuntime` |
| `security` | app proxy accounts realtime | conservé |

Modules **sans appelant hors tests** (code mort confirmé par le graphe) : `lib/execution/command-builder.ts`, `lib/realtime/mt5-translate.ts`,
barrels `lib/contracts/execution/index.ts`, `lib/accounts/index.ts`.

## 4. Base de données — disposition des tables (`schema.sql` : 17 tables, 2 hypertables)

| Table | Décision | Détail |
|---|---|---|
| `envelopes` | **MIGRATE** → `events` | Journal d'audit au format enveloppe SignalR (`message_id`, `target`…). Les lignes sont copiées dans `events` (migration additive) ; la table n'est supprimée que par `migrations/manual/` à lancer à la main, après vérification. |
| `candles` (hypertable), `ticks` (hypertable) | **KEEP** | Alimentées par `MarketDataService` ; `ticks.ts` devient l'heure du tick (et non de réception). Aucune rétention ajoutée sans décision. |
| `execution_commands` | **KEEP + étendre** | Colonnes ajoutées : `strategy_id`, `strategy_version`, `risk_decision_id`, `state`, `created_at` (additif). |
| `command_acks`, `execution_reports`, `command_reconciliations`, `position_scans` | **KEEP** | Faits d'exécution du lien EA. |
| `trading_day_anchors`, `position_opens`, `closed_trades`, `trade_captures` | **KEEP** | Journal sans saisie (ADR 0009). |
| `risk_lockouts`, `kill_switch_acks` | **KEEP** | Registre des verrous (source de vérité de « verrouillé maintenant »). |
| `news_releases`, `setup_proposals` | **KEEP** | Cache FRED ; mesure S01. |
| `account_settings` | **MIGRATE** → `account_rule_versions` | Ancien registre par *firme* ; le nouveau est par *compte* (règle anti-tilt conservée). Import ponctuel par CLI, lancé par l'utilisateur. |
| **nouvelles** | `accounts`, `account_rule_versions`, `trade_intents`, `risk_decisions`, `events`, `incidents`, `system_state` | Exigés par la mission (comptes, décisions de risque, intentions, événements, incidents, état système). |

Aucune table n'est spécifique à SignalR ou à .NET *en tant que telle* (vérifié : aucune table de session, de connexion ni de hub) ;
la seule structure « de transport » est le format enveloppe d'`envelopes`.

## 5. API : de l'ancien backend au nouveau cœur

| Ancien (.NET) | Nouveau (FastAPI) |
|---|---|
| `GET /health` | `GET /api/system/health` (+ `/readiness`, `/status`) |
| hub `GetSnapshot` | premier message WebSocket `snapshot` + `GET /api/system/status` |
| hub `PublishEvent` (verrous, ancre) | `POST /api/risk/lockouts`, `POST /api/risk/lockouts/{id}/acknowledge` ; l'ancre est calculée côté serveur |
| hub `SubmitCommand` | `POST /api/execution/commands` (exige une `RiskDecision` approuvée, `accountId` obligatoire) |
| message hub `event` (diffusé à tous) | WebSocket `/ws` (jeton + Origin, abonnement par compte, resynchronisation par `snapshot`) |
| `GET /api/risk/today?accountId` | `GET /api/risk/state?accountId=` |
| `GET /api/calendar/upcoming` | `GET /api/market/calendar` |
| `GET /api/candles` | `GET /api/market/{symbol}/candles` |
| `GET /api/setup-proposals` | `GET /api/strategy/proposals` |
| `GET /api/trades/closed`, `GET /api/journal/trades` | `GET /api/journal/trades` |
| `GET /api/captures/{id}` | `GET /api/journal/captures/{brokerPositionId}` |
| `GET /api/risk/lockouts` | `GET /api/risk/lockouts` |
| `GET /api/execution/divergence` | `GET /api/execution/reconciliation` |
| `GET/POST /api/account-settings` (+ `cancel`) | `GET/POST /api/accounts/{id}/rules` (+ `…/{versionId}/cancel`) |
| `GET /api/audit/recent` | `GET /api/system/events` |
| *(nouveaux, mission § 10)* | `GET/POST /api/accounts`, `…/{id}/connect|disconnect|positions|orders`, `GET/POST /api/active-account`, `GET /api/market/{symbol}[/context]`, `POST /api/risk/evaluate`, `GET /api/risk/decisions`, `GET /api/execution/state`, `GET /api/autonomy/state`, `POST /api/autonomy/arm|disarm|halt` |
| Next `GET /api/cockpit-token` | inchangé |

## 6. Ponts, traducteurs et travailleurs à supprimer — et pourquoi

| Élément | Rôle | Consommateurs | Remplacé par | Quand |
|---|---|---|---|---|
| `Mt5ObserverClient.cs` + `mt5_observer.py` (serveur WS) | pont Python→.NET (8765) | `GatewayBridgeService` | `Mt5Client` en processus | P3 migré → P7 supprimé |
| `Mt5WireTranslator.cs`, `PersistenceMapper.cs`, `lib/contracts/*`, `Contracts/*.cs`, `lib/realtime/mt5-translate.ts` | traducteurs/doubles modèles | Gateway, Host, store | un modèle pydantic → OpenAPI → types TS générés | P6/P7 |
| `GatewayBridgeService.cs` | pont adaptateurs→hub→écrivain | hub, base | dispatcher d'événements + services | P7 |
| `CockpitHub.cs` / SignalR | pont navigateur↔backend | `signalr-client.ts` | REST + WebSocket FastAPI | P6 |
| `GatewayState.cs` | état partagé du pont | hub | état propre à chaque service | P7 |
| `export_m1_candles.py` → `*.jsonl` → `run-setup-detection.ts` | chaîne de 3 workers S01 | `/setups`, MCP | `StrategyService` + `MarketDataService` | P5 |
| `tools/shared/backend-client.ts` | client HTTP TS des outils | MCP, revue hebdo | accès direct aux services Python | P7 |

**Conservé et justifié** : le lien TCP EA↔cœur (`ea_link.py`) — l'EA ne peut parler à Python que par socket ; ce n'est pas un pont mais le canal d'exécution/télémétrie de l'agent.

## 7. Où vont les tests existants

| Famille | Tests | Destination |
|---|---:|---|
| TS `risk` | 51 | `python/tests/unit/domain/risk/` (+ cas EURUSD/GBPUSD/GBPJPY/XAUUSD/BTCUSD du dimensionnement broker-aware, qui n'existaient pas) |
| TS `analysis` | 29 | `…/market/analysis/` avec vecteurs d'or générés depuis le TS |
| TS `setup` | 54 | `…/strategy/s01/` |
| TS `accounts` | 75 | `…/accounts/` (hors `agent-view`, resté en TS) |
| TS `compliance` | 22 | `…/journal/compliance` |
| TS `domain` (machine à états) + `contracts` (idempotence) | 26 | `…/execution/` |
| TS `market` (registre symboles) | 7 | `…/market/symbols` |
| TS `security`, `cockpit`, `account-analysis`, `journal` (chart-scale), `realtime/store` | 60 | restent en Vitest (présentation) |
| TS `execution` (command-builder) + `realtime/mt5-translate` | 3 + 8 | supprimés avec le code mort |
| C# `Mt5AgentServerTests` (430 l.), `Mt5WireI1/I2/TranslatorTests`, `ExecutionTranslationTests` | ~60 | `tests/integration/test_ea_link.py` (vrais sockets loopback) + `tests/unit/test_wire.py` |
| C# `LocalAccessGuardTests`, `RedactingConsoleFormatterTests` | ~20 | `tests/unit/test_api_security.py`, `test_log_redaction.py` |
| C# `AccountSettingsGuard/ValidationTests`, `TradingDayAnchorTests`, `FredReleaseScheduleTests`, `RiskTodayRepositoryTests` | ~25 | `domain/accounts/anti_tilt`, `domain/risk/trading_day`, `infrastructure/news`, `domain/risk` |
| C# `AuditRepositoryIntegrationTests` (passe **à vide** base arrêtée) | 1 | `tests/integration/test_database.py` — **échoue** si la base de test est absente (marqueur explicite, jamais vacuous) |
| C# `Mt5ObserverClientTests`, `PersistenceMapperTests` | ~25 | supprimés avec le pont / le traducteur |
| Python `test_mt5_observer.py` (34) | 34 | `tests/unit/test_observer_logic.py` |

## 8. Garde-fous de suppression (« WHY / WHO USES IT / WHAT REPLACES IT / WHEN »)

Aucun fichier de § 9 n'est supprimé avant que : (1) ses consommateurs aient été migrés, (2) son remplaçant ait des tests qui passent,
(3) une recherche globale ne trouve plus de référence fonctionnelle. Les dates de suppression sont la colonne « Disparaît après ».
Les `UNKNOWN` (deux zones : `lib/realtime/mock-client.ts` et `lib/mock/*`) se tranchent en P6 : l'alternative retenue sera le **mode
simulé du cœur** (`MT5_ENABLED=false`) — un seul chemin de données, pas un second moteur dans le navigateur — sauf obstacle constaté.

## 9. Disposition fichier par fichier (417 fichiers)

### `backend/.dockerignore` — 1 fichiers (DELETE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/.dockerignore` | 2 | **DELETE** | — | Plomberie de build .NET | P7 |

### `backend/TradingOs.slnx` — 1 fichiers (DELETE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/TradingOs.slnx` | 11 | **DELETE** | — | Plomberie de build .NET | P7 |

### `backend/src/TradingOs.Contracts` — 7 fichiers (DELETE 3, MIGRATE 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/src/TradingOs.Contracts/AccountSettings.cs` | 38 | **MIGRATE** | `python/trading_os/domain/accounts/rules_ledger.py` | Registre de réglages | P3 |
| `backend/src/TradingOs.Contracts/Envelope.cs` | 102 | **DELETE** | Modèles pydantic (`domain/*`, `api/schemas`) → OpenAPI → types TS générés | Miroir C# des contrats TS : un seul modèle Python fait foi | P6 |
| `backend/src/TradingOs.Contracts/Execution.cs` | 214 | **MIGRATE** | `python/trading_os/domain/execution/commands.py` | Commande/ACK/rapport d'exécution | P5 |
| `backend/src/TradingOs.Contracts/Mt5AgentStatus.cs` | 84 | **MIGRATE** | `python/trading_os/infrastructure/mt5/ea_link.py` (statut d'agent) | Statut d'identité/permissions/halte de l'agent | P3 |
| `backend/src/TradingOs.Contracts/Mt5Wire.cs` | 124 | **MIGRATE** | `python/trading_os/infrastructure/mt5/wire.py` | Messages du protocole EA (lien TCP conservé) | P3 |
| `backend/src/TradingOs.Contracts/ReadModels.cs` | 161 | **DELETE** | Modèles pydantic (`domain/*`, `api/schemas`) → OpenAPI → types TS générés | Miroir C# des contrats TS : un seul modèle Python fait foi | P6 |
| `backend/src/TradingOs.Contracts/TradingOs.Contracts.csproj` | 9 | **DELETE** | `python/pyproject.toml` | Projet .NET — plus de runtime .NET | P7 |

### `backend/src/TradingOs.Gateway` — 8 fichiers (DELETE 4, MIGRATE 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/src/TradingOs.Gateway/FredCalendarClient.cs` | 48 | **MIGRATE** | `python/trading_os/infrastructure/news/fred.py`, `domain/market/calendar.py` | Calendrier FRED (liste blanche de publications) | P4 |
| `backend/src/TradingOs.Gateway/FredReleaseSchedule.cs` | 57 | **MIGRATE** | `python/trading_os/infrastructure/news/fred.py`, `domain/market/calendar.py` | Calendrier FRED (liste blanche de publications) | P4 |
| `backend/src/TradingOs.Gateway/GatewayState.cs` | 122 | **DELETE** | `python/trading_os/services/*` (état en mémoire des services) | Instantané mono-compte du Gateway | P7 |
| `backend/src/TradingOs.Gateway/Mt5AgentServer.cs` | 595 | **MIGRATE** | `python/trading_os/infrastructure/mt5/ea_link.py` | Serveur TCP du lien EA (registre par compte, jeton, watchdog, ping) — l'EA n'a que ce canal | P3 |
| `backend/src/TradingOs.Gateway/Mt5ObserverClient.cs` | 252 | **DELETE** | `python/trading_os/infrastructure/mt5/client.py` (lecture MT5 directe) | Pont : client WebSocket vers l'observateur Python — A→Pont→B alors que A et B se parlent désormais directement | P7 |
| `backend/src/TradingOs.Gateway/Mt5WireTranslator.cs` | 225 | **DELETE** | `python/trading_os/infrastructure/mt5/wire.py` (analyse du seul lien EA) | Traducteur de protocole wire→enveloppe→DTO : double traduction supprimée | P7 |
| `backend/src/TradingOs.Gateway/TradingDayAnchor.cs` | 21 | **MIGRATE** | `python/trading_os/domain/risk/trading_day.py` | Ancre du jour de trading depuis le décalage serveur MT5 | P4 |
| `backend/src/TradingOs.Gateway/TradingOs.Gateway.csproj` | 13 | **DELETE** | `python/pyproject.toml` | Projet .NET — plus de runtime .NET | P7 |

### `backend/src/TradingOs.Host` — 12 fichiers (DELETE 8, MIGRATE 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/src/TradingOs.Host/AccountSettingsEndpoints.cs` | 186 | **MIGRATE** | `python/trading_os/api/routes/accounts.py` (réglages par compte) | Registre de réglages anti-tilt, désormais par compte | P7 |
| `backend/src/TradingOs.Host/CockpitHub.cs` | 139 | **DELETE** | `python/trading_os/api/websocket/hub.py` + `api/routes/*` | Hub SignalR (GetSnapshot/PublishEvent/SubmitCommand) : pont frontend↔backend ; REST + WebSocket Python directs | P6 |
| `backend/src/TradingOs.Host/Dockerfile` | 24 | **DELETE** | `scripts/start.ps1`, `.env` | Conteneur et configuration du backend .NET | P7 |
| `backend/src/TradingOs.Host/GatewayBridgeService.cs` | 254 | **DELETE** | `python/trading_os/shared/events/dispatcher.py`, `services/journal_service.py`, `services/risk_service.py`, `runtime/scheduler.py` | Pont adaptateurs→hub→écrivain ; ses règles (ancre de jour, faits de capture T05, alerte de verrou T02c) migrent dans les services | P7 |
| `backend/src/TradingOs.Host/LocalAccessGuard.cs` | 152 | **MIGRATE** | `python/trading_os/api/security.py` | Garde jeton + Origin (I0) : même règle, fail-closed, comparaison à temps constant | P7 |
| `backend/src/TradingOs.Host/NewsCalendarService.cs` | 116 | **MIGRATE** | `python/trading_os/services/news_service.py` + `runtime/scheduler.py` | Service FRED toutes les 6 h | P7 |
| `backend/src/TradingOs.Host/Program.cs` | 318 | **DELETE** | `python/trading_os/app/main.py` | Racine de composition ASP.NET : remplacée par la fabrique FastAPI | P7 |
| `backend/src/TradingOs.Host/Properties/launchSettings.json` | 23 | **DELETE** | `scripts/start.ps1`, `.env` | Conteneur et configuration du backend .NET | P7 |
| `backend/src/TradingOs.Host/RedactingConsoleFormatter.cs` | 68 | **MIGRATE** | `python/trading_os/shared/logging/redaction.py` | Aucun secret dans les journaux | P7 |
| `backend/src/TradingOs.Host/TradingOs.Host.csproj` | 14 | **DELETE** | `python/pyproject.toml` | Projet .NET — plus de runtime .NET | P7 |
| `backend/src/TradingOs.Host/appsettings.Development.json` | 8 | **DELETE** | `scripts/start.ps1`, `.env` | Conteneur et configuration du backend .NET | P7 |
| `backend/src/TradingOs.Host/appsettings.json` | 12 | **DELETE** | `scripts/start.ps1`, `.env` | Conteneur et configuration du backend .NET | P7 |

### `backend/src/TradingOs.Persistence` — 16 fichiers (DELETE 2, MIGRATE 13, REWRITE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/src/TradingOs.Persistence/AccountSettingsGuard.cs` | 78 | **MIGRATE** | `python/trading_os/domain/accounts/anti_tilt.py` | Règle anti-tilt (ADR 0007) : un réglage jamais assoupli en séance | P3 |
| `backend/src/TradingOs.Persistence/AccountSettingsRepository.cs` | 209 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/AccountSettingsValidation.cs` | 130 | **MIGRATE** | `python/trading_os/domain/accounts/anti_tilt.py` | Règle anti-tilt (ADR 0007) : un réglage jamais assoupli en séance | P3 |
| `backend/src/TradingOs.Persistence/AuditRepository.cs` | 33 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/CandleRepository.cs` | 39 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/ExecutionDivergenceRepository.cs` | 65 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/JournalRepository.cs` | 66 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/NewsCalendarRepository.cs` | 84 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/PersistenceMapper.cs` | 149 | **DELETE** | Écritures typées explicites dans les dépôts | Traducteur enveloppe→ligne SQL du writer perdant | P7 |
| `backend/src/TradingOs.Persistence/PersistenceWriter.cs` | 280 | **REWRITE** | `python/trading_os/infrastructure/database/event_store.py` | Écrivain perdant (`DropWrite`, TD-07) : faits d'exécution écrits avant d'agir, ticks seuls en file bornée | P5 |
| `backend/src/TradingOs.Persistence/RiskLockoutHistoryRepository.cs` | 42 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/RiskTodayRepository.cs` | 123 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/SetupProposalRepository.cs` | 94 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/TradeCaptureRepository.cs` | 190 | **MIGRATE** | `python/trading_os/infrastructure/database/repositories/` | Dépôts SQL (Dapper → psycopg) | P5 |
| `backend/src/TradingOs.Persistence/TradingOs.Persistence.csproj` | 23 | **DELETE** | `python/pyproject.toml` | Projet .NET — plus de runtime .NET | P7 |
| `backend/src/TradingOs.Persistence/schema.sql` | 306 | **MIGRATE** | `python/trading_os/infrastructure/database/migrations/0001_baseline.sql` | Schéma conservé à l'identique pour les tables reprises (la base existante reste utilisable) puis migrations numérotées | P2 |

### `backend/tests/TradingOs.Gateway.Tests` — 16 fichiers (DELETE 16)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `backend/tests/TradingOs.Gateway.Tests/AccountSettingsGuardTests.cs` | 105 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/AccountSettingsValidationTests.cs` | 87 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/AuditRepositoryIntegrationTests.cs` | 53 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/ExecutionTranslationTests.cs` | 88 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/FredReleaseScheduleTests.cs` | 35 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/LocalAccessGuardTests.cs` | 177 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/Mt5AgentServerTests.cs` | 430 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/Mt5ObserverClientTests.cs` | 194 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/Mt5WireI1Tests.cs` | 91 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/Mt5WireI2Tests.cs` | 83 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/Mt5WireTranslatorTests.cs` | 120 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/PersistenceMapperTests.cs` | 128 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/RedactingConsoleFormatterTests.cs` | 62 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/RiskTodayRepositoryTests.cs` | 68 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/TradingDayAnchorTests.cs` | 49 | **DELETE** | `python/tests/` (tests équivalents) | Tests du backend supprimé ; comportements recouverts côté Python (voir § Tests) | P7 |
| `backend/tests/TradingOs.Gateway.Tests/TradingOs.Gateway.Tests.csproj` | 27 | **DELETE** | `python/pyproject.toml` | Projet de tests .NET | P7 |

### `lib/account-analysis` — 5 fichiers (KEEP 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/account-analysis/breakdowns.test.ts` | 175 | **KEEP** | imports re-pointés vers les types générés | Analyses de présentation sur les trades du journal (pas une gate) | — |
| `lib/account-analysis/breakdowns.ts` | 236 | **KEEP** | imports re-pointés vers les types générés | Analyses de présentation sur les trades du journal (pas une gate) | — |
| `lib/account-analysis/narrative.test.ts` | 117 | **KEEP** | imports re-pointés vers les types générés | Analyses de présentation sur les trades du journal (pas une gate) | — |
| `lib/account-analysis/narrative.ts` | 184 | **KEEP** | imports re-pointés vers les types générés | Analyses de présentation sur les trades du journal (pas une gate) | — |
| `lib/account-analysis/use-account-analysis.ts` | 61 | **KEEP** | imports re-pointés vers les types générés | Analyses de présentation sur les trades du journal (pas une gate) | — |

### `lib/accounts` — 21 fichiers (DELETE 3, MIGRATE 14, REWRITE 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/accounts/active-profile.test.ts` | 159 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/active-profile.ts` | 105 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/agent-view.test.ts` | 138 | **REWRITE** | `lib/accounts/agent-view.ts` sur le schéma de statut d'agent généré | Présentation du statut d'agent (garde côté UI) | P6 |
| `lib/accounts/agent-view.ts` | 159 | **REWRITE** | `lib/accounts/agent-view.ts` sur le schéma de statut d'agent généré | Présentation du statut d'agent (garde côté UI) | P6 |
| `lib/accounts/connection.test.ts` | 29 | **DELETE** | `POST /api/accounts/{id}/connect` | Procédure manuelle observateur/start-live périmée | P6 |
| `lib/accounts/connection.ts` | 50 | **DELETE** | `POST /api/accounts/{id}/connect` | Procédure manuelle observateur/start-live périmée | P6 |
| `lib/accounts/cost-model.test.ts` | 56 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/cost-model.ts` | 28 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/firm.ts` | 46 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/ftmo.ts` | 113 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/index.ts` | 12 | **DELETE** | — | Barrel inutilisé | P6 |
| `lib/accounts/objectives.test.ts` | 143 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/objectives.ts` | 167 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/real.ts` | 51 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/registry.test.ts` | 43 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/registry.ts` | 28 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/settings-api.ts` | 100 | **REWRITE** | `lib/api/accounts.ts` + hook | Appels REST du registre de réglages | P6 |
| `lib/accounts/settings.test.ts` | 273 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/settings.ts` | 452 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/types.ts` | 73 | **MIGRATE** | `python/trading_os/domain/accounts/*` | Profils/politiques par fournisseur, objectifs de challenge, registre de réglages | P3 |
| `lib/accounts/use-account-settings.ts` | 40 | **REWRITE** | `lib/api/accounts.ts` + hook | Appels REST du registre de réglages | P6 |

### `lib/analysis` — 24 fichiers (MIGRATE 24)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/analysis/aggregate.test.ts` | 56 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/aggregate.ts` | 87 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/atr.test.ts` | 33 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/atr.ts` | 49 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/bias.test.ts` | 29 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/bias.ts` | 33 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/config.ts` | 76 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/index.ts` | 17 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/liquidity.test.ts` | 48 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/liquidity.ts` | 120 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/market-context.test.ts` | 48 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/market-context.ts` | 100 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/pd-arrays.test.ts` | 61 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/pd-arrays.ts` | 143 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/scoring.test.ts` | 85 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/scoring.ts` | 80 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/sessions.test.ts` | 22 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/sessions.ts` | 40 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/structure.test.ts` | 49 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/structure.ts` | 87 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/swings.test.ts` | 47 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/swings.ts` | 47 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/test-helpers.ts` | 47 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |
| `lib/analysis/types.ts` | 53 | **MIGRATE** | `python/trading_os/domain/market/analysis/*` | Moteur de contexte ICT/SMC — contexte, pas signal ; portage avec vecteurs d'or générés depuis le TS | P4 |

### `lib/cockpit` — 2 fichiers (KEEP 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/cockpit/verdict.test.ts` | 88 | **KEEP** | imports re-pointés vers les types générés | Verdict de séance : présentation de l'état de risque serveur | — |
| `lib/cockpit/verdict.ts` | 119 | **KEEP** | imports re-pointés vers les types générés | Verdict de séance : présentation de l'état de risque serveur | — |

### `lib/compliance` — 7 fichiers (MIGRATE 5, REWRITE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/compliance/evaluate.test.ts` | 110 | **MIGRATE** | `python/trading_os/domain/journal/compliance.py` | Violations après coup : calculées côté serveur (API journal), plus dans le navigateur/MCP | P5 |
| `lib/compliance/evaluate.ts` | 99 | **MIGRATE** | `python/trading_os/domain/journal/compliance.py` | Violations après coup : calculées côté serveur (API journal), plus dans le navigateur/MCP | P5 |
| `lib/compliance/labels.ts` | 14 | **REWRITE** | `lib/api/journal.ts` + hook | Libellés/hook UI sur l'API journal | P6 |
| `lib/compliance/summarize.ts` | 93 | **MIGRATE** | `python/trading_os/domain/journal/compliance.py` | Violations après coup : calculées côté serveur (API journal), plus dans le navigateur/MCP | P5 |
| `lib/compliance/use-compliance-rate.ts` | 55 | **REWRITE** | `lib/api/journal.ts` + hook | Libellés/hook UI sur l'API journal | P6 |
| `lib/compliance/violations.test.ts` | 117 | **MIGRATE** | `python/trading_os/domain/journal/compliance.py` | Violations après coup : calculées côté serveur (API journal), plus dans le navigateur/MCP | P5 |
| `lib/compliance/violations.ts` | 125 | **MIGRATE** | `python/trading_os/domain/journal/compliance.py` | Violations après coup : calculées côté serveur (API journal), plus dans le navigateur/MCP | P5 |

### `lib/contracts` — 13 fichiers (DELETE 9, MIGRATE 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/contracts/commands.ts` | 75 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/enums.ts` | 31 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/envelope.ts` | 99 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/events.ts` | 340 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/execution/idempotency.test.ts` | 46 | **MIGRATE** | `python/trading_os/domain/execution/idempotency.py`, `reasons.py` | Idempotence par commandId, motifs de refus | P5 |
| `lib/contracts/execution/idempotency.ts` | 41 | **MIGRATE** | `python/trading_os/domain/execution/idempotency.py`, `reasons.py` | Idempotence par commandId, motifs de refus | P5 |
| `lib/contracts/execution/index.ts` | 8 | **DELETE** | — | Barrel inutilisé | P5 |
| `lib/contracts/execution/reject-reason.ts` | 27 | **MIGRATE** | `python/trading_os/domain/execution/idempotency.py`, `reasons.py` | Idempotence par commandId, motifs de refus | P5 |
| `lib/contracts/mt5-wire.ts` | 434 | **MIGRATE** | `python/trading_os/infrastructure/mt5/wire.py` | Protocole du lien EA (seul wire conservé) | P3 |
| `lib/contracts/projections-risk.test.ts` | 56 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/projections.test.ts` | 75 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/projections.ts` | 117 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |
| `lib/contracts/snapshots.ts` | 171 | **DELETE** | Types générés depuis le schéma OpenAPI/WS Python (`lib/api/`, `lib/websocket/`) | Contrats écrits à la main, miroirs de contrats C# : un seul modèle Python fait foi | P6 |

### `lib/domain` — 11 fichiers (DELETE 1, MIGRATE 10)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/domain/account.ts` | 33 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/analysis.ts` | 111 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/execution-state.test.ts` | 135 | **MIGRATE** | `python/trading_os/domain/execution/state.py` | Machine à états de commande (13 états) — aujourd'hui non branchée ; devient le cœur de l'ExecutionEngine | P5 |
| `lib/domain/execution-state.ts` | 176 | **MIGRATE** | `python/trading_os/domain/execution/state.py` | Machine à états de commande (13 états) — aujourd'hui non branchée ; devient le cœur de l'ExecutionEngine | P5 |
| `lib/domain/execution.ts` | 228 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/index.ts` | 15 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/market.ts` | 66 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/primitives.ts` | 50 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/risk.ts` | 91 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/setup.ts` | 61 | **MIGRATE** | `python/trading_os/domain/*` (modèles pydantic) ; types TS générés depuis OpenAPI | Modèle de domaine canonique : passe de TypeScript à Python | P5 |
| `lib/domain/strategy.ts` | 56 | **DELETE** | `python/trading_os/domain/execution/intents.py` (TradeIntent) | `StrategySignal` : aucun producteur | P5 |

### `lib/execution` — 2 fichiers (DELETE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/execution/command-builder.test.ts` | 104 | **DELETE** | `python/trading_os/domain/execution/commands.py` | Code mort (aucun appelant) ; la création de commande devient une méthode de l'ExecutionEngine | P5 |
| `lib/execution/command-builder.ts` | 54 | **DELETE** | `python/trading_os/domain/execution/commands.py` | Code mort (aucun appelant) ; la création de commande devient une méthode de l'ExecutionEngine | P5 |

### `lib/(racine)` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/format.ts` | 43 | **KEEP** | — | Formatage d'affichage | — |

### `lib/journal` — 4 fichiers (KEEP 2, REWRITE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/journal/chart-scale.test.ts` | 43 | **KEEP** | — | Échelle du graphique de capture (présentation pure) | — |
| `lib/journal/chart-scale.ts` | 61 | **KEEP** | — | Échelle du graphique de capture (présentation pure) | — |
| `lib/journal/types.ts` | 25 | **REWRITE** | `lib/api/journal.ts` | Lecture de l'historique du journal | P6 |
| `lib/journal/use-journal-window.ts` | 90 | **REWRITE** | `lib/api/journal.ts` | Lecture de l'historique du journal | P6 |

### `lib/market` — 2 fichiers (MIGRATE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/market/symbols/registry.test.ts` | 52 | **MIGRATE** | `python/trading_os/domain/market/symbols.py` | Registre canonique ↔ symbole courtier | P3 |
| `lib/market/symbols/registry.ts` | 117 | **MIGRATE** | `python/trading_os/domain/market/symbols.py` | Registre canonique ↔ symbole courtier | P3 |

### `lib/mock` — 3 fichiers (UNKNOWN 3)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/mock/candles.ts` | 70 | **UNKNOWN** | idem `mock-client.ts` | Données de démonstration du mock | P6 |
| `lib/mock/envelope.ts` | 29 | **UNKNOWN** | idem `mock-client.ts` | Données de démonstration du mock | P6 |
| `lib/mock/initial-snapshot.ts` | 340 | **UNKNOWN** | idem `mock-client.ts` | Données de démonstration du mock | P6 |

### `lib/realtime` — 10 fichiers (DELETE 3, REWRITE 6, UNKNOWN 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/realtime/backend-url.ts` | 10 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |
| `lib/realtime/client.ts` | 29 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |
| `lib/realtime/mock-client.ts` | 274 | **UNKNOWN** | mode simulé du cœur (`MT5_ENABLED=false`) ou mock minimal | Décision à prendre en P6 : mock navigateur ou flux simulé côté Python | P6 |
| `lib/realtime/mt5-translate.test.ts` | 132 | **DELETE** | — | Traducteur wire→domaine côté navigateur : aucun appelant hors tests (code mort) | P6 |
| `lib/realtime/mt5-translate.ts` | 127 | **DELETE** | — | Traducteur wire→domaine côté navigateur : aucun appelant hors tests (code mort) | P6 |
| `lib/realtime/provider.tsx` | 136 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |
| `lib/realtime/signalr-client.ts` | 699 | **DELETE** | `lib/websocket/cockpit-socket.ts` + `lib/api/*` ; calculs → Python | Client SignalR : transport + ~300 lignes de logique serveur (risque, verrous, contexte, hydratation) | P6 |
| `lib/realtime/store.test.ts` | 133 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |
| `lib/realtime/store.ts` | 366 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |
| `lib/realtime/use-persistence-health.ts` | 77 | **REWRITE** | même rôle sur REST + WebSocket Python | Store du cockpit : réducteurs conservés, transport remplacé | P6 |

### `lib/risk` — 16 fichiers (MIGRATE 16)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/risk/evaluate.test.ts` | 103 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/evaluate.ts` | 96 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/gates.test.ts` | 45 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/gates.ts` | 165 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/index.ts` | 26 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/lockout.test.ts` | 135 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/lockout.ts` | 112 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/news-calendar.test.ts` | 50 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/news-calendar.ts` | 41 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/open-risk.test.ts` | 30 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/open-risk.ts` | 30 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/policy.test.ts` | 41 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/policy.ts` | 47 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/sizing.test.ts` | 99 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/sizing.ts` | 61 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |
| `lib/risk/types.ts` | 45 | **MIGRATE** | `python/trading_os/domain/risk/*` | Risk Engine (9 gates, verrous, sizing) : de TypeScript-navigateur à Python serveur ; tests portés ; facteur XAU en dur remplacé par le dimensionnement broker-aware | P4 |

### `lib/security` — 4 fichiers (KEEP 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/security/cockpit-token.test.ts` | 47 | **KEEP** | — | Jeton du cockpit et garde loopback (même modèle de sécurité locale) | — |
| `lib/security/cockpit-token.ts` | 79 | **KEEP** | — | Jeton du cockpit et garde loopback (même modèle de sécurité locale) | — |
| `lib/security/loopback-host.test.ts` | 29 | **KEEP** | — | Jeton du cockpit et garde loopback (même modèle de sécurité locale) | — |
| `lib/security/loopback-host.ts` | 36 | **KEEP** | — | Jeton du cockpit et garde loopback (même modèle de sécurité locale) | — |

### `lib/setup` — 22 fichiers (MIGRATE 22)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `lib/setup/bias.test.ts` | 42 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/bias.ts` | 29 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/dealing-range.test.ts` | 45 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/dealing-range.ts` | 54 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/displacement.test.ts` | 46 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/displacement.ts` | 72 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/gates.test.ts` | 57 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/gates.ts` | 67 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/liquidity.test.ts` | 80 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/liquidity.ts` | 117 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/poi.test.ts` | 73 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/poi.ts` | 68 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/preconditions.test.ts` | 39 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/preconditions.ts` | 48 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/proposal.test.ts` | 174 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/proposal.ts` | 192 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/reconciliation.test.ts` | 85 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/reconciliation.ts` | 113 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/stop.test.ts` | 23 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/stop.ts` | 31 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/sweep.test.ts` | 43 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |
| `lib/setup/sweep.ts` | 45 | **MIGRATE** | `python/trading_os/domain/strategy/s01/*` | Détecteur S01 : exécuté par le StrategyRuntime Python au lieu du worker Node + JSONL | P5 |

### `app` — 19 fichiers (KEEP 19)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `app/(cockpit)/account/page.tsx` | 98 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/agents/page.tsx` | 28 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/analyse/page.tsx` | 323 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/error.tsx` | 25 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/journal/[brokerPositionId]/page.tsx` | 204 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/journal/page.tsx` | 556 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/layout.tsx` | 6 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/loading.tsx` | 19 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/market-context/page.tsx` | 29 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/page.tsx` | 36 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/positions/page.tsx` | 169 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/preflight/page.tsx` | 131 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/risk/page.tsx` | 33 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/settings/page.tsx` | 79 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/(cockpit)/setups/page.tsx` | 16 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/api/cockpit-token/route.ts` | 15 | **KEEP** | — | Jeton du cockpit (même origine uniquement) | — |
| `app/favicon.ico` | 31 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/globals.css` | 152 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |
| `app/layout.tsx` | 49 | **KEEP** | adaptation des hooks/imports | Pages du cockpit : le visuel ne change pas, la source de données oui | P6 |

### `components/accounts` — 13 fichiers (KEEP 8, REWRITE 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/accounts/code-rules-card.tsx` | 68 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/connection-chain.tsx` | 135 | **REWRITE** | liste de comptes + actions Connect/Disconnect/Set Active/Disable Trading ; formulaire de compte générique | Écran Account : la procédure manuelle et les formulaires par firme disparaissent | P6 |
| `components/accounts/connection-procedure.tsx` | 106 | **REWRITE** | liste de comptes + actions Connect/Disconnect/Set Active/Disable Trading ; formulaire de compte générique | Écran Account : la procédure manuelle et les formulaires par firme disparaissent | P6 |
| `components/accounts/exness-settings-form.tsx` | 184 | **REWRITE** | liste de comptes + actions Connect/Disconnect/Set Active/Disable Trading ; formulaire de compte générique | Écran Account : la procédure manuelle et les formulaires par firme disparaissent | P6 |
| `components/accounts/firm-account-card.tsx` | 181 | **REWRITE** | liste de comptes + actions Connect/Disconnect/Set Active/Disable Trading ; formulaire de compte générique | Écran Account : la procédure manuelle et les formulaires par firme disparaissent | P6 |
| `components/accounts/form-controls.tsx` | 43 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/ftmo-settings-form.tsx` | 220 | **REWRITE** | liste de comptes + actions Connect/Disconnect/Set Active/Disable Trading ; formulaire de compte générique | Écran Account : la procédure manuelle et les formulaires par firme disparaissent | P6 |
| `components/accounts/objectives-card.tsx` | 94 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/pending-change.tsx` | 57 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/rules-card.tsx` | 67 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/settings-guard-banner.tsx` | 61 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/settings-history.tsx` | 71 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/accounts/use-settings-submit.ts` | 47 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `components/analyse` — 2 fichiers (KEEP 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/analyse/breakdown-section.tsx` | 76 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/analyse/stat-tile.tsx` | 30 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `components/cockpit` — 15 fichiers (KEEP 15)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/cockpit/agent-health-panel.tsx` | 83 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/audit-feed.tsx` | 142 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/compliance-card.tsx` | 97 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/discipline-gauge.tsx` | 150 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/economic-calendar.tsx` | 118 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/execution-reports-feed.tsx` | 69 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/kpi-card.tsx` | 87 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/kpi-strip.tsx` | 94 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/lockout-history.tsx` | 121 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/market-context-panel.tsx` | 94 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/positions-table.tsx` | 110 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/reconciliation-view.tsx` | 178 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/risk-status-panel.tsx` | 133 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/session-verdict-banner.tsx` | 123 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/cockpit/setup-proposals-panel.tsx` | 125 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `components/journal` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/journal/trade-chart.tsx` | 141 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `components/shell` — 9 fichiers (KEEP 9)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/shell/account-menu.tsx` | 182 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/app-sidebar.tsx` | 112 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/cockpit-shell.tsx` | 28 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/kill-switch-button.tsx` | 40 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/lockout-ack-banner.tsx` | 51 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/lockout-violation-banner.tsx` | 42 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/nav.ts` | 81 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/news-status.tsx` | 102 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/shell/site-header.tsx` | 42 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `components/ui` — 15 fichiers (KEEP 15)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `components/ui/avatar.tsx` | 108 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/badge.tsx` | 47 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/button.tsx` | 63 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/card.tsx` | 91 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/dropdown-menu.tsx` | 256 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/empty-state.tsx` | 26 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/input.tsx` | 20 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/panel.tsx` | 74 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/progress.tsx` | 36 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/separator.tsx` | 27 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/sheet.tsx` | 142 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/sidebar.tsx` | 727 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/skeleton.tsx` | 13 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/status-pill.tsx` | 42 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |
| `components/ui/tooltip.tsx` | 56 | **KEEP** | adaptation des imports/hooks | Composants d'interface (shadcn/ui, panneaux) | P6 |

### `hooks` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `hooks/use-mobile.ts` | 24 | **KEEP** | — | Hook utilitaire d'interface | — |

### `scripts` — 4 fichiers (DELETE 2, MIGRATE 1, REWRITE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `scripts/dev-submit-command.ts` | 149 | **DELETE** | `POST /api/execution/commands` (garde Risk Engine) | Harnais de développement qui contournait le Risk Engine via le hub | P6 |
| `scripts/import-candles.ts` | 90 | **MIGRATE** | `python/trading_os/cli/import_candles.py` | Import de bougies en base | P5 |
| `scripts/run-setup-detection.ts` | 388 | **DELETE** | `python/trading_os/services/strategy_service.py` | Worker Node S01 lisant des JSONL : remplacé par le StrategyRuntime intégré | P5 |
| `scripts/start-live.ps1` | 309 | **REWRITE** | `scripts/start.ps1` | Démarrage : base, cœur Python, cockpit ; plus d'observateur, de backend .NET ni d'exportateur | P7 |

### `tools/mcp-server` — 2 fichiers (REWRITE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `tools/mcp-server/README.md` | 70 | **REWRITE** | `python/trading_os/mcp/server.py` | Serveur MCP en lecture seule : le TypeScript ne reste que dans le cockpit | P7 |
| `tools/mcp-server/index.ts` | 236 | **REWRITE** | `python/trading_os/mcp/server.py` | Serveur MCP en lecture seule : le TypeScript ne reste que dans le cockpit | P7 |

### `tools/mt5-execution-agent` — 4 fichiers (KEEP 3, REWRITE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `tools/mt5-execution-agent/Include/CommandStore.mqh` | 295 | **KEEP** | — | Journal de commandes idempotent, parseur JSON | — |
| `tools/mt5-execution-agent/Include/JsonLite.mqh` | 156 | **KEEP** | — | Journal de commandes idempotent, parseur JSON | — |
| `tools/mt5-execution-agent/README.md` | 188 | **REWRITE** | même fichier, lien vers le cœur Python | Procédure de vérification de l'agent | P7 |
| `tools/mt5-execution-agent/TradingOsAgent.mq5` | 1458 | **KEEP** | garde-fous conservés ; dead-man ajouté (refus seulement) | Agent local d'exécution et de sécurité : pas de stratégie, pas de risque principal ; `OrderSend` unique et inatteignable inchangé | — |

### `tools/mt5-observer` — 12 fichiers (DELETE 7, MIGRATE 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `tools/mt5-observer/README.md` | 91 | **DELETE** | `python/pyproject.toml` | Dépendances/mode d'emploi de l'observateur | P7 |
| `tools/mt5-observer/analyze_spread.py` | 117 | **DELETE** | `python/trading_os/services/market_data_service.py` ; `AccountService` | Exportateur JSONL (worker intermédiaire), sonde de terminal et mesures jetables dont le cycle de vie est clos | P7 |
| `tools/mt5-observer/export_m1_candles.py` | 185 | **DELETE** | `python/trading_os/services/market_data_service.py` ; `AccountService` | Exportateur JSONL (worker intermédiaire), sonde de terminal et mesures jetables dont le cycle de vie est clos | P7 |
| `tools/mt5-observer/import_history.py` | 92 | **MIGRATE** | `python/trading_os/cli/*` | Outils de mesure/import en lecture seule | P5 |
| `tools/mt5-observer/list_symbols.py` | 62 | **MIGRATE** | `python/trading_os/cli/*` | Outils de mesure/import en lecture seule | P5 |
| `tools/mt5-observer/log_spread.py` | 126 | **DELETE** | `python/trading_os/services/market_data_service.py` ; `AccountService` | Exportateur JSONL (worker intermédiaire), sonde de terminal et mesures jetables dont le cycle de vie est clos | P7 |
| `tools/mt5-observer/mt5_observer.py` | 712 | **MIGRATE** | `python/trading_os/infrastructure/mt5/observer_logic.py` + `client.py` | Logique conservée (identifier≠ticket, tours manqués, P&L net, prix de sortie pondéré) ; serveur WS et gestionnaire de commandes supprimés | P3 |
| `tools/mt5-observer/probe_terminal.py` | 94 | **DELETE** | `python/trading_os/services/market_data_service.py` ; `AccountService` | Exportateur JSONL (worker intermédiaire), sonde de terminal et mesures jetables dont le cycle de vie est clos | P7 |
| `tools/mt5-observer/requirements.txt` | 3 | **DELETE** | `python/pyproject.toml` | Dépendances/mode d'emploi de l'observateur | P7 |
| `tools/mt5-observer/spread_history.py` | 165 | **MIGRATE** | `python/trading_os/cli/*` | Outils de mesure/import en lecture seule | P5 |
| `tools/mt5-observer/test_mt5_observer.py` | 388 | **MIGRATE** | `python/tests/unit/test_observer_logic.py` | 34 tests Python repris | P3 |
| `tools/mt5-observer/test_probe_terminal.py` | 40 | **DELETE** | — | Test de la sonde supprimée | P7 |

### `tools/shared` — 1 fichiers (DELETE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `tools/shared/backend-client.ts` | 64 | **DELETE** | accès direct aux services Python | Client HTTP TS des outils | P7 |

### `tools/weekly-review` — 3 fichiers (REWRITE 3)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `tools/weekly-review/index.ts` | 62 | **REWRITE** | `python/trading_os/cli/weekly_review.py` | Revue hebdomadaire sur les services journal Python | P7 |
| `tools/weekly-review/render.ts` | 81 | **REWRITE** | `python/trading_os/cli/weekly_review.py` | Revue hebdomadaire sur les services journal Python | P7 |
| `tools/weekly-review/stats.ts` | 125 | **REWRITE** | `python/trading_os/cli/weekly_review.py` | Revue hebdomadaire sur les services journal Python | P7 |

### `docs` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `docs/project/trading-operating-system-blueprint.md` | 2553 | **KEEP** | bandeau « baseline pré-migration » | Audit de référence de l'architecture d'avant l'ADR 0016 (historique : aussi dans le commit `e53a4ac`) | — |

### `context` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/README.md` | 44 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/adr` — 16 fichiers (KEEP 16)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/adr/0001-le-process-est-le-produit.md` | 27 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0002-fin-de-la-recherche-d-edge.md` | 26 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0003-stack-et-topologie.md` | 24 | **KEEP** | mention « amendé par 0016 » dans l'index | Stack et topologie : .NET/SignalR remplacés par l'ADR 0016 | — |
| `context/adr/0004-contrats-de-domaine.md` | 17 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0005-ia-en-lecture-seule.md` | 24 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0006-gouvernance-par-outils.md` | 26 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0007-risk-engine-point-de-controle.md` | 24 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0008-journal-de-session.md` | 62 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0009-faits-immuables-rendu-a-la-demande.md` | 49 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0010-execution-agent-mt5.md` | 83 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0011-banc-de-replay.md` | 59 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0012-systeme-de-design-shadcn.md` | 71 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0013-connexion-depuis-l-application.md` | 92 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0014-armement-de-l-agent.md` | 71 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/0015-mode-autonome.md` | 150 | **KEEP** | — | ADR : historique de décisions ; ceux qui décrivent la pile supprimée reçoivent une mention « amendé par 0016 » dans l'index | — |
| `context/adr/README.md` | 40 | **KEEP** | ajout de l'ADR 0016 | Index des ADR | — |

### `context/ai` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/ai/ai_future.md` | 22 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/architecture` — 2 fichiers (REWRITE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/architecture/bounded_contexts.md` | 41 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/architecture/system_overview.md` | 115 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/backend` — 3 fichiers (REWRITE 3)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/backend/backend_bootstrap.md` | 57 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/backend/backend_plan.md` | 49 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/backend/persistence.md` | 67 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/domain` — 5 fichiers (KEEP 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/domain/domain_model_mvp.md` | 61 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/domain/ict_smc_framework.md` | 117 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/domain/risk_ftmo.md` | 50 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/domain/symbols-broker.md` | 50 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/domain/trading_ontology.md` | 53 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/engineering` — 5 fichiers (REWRITE 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/engineering/analysis_engine_mvp.md` | 80 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/engineering/risk_engine_mvp.md` | 63 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/engineering/stack.md` | 68 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/engineering/standards.md` | 35 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/engineering/testing_strategy.md` | 32 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/execution` — 3 fichiers (REWRITE 3)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/execution/protocol.md` | 112 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/execution/safety.md` | 72 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/execution/state-machine.md` | 150 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/frontend` — 6 fichiers (KEEP 6)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/frontend/design_system.md` | 82 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/frontend/final_interface_spec.md` | 272 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/frontend/frontend_plan.md` | 64 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/frontend/information_architecture.md` | 233 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/frontend/visual_reference_analysis.md` | 97 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/frontend/visual_reference_ftmo_journal.md` | 176 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/governance` — 2 fichiers (KEEP 1, REWRITE 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/governance/decision_process.md` | 22 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/governance/quality_gates.md` | 66 | **REWRITE** | gates `pytest`/`ruff`/`mypy` à la place de `dotnet` | Portes de qualité | P7 |

### `context/infrastructure` — 2 fichiers (REWRITE 2)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/infrastructure/infrastructure_plan.md` | 37 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/infrastructure/runbook.md` | 264 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/monitoring` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/monitoring/observability.md` | 39 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/product` — 21 fichiers (KEEP 21)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/product/backlog.md` | 85 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/product/catalogue.md` | 312 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/product/tools/EA-01-detection-s01.md` | 150 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/EA-02-observe-taux-accord.md` | 233 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/EA-03-protocole-execution.md` | 202 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/EA-04-profils-compte.md` | 229 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/EA-05-agent-mql5.md` | 624 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/EA-06-reconciliation.md` | 269 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/README.md` | 35 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/S01-strategie-sweep-aligne.md` | 260 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T01-calculateur-taille.md` | 121 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T02-lockout.md` | 356 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T03-gate-news.md` | 100 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T04-ticket-pretrade.md` | 124 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T05-captures-auto.md` | 241 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T06-journal-auto.md` | 214 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T07-tracker-conformite.md` | 172 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T08-revue-hebdomadaire.md` | 141 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T09-checklist-prevol.md` | 217 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T12-prop-firm-control-center.md` | 343 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |
| `context/product/tools/T15-serveur-mcp.md` | 170 | **KEEP** | journaux d'outil conservés (historique) ; sections d'architecture mises à jour au besoin | Fiches d'outil et leur journal | — |

### `context/project` — 5 fichiers (KEEP 5)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/project/charter.md` | 62 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/project/pivot-2026-09-04.md` | 37 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/project/roadmap.md` | 149 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/project/session-log.md` | 1797 | **KEEP** | entrée de session + instantané | Mémoire de pilotage du projet (ADR 0008) | — |
| `context/project/state.md` | 285 | **KEEP** | entrée de session + instantané | Mémoire de pilotage du projet (ADR 0008) | — |

### `context/realtime` — 7 fichiers (REWRITE 7)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/realtime/README.md` | 19 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/dashboard_realtime_model.md` | 56 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/event_contracts.md` | 159 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/live_prototype.md` | 65 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/mt5_agent_realtime_lifecycle.md` | 103 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/mt5_wire_protocol.md` | 174 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |
| `context/realtime/websocket_first_architecture.md` | 160 | **REWRITE** | sections qui décrivent .NET/SignalR/observateur réécrites pour le cœur Python | Documentation vivante de la pile supprimée | P7 |

### `context/security` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/security/security_principles.md` | 64 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/templates` — 6 fichiers (KEEP 6)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/templates/README.md` | 34 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/templates/reference-dashboard-overview.png` | 2681 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/templates/reference-trade-replay.webp` | 726 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/templates/reference-trades-table.png` | 1712 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/templates/tdd-template.md` | 28 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |
| `context/templates/tradezella-dashboard.webp` | 679 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `context/workflows` — 1 fichiers (KEEP 1)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `context/workflows/development_workflow.md` | 35 | **KEEP** | — | Cerveau du projet : domaine, produit, frontend, sécurité, gouvernance | — |

### `.claude` — 4 fichiers (KEEP 4)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `.claude/CLAUDE.md` | 48 | **KEEP** | mise à jour des références d'architecture | Instructions et commandes de workflow | — |
| `.claude/commands/outil-close.md` | 17 | **KEEP** | mise à jour des références d'architecture | Instructions et commandes de workflow | — |
| `.claude/commands/outil-start.md` | 19 | **KEEP** | mise à jour des références d'architecture | Instructions et commandes de workflow | — |
| `.claude/context/README.md` | 7 | **KEEP** | mise à jour des références d'architecture | Instructions et commandes de workflow | — |

### `(racine du dépôt)` — 15 fichiers (KEEP 9, REWRITE 6)

| Fichier | Lignes | Décision | Cible / remplacé par | Pourquoi | Disparaît après |
|---|---:|---|---|---|---|
| `.env.example` | 23 | **REWRITE** | variables du cœur Python | Modèle de configuration | P2 |
| `.gitignore` | 67 | **REWRITE** | ajout `python/.venv`, caches Python ; retrait des artefacts .NET | Fichiers ignorés | P7 |
| `AGENTS.md` | 17 | **KEEP** | — | Instructions de l'assistant | — |
| `CLAUDE.md` | 2 | **KEEP** | — | Instructions de l'assistant | — |
| `README.md` | 62 | **REWRITE** | démarrage de la nouvelle architecture | Présentation du dépôt | P7 |
| `components.json` | 21 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `docker-compose.yml` | 97 | **REWRITE** | TimescaleDB seule (+ cockpit optionnel) | Le cœur Python tourne sur l'hôte Windows (le paquet MetaTrader5 est Windows-only) | P7 |
| `eslint.config.mjs` | 18 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `next.config.ts` | 14 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `package-lock.json` | 11146 | **REWRITE** | régénéré | Verrou des dépendances npm | P7 |
| `package.json` | 41 | **REWRITE** | retrait de @microsoft/signalr, @modelcontextprotocol/sdk, zod, tsx, pg | Dépendances npm | P7 |
| `postcss.config.mjs` | 7 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `proxy.ts` | 15 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `tsconfig.json` | 34 | **KEEP** | — | Configuration Next.js / outillage frontend | — |
| `vitest.config.ts` | 15 | **KEEP** | — | Configuration Next.js / outillage frontend | — |


## 10. Suivi d'avancement (à mettre à jour à chaque phase — c'est le point de reprise)

État au **2026-10-08**. La migration est **suspendue depuis le 2026-10-08 à 05:10** pour la refonte
visuelle du cockpit (ADR 0017) ; rien n'est déployé. L'ancienne pile (.NET, SignalR, observer Python)
reste la seule qui existe en service, et elle est **éteinte** au 2026-10-08 (aucun conteneur du
projet depuis le 2026-09-28, MT5 fermé). Branche `refactor/python-native-architecture`, sommet
`66d4274`. Dernière
vérification, le 2026-10-08 depuis un worktree temporaire : **463 tests verts**, `ruff` propre,
`mypy --strict` propre sur 92 fichiers.

| Phase | État | Preuve |
|---|---|---|
| 0 — audit, migration-map | ✅ fait | ce document (`dcf6b0b`) |
| 1 — architecture cible + ADR | ✅ fait | `docs/architecture/python-native-architecture.md`, `context/adr/0016-…` (`dcf6b0b`) |
| 2 — cœur Python | 🔶 en cours | noyau partagé (identifiants, temps, erreurs, journalisation qui masque les secrets, événements), configuration, base de données (migrations numérotées, dépôts SQL) : `1d362a3`, `8c9910c`. **Reste** : `runtime/` (superviseur, battement, ordonnanceur, moteur — le paquet est vide), application FastAPI + WebSocket + sécurité + OpenAPI, CLI et MCP |
| 3 — comptes + MT5 | 🔶 en cours | domaine des comptes, lecteur MT5 en processus fils à liste blanche (lecture seule), lien EA, simulateur, services comptes / données de marché / positions : `48df6c0`, `751c580`, `89affb7`. **Reste** : service de réconciliation, actualités (FRED) |
| 4 — risque | 🔶 en cours | `domain/risk` et `services/risk` (jauges, verrous, dimensionnement depuis les spécifications du courtier, exposition et corrélation, politiques par compte) : `1d362a3`, `89affb7`. **Reste** : portage de `lib/analysis` (24 fichiers, contexte de marché) |
| 5 — exécution | 🔶 en cours | moteur d'exécution centralisé, passerelles d'ordres, cycle de vie des commandes ; l'ordre part toujours par l'EA, jamais par `order_send` depuis Python : `48df6c0`, `66d4274`. **Reste** : service d'autonomie, journal, portage de `lib/setup` (S01, 22 fichiers) et de `lib/compliance` |
| 6 — frontend | ⏳ pas commencé | à faire : `lib/api`, `lib/websocket`, retrait de SignalR. La refonte visuelle (ADR 0017) ne touche à rien de cela |
| 7 — suppression radicale | ⏳ pas commencé | — |
| EA `DEAD_MAN` | ⏳ pas commencé | refus fondé sur le ping ; vérification de compilation seulement (MetaEditor en ligne de commande) |
| Validation finale + rapport | ⏳ | `docs/architecture/python-native-migration-report.md` |

**Reprendre ici** — dans l'ordre : service de réconciliation → service d'autonomie → actualités (FRED)
→ journal → `runtime/` (superviseur, battement, ordonnanceur, moteur) → application FastAPI + WebSocket
+ sécurité + OpenAPI → portage de `lib/analysis` puis de `lib/setup` → CLI / MCP → frontend (phase 6)
→ EA `DEAD_MAN` → suppressions (phase 7) → documents vivants et rapport final.

- Tests : depuis `04_code/python`, `.venv\Scripts\python.exe -m pytest -q` (≈ 2 min 35 s : un cluster
  PostgreSQL jetable lancé depuis les binaires PG 18 installés, jamais la base `tradingos`), puis
  `-m ruff check .` et `-m mypy trading_os`.
- La branche `feat/ui-redesign-exponentvalue` (refonte visuelle, ADR 0017) est coupée de ce même
  sommet : l'y fusionner avant la phase 6, qui touche aussi `components/` et `lib/`. Pour reprendre la
  migration sans toucher à une arborescence où la refonte est en cours : `git worktree add` sur la
  branche de migration, et l'interpréteur du venv existant (le répertoire courant l'emporte sur le
  finder éditable).

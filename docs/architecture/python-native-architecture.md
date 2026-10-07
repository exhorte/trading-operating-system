# Architecture cible — Trading OS Python-native

> Phase 1 de la migration. Spécification contre laquelle le cœur Python est implémenté et testé.
> Décision : `context/adr/0016-architecture-python-native.md`. État mesuré de départ et dispositions fichier par
> fichier : `docs/architecture/migration-map.md`. Ce document décrit la **cible** ; ce qui n'est pas encore
> livré est signalé dans le rapport de migration, jamais présenté comme fait ici.

## 1. Principes

SIMPLE · DIRECT · PYTHON-NATIVE · MODULAIRE · TESTABLE · OBSERVABLE · SAFE · EXPLICABLE.
Moins de couches, moins de traductions, moins de processus, moins de protocoles ; plus de contrôle, de visibilité,
de fiabilité. Chaque abstraction a une justification écrite (§ 14) ; une fonction suffit quand elle suffit.

```
                         NEXT.JS COCKPIT  (lib/api, lib/websocket)
                                │  REST + WebSocket (127.0.0.1:8000)
                                ▼
                   ┌─────────────────────────────┐        un seul processus Python
                   │  FastAPI  (api/)            │
                   ├─────────────────────────────┤
                   │  services/                  │  account · market_data · strategy · risk ·
                   │  runtime/                   │  execution · position · reconciliation ·
                   │                             │  journal · autonomy · news
                   │  domain/  (pur, sans E/S)   │  supervisor · heartbeat · scheduler
                   ├─────────────────────────────┤
                   │  infrastructure/            │  mt5 · database · news · security · filesystem
                   └───────┬──────────────┬──────┘
        processus enfant   │              │  TCP 127.0.0.1:9765 (NDJSON, jeton)
        lecture seule      ▼              ▼
              API MetaTrader5 ─▶ MT5 ◀─ EA TradingOsAgent (exécution locale, garde-fou) ─▶ courtier
                                        (Exness | FTMO)
                                 PostgreSQL/TimescaleDB (Docker, volume existant)
```

## 2. Composants et responsabilités

Arborescence (`python/trading_os/`) — celle de la mission, ajustée par l'audit (ajouts en gras) :

| Paquet | Contient | Règle |
|---|---|---|
| `app/` | `main.py` (fabrique FastAPI + point d'entrée), `config.py` (pydantic-settings), `dependencies.py` (conteneur), `lifecycle.py` | seul endroit qui assemble |
| `api/routes/`, `api/websocket/`, `api/schemas/`, **`api/security.py`** | REST, WebSocket, schémas propres à l'API, garde jeton+Origin | aucune règle métier |
| `domain/<accounts,market,strategy,risk,execution,positions,autonomy,journal,system>/` | modèles pydantic, règles pures, machines à états | **aucune E/S, aucun import d'infrastructure** (test d'architecture) |
| `services/` | un service par capacité (liste ci-dessus) | orchestre domaine + infrastructure ; état en mémoire propre |
| `infrastructure/mt5/` | `client.py`, `transport.py`, `worker.py`, `fake.py`, `observer_logic.py`, `wire.py`, `ea_link.py` | **seul** endroit qui parle à MT5 |
| `infrastructure/database/` | pool, migrations SQL, dépôts, `event_store.py` | seul endroit qui écrit en SQL |
| `infrastructure/news/`, **`infrastructure/security/`**, `infrastructure/filesystem/` | FRED ; `CredentialStore` ; lecture `.env`/fichiers jeton | — |
| `runtime/` | `engine.py` (cycle de vie), `supervisor.py`, `heartbeat.py`, `scheduler.py` | — |
| `shared/` | `events/` (modèles + dispatcher), `errors/`, `ids/`, `logging/` (masquage) | — |
| **`cli/`**, **`mcp/`** | `serve`, `db migrate`, `import-candles`, `spread-history`, `list-symbols`, `weekly-review`, serveur MCP en lecture seule | outils, pas de logique |

Chaque service est un module de ce processus (pas de port, pas de file externe). Un **dispatcher d'événements interne**
(`shared/events/dispatcher.py`, ≈ 80 lignes : `subscribe(type, handler)` / `publish(event)` asynchrone) relie les
services ; trois abonnés génériques seulement : persistance (`event_store`), diffusion WebSocket, journalisation.

### Responsabilités par service

| Service | Responsabilité | Émet |
|---|---|---|
| `AccountService` | comptes (CRUD sans secret), connexion/déconnexion/reconnexion, **compte actif** unique, `trading_enabled`, identifiants via `CredentialStore`, refus de bascule (positions/ordres/session armée) | `AccountConnected/Disconnected`, `ActiveAccountChanged` |
| `MarketDataService` | ticks (≈ 1 Hz), bougies, spécifications de symbole, spread, session, calendrier ; **seul fournisseur de données de marché** | `MarketTickReceived`, `CandleClosed` |
| `PositionService` | compte, positions, ordres (toutes les 2 s) ; détection ouverture/clôture (identifier ≠ ticket, tours manqués) | `PositionOpened/Modified/Closed`, `AccountSnapshotUpdated` |
| `StrategyService` | exécute les stratégies enregistrées (S01) à la clôture de bougie ; produit des `TradeIntent` ; **ne décide ni du risque ni de l'ordre** | `StrategyEvaluationStarted/Completed`, `TradeIntentCreated`, `TradeRejected` |
| `RiskService` | état de risque par compte, registre des verrous, `can_i_trade`, `RiskDecision` (persistée) ; **point de contrôle unique** | `RiskEvaluationStarted`, `RiskApproved/Rejected`, `RiskStateUpdated`, `Lockout*` |
| `ExecutionService` (moteur) | commande → validation → décision de risque → persistance `PENDING` → envoi → ack → résultat ; idempotence ; modes OBSERVE/PAPER/CONFIRM/ARMED/AUTONOMOUS | `ExecutionCommandCreated/Sent`, `ExecutionAcknowledged/Failed/Unknown`, `ExecutionReported` |
| `ReconciliationService` | compare l'état du Trading OS à celui de MT5 (pur : `domain/positions/reconciliation.py`) ; résout les `UNKNOWN` | `ReconciliationStarted/Mismatch/Completed` |
| `JournalService` | reconstitue chaque trade (Intent → … → Outcome), faits de capture T05 (immuables), conformité, requêtes d'analyse | — |
| `AutonomyService` | échelle d'états, bail côté serveur, readiness, arrêt, homme mort | `AutonomyArmed/Disarmed/Halted` |
| `NewsService` | calendrier FRED (cache en base, échec fermé) | `MarketCalendarUpdated` |
| `Supervisor` (runtime) | évalue la santé de tout le reste, ouvre/ferme des incidents, déclenche SAFE/DISARM/HALT/RECONNECT/RECONCILE | `SystemHealthChanged`, `HeartbeatMissed`, `IncidentOpened/Resolved` |

## 3. Flux de données

```
MT5 ─(processus lecture)─▶ MarketDataService ─▶ CandleClosed ─▶ StrategyService ─▶ TradeIntent
                      └─▶ PositionService ─▶ PositionOpened/Closed ─▶ JournalService (captures, T05)
                                                                   └▶ RiskService (verrou T02c, trades du jour)
TradeIntent ─▶ RiskService.evaluate ─▶ RiskDecision (persistée)
              ├─ rejetée ─▶ TradeRejected (journal)
              └─ approuvée ─▶ ExecutionService ─▶ (mode) ─▶ voir § 4
Tout événement ─▶ dispatcher ─▶ { event_store (SQL) , WebSocket (cockpit) , logs }
```

## 4. Flux d'exécution

```
ExecutionRequest (accountId obligatoire, commandId = clé d'idempotence)
   │ validation structurelle (compte = compte réellement connecté ? symbole ? volume ? SL obligatoire ? expiration ?)
   │ idempotence : commandId connu → renvoie l'existant (409 si charge utile différente)
   │ RiskDecision approuvée, liée au même compte (sinon refus RISK_NOT_APPROVED)  ◀── point de contrôle unique
   ▼
ExecutionCommand (PENDING, persistée AVANT tout envoi ; base indisponible ⇒ refus)
   ▼
mode effectif = min(plafond TRADING_MODE, plafond du compte, état d'autonomie)
   OBSERVE  → enregistrée « observée », rien n'est envoyé nulle part
   PAPER    → PaperBroker (remplissage simulé au tick, en processus) ; jamais MT5
   CONFIRM  → attend `POST …/confirm` d'un humain, puis envoi
   ARMED    → envoi automatique tant que le bail est valide (renouvelé par le cœur, expire → CONFIRM)
   AUTONOMOUS → envoi automatique si readiness verte en continu
   ▼ envoi (lien EA, NDJSON)  →  SENT
EA : idempotence disque → halte → identité → compte → expiration → barrières locales → ACK
   ACK ACCEPTED → ACKNOWLEDGED ; REJECTED → REJECTED ; EXPIRED → EXPIRED ; DUPLICATE → no-op
   rapport FILLED/PARTIALLY_FILLED → EXECUTED ; SIMULATED (EA compilé OBSERVE) → SIMULATED ; FAILED → FAILED
   retours ambigus (10011 erreur de traitement, 10012 délai, 10031 pas de connexion) → UNKNOWN (jamais FAILED)
   silence/perte de lien après SENT → UNKNOWN → RECONCILING (historique MT5 : magic + commentaire) → RECONCILED
```

États persistés de la commande (les huit de la mission + sorties terminales héritées de l'ADR 0010) :
`PENDING → SENT → ACKNOWLEDGED → EXECUTED → RECONCILED` ; `UNKNOWN → RECONCILING → RECONCILED` ;
terminaux : `FAILED`, `REJECTED`, `EXPIRED`, `CANCELLED`, `SIMULATED`. La machine à 13 états de l'audit est ramenée à ces
états : `RISK_APPROVED` disparaît (la décision précède la commande) ; `RECEIVED/VALIDATING/EXECUTING` sont internes à
l'agent (non observables) et fusionnés dans `ACKNOWLEDGED`. Toute transition passe par une table (`domain/execution/state.py`) ;
une transition illégale lève une erreur — jamais d'écriture d'état libre. Types de commande : `OPEN, MODIFY, CLOSE,
PARTIAL_CLOSE, CANCEL` ; seuls ceux dont l'agent annonce la capacité dans son `hello` sont envoyés (aujourd'hui `OPEN`
seulement : les autres sont refusés à la soumission avec `AGENT_CAPABILITY_MISSING`, pas envoyés dans le vide).

## 5. Flux de compte

`Account` : `id, name, provider (EXNESS|FTMO), platform (MT5), account_type, login, server, currency, environment
(DEMO|SIMULATED|LIVE), terminal_path?, status, trading_enabled, risk_profile, trading_rules, execution_profile`. Aucun secret.

Les différences FTMO/Exness vivent dans des **profils** (`domain/accounts/profiles.py`) : un registre
`provider → fabrique de politique` construit `AccountPolicy = {RiskProfile, TradingRules, NewsPolicy, DrawdownPolicy,
PositionLimits, ExecutionLimits}`. Aucun `if provider == …` ailleurs (test d'architecture : grep dans `domain/risk` et `services`).

`connect(account_id)` : refuse si un autre compte du même terminal est connecté et non déconnectable (positions ouvertes,
ordres en attente, session armée — ADR 0013) → lance le processus de lecture du terminal → `initialize(path)` →
(identifiants du `CredentialStore` ou fournis, ou terminal déjà connecté) `login` → **vérifie** `login` et `server` réels
contre le compte (`wrong_server`, `wrong_credentials`, `account_mismatch`, sans jamais citer un secret) → `CONNECTED`.
`active_account` : exactement un, persisté (`system_state`) ; seul lui reçoit des commandes **automatiques** ; une
commande humaine vise un `accountId` explicite qui doit être connecté et égal au compte réel du terminal.

## 6. Flux de risque

Pipeline unique : `TradeIntent → RiskService → RiskDecision → ExecutionService`. Jamais `Strategy → Execution`.

`can_i_trade(account, intent?) → {decision: ALLOWED|DENIED, reasons[], checks[]}` — 17 contrôles explicables :
compte sain · courtier connecté · MT5 sain · règles du compte · budget de perte du jour · drawdown total · risque ouvert ·
risque corrélé · actualité · spread (porte de coût S01, pas de plafond fixe : ADR 0015) · session · symbole autorisé ·
limite de positions · nombre de trades · verrou/kill switch · état d'autonomie · santé EA/MT5. Sortie type :
`{"decision":"DENIED","reasons":["daily_risk_budget_exceeded","news_restriction","correlated_exposure_too_high"]}`.

**Dimensionnement broker-aware** (`domain/risk/sizing.py`) — jamais `risque / distance_du_stop` seul :

```
perte_par_lot = ((distance_stop + spread) / tick_size) × tick_value_loss + commission_aller_retour   [devise du compte]
volume_brut   = budget_de_risque / perte_par_lot
volume        = arrondi_inférieur_au_pas(volume_brut) borné à [volume_min, volume_max]
si volume_brut < volume_min → refus « min_volume_exceeds_risk » (on n'arrondit JAMAIS au-dessus du budget)
```
`tick_value_loss` est exprimé par MT5 en devise du compte (conversion faite par le courtier) ; données manquantes ou
nulles → `SizingError` (refus), pas de valeur par défaut. Tests : XAUUSD, EURUSD, GBPUSD, GBPJPY, BTCUSD. Le facteur « or ×100 »
codé en dur de `lib/risk/sizing.ts` et `open-risk.ts` disparaît.

Verrous : registre persistant source de vérité de « verrouillé maintenant » ; perte du jour/drawdown/trades levés **par
accusé** (T02c, amendement de l'ADR 0015) ; pause sur pertes consécutives temporisée (30 min) ; kill switch.
Politiques par compte (FTMO ≠ Exness) ; valeurs validées par l'utilisateur dans le journal de session (0,1 %, 5 %, 10 %, 4
trades, 2 positions…) vivent dans la **configuration du compte**, jamais en dur ; sans elles l'autonomie refuse de démarrer.

## 7. Flux d'autonomie

Échelle : `OFF → OBSERVE → PAPER → CONFIRM → ARMED → AUTONOMOUS`, plus `HALTED`. Une marche à la fois vers le haut, descente
libre ; jamais au-dessus du plafond effectif `min(TRADING_MODE, execution_profile.max_mode du compte)` (défaut **OBSERVE**).

| État | Effet |
|---|---|
| OFF | sous-système de trading inactif (télémétrie seule) |
| OBSERVE | stratégies évaluées, intentions et décisions de risque enregistrées, **rien n'est envoyé** |
| PAPER | intentions approuvées exécutées sur le broker simulé |
| CONFIRM | intentions approuvées en attente de confirmation humaine, puis envoi à l'EA |
| ARMED | envoi automatique **sous bail** (30 min par défaut, renouvelable par l'humain) ; l'expiration retombe en CONFIRM |
| AUTONOMOUS | envoi automatique sans bail ; exige `READY` à l'entrée **et en continu** |
| HALTED | tout est coupé ; `control.halt` envoyé à l'agent ; sortie seulement par accusé humain vers OFF |

Toute erreur critique (supervisor) : `AUTONOMOUS|ARMED → HALTED`. **Readiness** (`AUTONOMY = BLOCKED` dès qu'un contrôle
critique échoue) : cœur sain · base saine · MT5 connecté et frais · bon compte connecté · symbole disponible · Risk Engine
sain · dimensionnement valide · réconciliation saine · kill switch disponible (EA joignable, capacité `halt`) · heartbeat
actif · superviseur sain · moteur d'exécution sain · stratégie valide · gestion de position valide · aucun incident critique ·
limites du compte configurées. *Aujourd'hui `position_management_valid` échoue (aucune sortie S01 : dette TD-09) et le
capital de référence n'est pas fixé : AUTONOMOUS est bloqué, c'est voulu.*

**Homme mort.** Le cœur envoie `control.ping` toutes les 5 s à l'agent et publie `system.heartbeat` au cockpit. L'EA refuse
tout nouvel ordre (`DEAD_MAN`) quand aucun ping n'est arrivé depuis `InpDeadManSeconds` (30 s) — un ordre reçu n'est pas une
preuve de vie, seul le ping l'est ; les stops chez le courtier restent. Côté cœur, un heartbeat de l'agent périmé lève
`HeartbeatMissed` et fait échouer la readiness.

## 8. Intégration MT5

**Lecture** — `Mt5Client` (async) pilote un **processus enfant** par terminal (`worker.py`, JSON par ligne sur stdio) qui
importe `MetaTrader5` et n'exécute que la **liste blanche** : `initialize, login, shutdown, last_error, account_info,
terminal_info, symbol_info, symbol_info_tick, symbol_select, symbols_get, positions_get, orders_get, history_deals_get,
history_orders_get, copy_rates_from_pos, copy_rates_range, copy_ticks_range, order_calc_profit, order_calc_margin`.
`order_send`, `order_check` et tout appel de modification/clôture n'y figurent pas : un test lit la liste et échoue si un
nom d'ordre apparaît (équivalent du « grep ce fichier : il n'y en a pas » de l'observateur historique). Raisons : module
global au processus, appels bloquants, isolation des plantages natifs. `FakeMt5` implémente la même surface pour les tests
et le mode simulé (`MT5_ENABLED=false`).

**Exécution** — lien TCP NDJSON avec l'EA (`ea_link.py`) : serveur asyncio sur `127.0.0.1:9765`, registre par compte
(refus d'un second `hello` tant que l'agent existant est vivant, silencieux > 30 s = mort), jeton comparé en temps constant
(fail-closed), watchdog, `control.ping` 5 s, `control.halt`. Le protocole (`wire.py`) reprend `lib/contracts/mt5-wire.ts` :
messages de l'agent `agent.hello/heartbeat, execution.ack/report/reconciled/position.scan` ; du cœur `execution.order,
control.ping, control.halt`. **L'EA reste inchangé sur le fil** ; seul ajout : refus `DEAD_MAN`.

**EA** — connexion, heartbeat, exécution locale, accusés, télémétrie, réconciliation, sécurité locale, arrêt d'urgence. Aucune
stratégie, aucun Risk Engine principal, aucun journal métier, aucune IA. Orienté événements : il réagit à une commande, publie
un heartbeat/scan toutes les 5 s, ne modifie rien « à chaque tick ». Plafond de mode compilé `OBSERVE` (inchangé).

## 9. Intégration frontend

REST (JSON camelCase, schémas = modèles pydantic → OpenAPI → `lib/api/schema.ts` généré) + un WebSocket `/ws`.
Authentification : jeton du cockpit (`/api/cockpit-token`, même origine) en `Authorization: Bearer` (REST) ou
`?access_token=` (WS) **et** Origin autorisée ; lectures comprises (hors `/api/system/health`). Contrat WebSocket (« gates temps réel ») :

| Sujet | Règle |
|---|---|
| Trame serveur | `{"type","id","occurredAt","accountId","correlationId","payload"}` ; première trame `system.snapshot` |
| Portée | tous les comptes par défaut ; `{"type":"subscribe","accountIds":[…]}` restreint (événements globaux toujours envoyés) |
| États de connexion client | `connecting · connected · reconnecting · stale · disconnected` (déjà ceux du store) |
| Donnée périmée | pas de `system.heartbeat` (2 s) depuis 8 s ⇒ `stale` ; aucune décision n'est prise sur donnée périmée |
| Reconnexion | automatique (backoff 1→10 s) ; nouveau `system.snapshot` à chaque reconnexion ; `{"type":"resync"}` à la demande |
| Contre-pression | file bornée par client (500) ; en cas de débordement les **ticks** les plus anciens sont jetés, jamais un événement de cycle de vie ; au-delà, fermeture 1013 → resynchronisation |
| Observabilité | `GET /api/system/health` : clients WS, compteur de trames, file, événements perdus |

Le navigateur n'évalue plus aucune règle : il affiche `risk.state.updated`, `analysis.market_context.updated`, etc. Il ne
publie plus de faits de verrou (`PublishEvent`) : `POST /api/risk/lockouts` (kill switch) et `…/acknowledge`.

## 10. Base de données

PostgreSQL/TimescaleDB conservées (pertinence confirmée : séries de ticks/bougies en hypertables, volume et données réels
de l'utilisateur). `psycopg 3` asynchrone, SQL explicite, **migrations numérotées** (`infrastructure/database/migrations/NNNN_*.sql`,
table `schema_migrations`, checksum, exécution transactionnelle, `python -m trading_os db migrate`) en remplacement du
`schema.sql` rejoué à chaque démarrage. `0001_baseline` = schéma actuel à l'identique (la base existante est reconnue sans
rien modifier) ; `0002+` ajoutent `accounts`, `account_rule_versions`, `trade_intents`, `risk_decisions`, `events`,
`incidents`, `system_state` et des colonnes à `execution_commands` (additif). Garanties :

| Donnée | Garantie |
|---|---|
| commandes, décisions de risque, verrous, états d'autonomie | écrites **avant d'agir**, dans la même transaction que le changement d'état ; échec ⇒ refus |
| événements du journal d'audit (`events`) | écrits de façon durable ; **un seul** traitement par événement (id unique, `ON CONFLICT DO NOTHING`) |
| ticks | file bornée + écriture par lots ; perte tolérée et **comptée** (`dropped` dans la santé) ; horodatage = heure du tick |
| faits de capture T05 | immuables (une ligne par position et type, jamais modifiée) |

Aucune table ne contient de secret. Aucune migration destructive n'est appliquée automatiquement (`migrations/manual/`).

## 11. Sécurité

| Sujet | Mesure |
|---|---|
| Surface | tout lié à `127.0.0.1` ; jeton cockpit + Origin ; comparaisons en temps constant ; échec fermé si le jeton n'est pas configuré |
| Identifiants MT5 | jamais dans le frontend, les journaux, la base, les événements, les exceptions ; `SecretStr` partout ; `CredentialStore` nul par défaut, coffre Windows en opt-in ; endpoint d'écriture seule |
| Journaux | filtre de masquage (jetons, mots de passe) ; test avec « sentinelles » : un faux mot de passe est absent des journaux, réponses, événements, exceptions, tables |
| EA | jeton d'agent (`MQL5\Files\tradingos_agent.token`) ; identité (`ACCOUNT_LOGIN`) ; magic > 0 ; instance unique ; plafond de mode compilé |
| Assistant de développement | ne déclenche jamais ordre/armement/autonomie ; ne voit jamais de mot de passe réel (`.claude/CLAUDE.md`) |
| Limite assumée | un logiciel malveillant sous le compte Windows de l'utilisateur lit `.env`, la mémoire et les fichiers MT5 : hors modèle de menace (ADR 0013) |

## 12. Gestion des pannes — le Supervisor

Évalue toutes les 2 s : cœur, MT5 (processus de lecture, fraîcheur des ticks pendant les heures de marché), état du compte,
données de marché, Risk Engine (dernier cycle), moteur d'exécution, réconciliation, base, heartbeat de l'agent, WebSocket.

| Défaut détecté | Gravité | Action |
|---|---|---|
| donnée périmée (aucun tick, marché ouvert) | moyenne | `SAFE` (entrées refusées `system_degraded`) |
| MT5 déconnecté / processus de lecture mort | haute | `RECONNECT` + `SAFE` ; au-delà du délai, `DISARM` |
| heartbeat de l'agent périmé | haute | `SAFE` ; `DISARM` si ARMED/AUTONOMOUS ; l'EA se coupe de lui-même (`DEAD_MAN`) |
| base indisponible | haute | `SAFE` (aucune commande ne peut être persistée) ; `HALT` si AUTONOMOUS |
| échec d'exécution / commande `UNKNOWN` | haute | `SAFE` + `RECONCILE` |
| échec de réconciliation persistant | critique | `HALT` |
| position inattendue (magic du Trading OS sans commande) | critique | `HALT` |
| erreur critique non gérée | critique | `HALT` + incident |

`HALT` = autonomie `HALTED` + `control.halt` à l'agent + incident ouvert ; la levée est un geste humain.

## 13. Configuration

`pydantic-settings`, variables d'environnement et `.env` (jamais committé). Les secrets (jetons, clé FRED) sont séparés de la configuration.

| Variable | Défaut | Rôle |
|---|---|---|
| `TRADING_ENV` | `development` | environnement logique |
| `DATABASE_URL` | `postgresql://tradingos:…@127.0.0.1:5433/tradingos` | base (le mot de passe de développement est dans `.env`, plus dans le code) |
| `MT5_ENABLED` | `true` | `false` = mode simulé (FakeMt5), aucun terminal requis |
| `TRADING_MODE` | `OBSERVE` | **plafond** de mode global |
| `ACTIVE_ACCOUNT_ID` | — | compte actif initial (sinon celui de `system_state`) |
| `LOG_LEVEL` | `INFO` | |
| `API_HOST`/`API_PORT` | `127.0.0.1`/`8000` | |
| `EA_LINK_HOST`/`EA_LINK_PORT` | `127.0.0.1`/`9765` | lien EA |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | |
| `CREDENTIAL_STORE` | `none` | `none` \| `windows` \| `env` (développement) |
| Secrets | | `TRADINGOS_COCKPIT_TOKEN`, `TRADINGOS_AGENT_TOKEN`, `FRED_API_KEY` |

## 14. Abstractions retenues — pourquoi chacune existe

| Abstraction | Justification |
|---|---|
| processus de lecture MT5 (worker) | module global + appels bloquants + plantages natifs (E-06) ; ajoute la liste blanche structurelle |
| `Mt5Transport` (sous-processus / en processus) | tests et mode simulé sans terminal ; une seule ligne de séparation |
| dispatcher d'événements | relie les services sans qu'ils se connaissent ; < 100 lignes ; pas de bus distribué |
| `OrderGateway` (Null, Paper, EaLink) | trois modes d'exécution réels ; c'est ce qui rend « OBSERVE n'envoie rien » testable |
| `CredentialStore` | exigé par la mission ; trois implémentations réelles (none, windows, env/test) |
| `Repository` (par agrégat) | SQL explicite isolé de la logique ; pas de classe générique |
| `ProfileFactory` (registre) | remplace les `if ftmo` : c'est la demande explicite de la mission |

Rejetées : usine de dépôts, adaptateurs de courtier génériques (Alpaca/SnapTrade exclus), file de messages, ORM, microservices.

## 15. Stratégie de test

| Couche | Outil | Contenu |
|---|---|---|
| Unitaire domaine | pytest | risque (gates, verrous, sizing × 5 symboles, corrélation, news, spread, session), exécution (états, idempotence, expiration), réconciliation (5 cas), autonomie, comptes, S01 et analyse (vecteurs d'or du TS) |
| Intégration | pytest-asyncio | lien EA par sockets réels, API (client ASGI), base jetable (**échoue** si absente, jamais « à vide »), supervisor |
| Contrat | pytest | schéma OpenAPI figé et types TS générés à jour ; liste blanche MT5 ; absence de secret dans les événements |
| MT5 | pytest | `FakeMt5` (toujours) ; suite `live` en lecture seule, activée par `MT5_LIVE_TESTS=1`, **jamais d'ordre** |
| Frontend | vitest, tsc, eslint, next build | présentation, store, client API/WS |
| Architecture | pytest | domaine sans E/S ; aucun `if provider` hors profils ; aucune fonction d'ordre côté Python |

## 16. Invariants — où chacun est tenu

| # | Invariant | Mécanisme | Test |
|---|---|---|---|
| 1 | Python est le cœur | tout le domaine/les services sont Python | arborescence |
| 2–3 | .NET et SignalR inutiles | dossiers supprimés | recherche globale (rapport) |
| 4–5 | pas d'Alpaca / SnapTrade | aucune référence | recherche globale |
| 6–7 | Exness/FTMO via MT5, encapsulé | `infrastructure/mt5/` seul | test d'architecture (import de `MetaTrader5` limité à `worker.py` et `observer`) |
| 8 | le frontend parle au cœur | `lib/api`, `lib/websocket` | build + tests |
| 9–10 | Risk Engine avant Exécution, aucun contournement | `ExecutionService.submit` exige une décision approuvée | `test_execution_requires_risk_decision` |
| 11 | chaque ordre a un `accountId` | champ requis du schéma | test API |
| 12 | un seul compte actif reçoit des ordres automatiques | `active_account` unique | test autonomie/exécution |
| 13 | identifiants jamais hors du cœur | `SecretStr`, filtre, sentinelles | test de sentinelle |
| 14–16 | EA ni cerveau, ni stratégie, événementiel | EA inchangé hors `DEAD_MAN` | revue du diff MQL5 |
| 17–18 | réconciliation et idempotence obligatoires | services + base | tests dédiés |
| 19–20 | kill switch, homme mort | `halt`, ping/`DEAD_MAN` | tests autonomie + lien EA |
| 21–22 | autonomie seulement si READY ; erreur critique ⇒ HALT | `AutonomyService`, supervisor | tests autonomie |
| 23–25 | pas de microservice, de pont, de code mort | un processus ; suppressions | recherche globale |

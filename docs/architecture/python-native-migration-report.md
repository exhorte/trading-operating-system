# Rapport de migration — Trading OS Python-native

Produit le 2026-10-09, à la fin de la mission « restructuration radicale » (phases 0 à 7). Branche `refactor/python-native-architecture`, commits **locaux** (rien n'est poussé). Décision : `context/adr/0016-architecture-python-native.md`. Audit de départ : `docs/architecture/migration-map.md`. Architecture livrée : `docs/architecture/python-native-architecture.md`. Les listes exactes de fichiers (supprimés, créés, modifiés) sont dans `docs/architecture/python-native-migration-files.md`.

**Verdict en trois lignes.** Le Gateway .NET, SignalR, l'observateur Python et tout ce qui n'existait que pour les relier ont été **supprimés du dépôt** (et leur conteneur et leur image de la machine). Un cœur Python modulaire en un seul processus porte le métier ; le cockpit Next.js lui parle en REST et en un WebSocket ; l'agent MQL5 reste l'exécutant local. **Aucun ordre n'a jamais été envoyé, et rien n'a encore tourné contre un vrai MT5, un vrai agent ou la vraie base** : la migration est vérifiée avec un terminal simulé, des sockets réels, un PostgreSQL jetable et un navigateur réel — le premier rattachement d'un compte est un essai que l'utilisateur doit faire, en `OBSERVE` (§ Reprendre).

## A. Architecture avant

```
MT5 ──▶ observateur Python (WebSocket 8765) ──▶ Gateway .NET (5080 : REST + hub SignalR ; 9765 : lien agent MQL5)
                                                    │                                    ▲
                    exportateur Python ─▶ fichiers JSONL ─▶ worker Node (S01) ─▶ PostgreSQL│
                                                    ▼                                    │
                              cockpit Next.js : client SignalR + Risk Engine, analyse ICT/SMC et détection de verrous
                              évalués **dans l'onglet du navigateur** ; serveur MCP et revue hebdomadaire en Node
```

Quatre langages (TypeScript, C#, Python, MQL5), une dizaine de processus lancés à la main, des contrats recopiés trois fois (TypeScript, C#, SQL), des traductions en cascade, une persistance perdante par conception, et un Risk Engine sans autorité (« aucun ordre n'oblige à l'avoir consulté »). Détail mesuré : `migration-map.md` § 1.

## B. Architecture après

```
cockpit Next.js ── REST + un WebSocket /ws ──▶ cœur Python (FastAPI, 127.0.0.1:8000, un processus)
                                                  │ domain/ (pur) → services/ → infrastructure/, derrière api/ et runtime/
                  ┌───────────────────────────────┼─────────────────────────────┐
                  ▼                               ▼                             ▼
     processus enfant MT5 (lecture seule,   lien agent TCP 127.0.0.1:9765   PostgreSQL / TimescaleDB
     liste blanche, aucun appel d'ordre)           │                         (Docker, volume existant)
                  ▼                               ▼
                 MT5 ◀────────────────────  EA TradingOsAgent 1.11 ──▶ courtier (Exness | FTMO)
```

Un monolithe modulaire : un processus, des frontières de code vérifiées par des tests d'architecture, un dispatcher d'événements en mémoire (≈ 45 lignes), aucun pont, aucun traducteur, aucun microservice. Le Risk Engine est le point de contrôle unique : `ExecutionService` refuse toute commande sans décision de risque approuvée, liée au même compte et non expirée. Le détail est dans `python-native-architecture.md`.

## C. Fichiers supprimés

Liste exacte : `python-native-migration-files.md`, § « Supprimés ». Par ensemble :

| Ensemble | Ce qui est parti |
|---|---|
| Le Gateway .NET | `backend/` en entier : 5 projets (`Contracts`, `Gateway`, `Host`, `Persistence`, `Gateway.Tests`), `TradingOs.slnx`, `Dockerfile`, `.dockerignore`, `appsettings*.json`, `launchSettings.json`, 60 fichiers (49 en C#) dont `Mt5AgentServer`, `Mt5ObserverClient`, `Mt5WireTranslator`, `GatewayBridgeService`, `LocalAccessGuard`, `AccountSettingsGuard`, `PersistenceMapper`, `RedactingConsoleFormatter`, `NewsCalendarService` — et leurs 16 fichiers de tests |
| L'observateur Python et ses outils | `tools/mt5-observer/` (observateur, exportateur de bougies, sonde de terminal, journal et analyse de spread, importeur d'historique, `list_symbols`, `spread_history`, leurs tests, `requirements.txt`, README) — les fonctions utiles sont devenues des commandes du cœur (`python -m trading_os export-history | import-candles | list-symbols | spread-history`) |
| Les scripts et le lanceur | `scripts/start-live.ps1`, `scripts/{run-setup-detection,dev-submit-command,import-candles}.ts` |
| SignalR et le transport d'avant | `lib/realtime/{signalr-client,mock-client,client,backend-url,mt5-translate}`, la source « mock » du navigateur (`lib/mock/`), `lib/contracts/` (13 fichiers : enveloppes, événements, wire recopiés) |
| La logique qui vivait dans l'onglet | `lib/risk/` (16), `lib/analysis/` (24), `lib/setup/` (22), `lib/domain/` (11), `lib/execution/`, `lib/market/`, l'ancienne `lib/accounts/` (17), l'évaluation de conformité et les types du journal — **portés** dans le cœur, pas abandonnés (voir K) |
| Les outils Node | `tools/{mcp-server,weekly-review,shared}/` — réécrits en Python (`python -m trading_os mcp | weekly-review`) |
| Les graphiques | composants de graphique, `chart-scale`, la fenêtre de graphique des captures (ADR 0018) |
| Docker | le service `backend` de `docker-compose.yml`, son réseau externe, le **conteneur `tradingos-backend` et l'image `04_code-backend`** (346 Mo) de la machine ; la base, son volume et les conteneurs des autres projets n'ont pas été touchés |
| Les documents qui ne décrivaient que cela | `docs/project/trading-operating-system-blueprint.md` (audit daté du 2026-10-05 de l'ancien système, 2 553 lignes), `context/backend/` (plan et bootstrap .NET), `context/realtime/{websocket_first_architecture,live_prototype,mt5_agent_realtime_lifecycle}.md` |
| Les générateurs de vecteurs d'or TypeScript | `python/tests/golden/generate_*.ts|mjs` (les vecteurs, eux, sont conservés ; `python/tests/golden/README.md` donne la provenance) |

**Données préservées, pas supprimées** : les exports de bougies et le journal de spread de l'observateur (`d1/h1/h4/m1_*.jsonl`, `spread_*.json`, ~ 1,2 Mo, ignorés par Git donc irrécupérables) ont été **déplacés** dans `exports/observer-2026-09/` (gitignoré) ; à l'utilisateur de les supprimer ou de les importer (`python -m trading_os import-candles`).

## D. Fichiers créés

Liste exacte : `python-native-migration-files.md`, § « Créés ». Par ensemble :

- **Le cœur** : `python/` (pyproject, `trading_os/` : 179 modules sur `app`, `api`, `domain`, `services`, `infrastructure`, `runtime`, `cli`, `mcp`, `devtools`, `shared` ; 3 migrations SQL et 2 scripts manuels ; `tests/` : 85 fichiers — domaine, services, API, intégration, base, architecture, vecteurs d'or).
- **Le cockpit** : `lib/api/` (client typé, `useApi`, types générés), `lib/websocket/`, `lib/realtime/` (store, contrôleur, fournisseur), `lib/cockpit/`, `lib/accounts/`, `lib/journal/`, `lib/compliance/`, `lib/account-analysis/`, et les composants de Settings, Account, journal et dossier de trade réécrits.
- **L'infrastructure et la documentation** : `scripts/start.ps1`, `docker-compose.yml` (réduit à la base), `.env.example`, `docs/architecture/` (carte de migration, architecture cible, ce rapport et sa liste), ADR 0016 et 0018, `context/infrastructure/persistence.md`, `python/tests/golden/README.md`.
- **L'agent** : build 1.11 de `TradingOsAgent.mq5` (modifié, pas créé) et `python/tests/architecture/test_execution_agent.py`, qui lit sa source.

## E. Fichiers modifiés

Liste exacte : `python-native-migration-files.md`, § « Modifiés ». Les principaux : `tools/mt5-execution-agent/` (interrupteur d'homme mort, renommages), `README.md`, `.claude/CLAUDE.md`, `context/` (réécriture des documents vivants ; amendements datés des ADR, des fiches d'outil et des archives), `package.json` et `package-lock.json` (dépendances), `eslint.config.mjs`, `.gitignore`, `app/` et `components/` (les douze écrans et la coque).

## F. Dépendances supprimées

| Quoi | Détail |
|---|---|
| Packages npm | `@microsoft/signalr`, `@modelcontextprotocol/sdk`, `zod` (dépendances) ; `pg`, `@types/pg`, `tsx` (développement) ; scripts `mcp` et `weekly-review` |
| Paquets NuGet | `Npgsql 10.0.3`, `Dapper 2.1.79`, `Microsoft.Extensions.Hosting.Abstractions 10.0.9`, `xunit`, `Microsoft.NET.Test.Sdk`, `coverlet.collector` — avec `backend/` ; cible `net10.0` |
| Paquet pip | `websockets` (observateur) |
| Services Docker | `backend` (.NET) ; le réseau externe `trading_operating_system_algorithmique_default`, qu'il imposait |
| Ports | **5080** (REST et hub SignalR), **8765** (observateur) |
| Variables d'environnement | `Cockpit__ListenUrl`, `Cockpit__AgentBindAny`, `Cockpit__AgentPort`, `Cockpit__ObserverUrl`, `Cockpit__DashboardOrigin`, `Cockpit__CockpitToken`, `Cockpit__ObserverToken`, `Cockpit__AgentToken`, `ConnectionStrings__TradingOs`, `Fred__ApiKey`, `TRADINGOS_OBSERVER_TOKEN`, `TRADINGOS_DB`, `TRADINGOS_CANDLES_DIR`, `TRADINGOS_ACCOUNT_ID`, `TRADING_OS_ACCOUNT_ID`, `NEXT_PUBLIC_REALTIME_SOURCE`, `NEXT_PUBLIC_BACKEND_HUB_URL`, `NEXT_PUBLIC_MOCK_ACCOUNT_ID`, `NEXT_PUBLIC_MT5_WS_URL` |
| Routes et hub | `/hub/cockpit` (méthodes `SubmitCommand`, `PublishEvent`…), `/api/audit/recent`, `/api/account-settings`, `/api/risk/today`, `/api/calendar/upcoming` et le reste de l'ancienne surface HTTP du backend — remplacés par les 59 opérations du cœur (`lib/api/generated.ts`) |
| Contrainte de la machine | plus aucun binaire .NET : la politique Smart App Control de Windows, qui en bloquait le chargement, n'est plus un sujet |

## G. Dépendances conservées

Next.js 16 / React 19 / TypeScript / Tailwind 4 / shadcn sur Radix / lucide-react / Vitest / ESLint (cockpit) ; Python ≥ 3.12 avec FastAPI, uvicorn, pydantic 2, pydantic-settings, psycopg 3, httpx, keyring, `MetaTrader5` (Windows), pytest, ruff, mypy ; PostgreSQL + TimescaleDB (le conteneur `tradingos-timescaledb` et son volume, intacts) ; MQL5 (l'agent) ; MetaEditor (la compilation). Aucune nouvelle plateforme de données de marché (Massive n'est pas intégrée), aucun Alpaca, aucun SnapTrade, aucun adaptateur de courtier générique.

## H. Migration des données

- **Aucune donnée n'est déplacée ni supprimée par la migration.** `0001_baseline.sql` recrée à l'identique (idempotent) le schéma que l'ancien backend avait créé : les 26 tables existantes sont reconnues telles quelles. `0002_core.sql` ajoute (comptes, limites versionnées, intentions, décisions, commandes à cycle de vie complet, journal d'événements, incidents, état système) et **renomme** l'ancienne `execution_commands` en `legacy_execution_commands` (lignes intactes). `0003_captures_are_data.sql` rend la fenêtre de graphique des captures optionnelle.
- **Les tables que le cœur ne lit plus** (`envelopes`, `legacy_execution_commands`, `account_settings`) restent, tant que `python -m trading_os db manual drop_legacy_tables --confirm drop_legacy_tables` n'a pas été lancé : **une décision de l'utilisateur sur son historique**, jamais automatique ; de même pour `drop_capture_window`.
- **Ce qui n'a pas été fait** : appliquer ces migrations à la vraie base. Elles ont été appliquées, vérifiées et rejouées sur des bases jetables, jamais sur `tradingos`. Une sauvegarde (`pg_dump -Fc`) précède le premier essai (runbook § 1).

## I. Migration frontend

Le cockpit ne fait plus que rendre : un client typé (`call("accounts_list")` — une opération se nomme, elle ne s'écrit pas comme une URL), un transport WebSocket (`CockpitSocket`), un contrôleur et un store pur (réducteur qui décrit ses effets au lieu de les exécuter). Les contrats TypeScript sont **générés** depuis les schémas du cœur (`python -m trading_os gen-types`) ; un test Python échoue si `lib/api/generated.ts` est périmé. Plus de Risk Engine, de moteur d'analyse ni de détection de verrous dans l'onglet. La source « mock » du navigateur est remplacée par le mode simulé du **cœur** (`MT5_ENABLED=false`), qui sert un compte de démonstration par le même chemin que le vrai.

**Vérification** : Chrome headless contre le vrai cœur et sa base — 12 écrans × {clair, sombre} × {bureau, mobile}, sur le build de production : aucune erreur console, aucun débordement, aucun contraste sous AA ; le formulaire de limites (aperçu en direct, enregistrement, report au prochain jour de trading, annulation) joué de bout en bout. Trouvé et corrigé en chemin : voir N.

## J. Migration MT5

Un seul module importe `MetaTrader5` (`infrastructure/mt5/worker.py`), dans **un processus enfant par terminal**, sur une **liste blanche** de 25 fonctions de lecture ; `order_send`, `order_check` et tout appel de modification n'y sont pas exécutables (un test l'exige, un autre le vérifie à travers le vrai processus). Le client (`Mt5Client`) vérifie le login et le serveur réels à chaque rattachement (`account_mismatch`, `server_mismatch`), mesure le décalage de l'horloge du courtier (l'heure serveur n'est pas UTC) et ne se fie qu'à l'identifiant de position, jamais au ticket. Les mots de passe ne sont jamais stockés par défaut (ADR 0013, stockage opt-in amendé par l'ADR 0016). **Suite de contrat du terminal** (`tests/integration/test_terminal_contract.py`) : les mêmes dix assertions tournent contre le terminal simulé (toujours) et contre un vrai terminal ouvert (`MT5_LIVE_TESTS=1`, lecture seule, sans jamais changer de compte) — **la partie réelle n'a pas été exécutée** (aucun terminal ouvert pendant la session).

**L'agent MQL5** (build 1.11) : un seul `OrderSend`, dans `ExecuteOrder`, derrière un plafond de mode compilé à `OBSERVE` ; nouvel interrupteur d'homme mort (aucun ordre accepté sans `control.ping` du cœur depuis `InpDeadManSeconds`, 30 s par défaut, jamais désactivable) ; `InpGatewayHost/Port` renommés `InpCoreHost/Port` ; `gatewaySilentMs` renommé `coreSilentMs` (le cœur lit encore l'ancien nom, pour un agent non recompilé) ; compile sans erreur ni avertissement. **Non déployée** dans le terminal de l'utilisateur.

## K. Migration du Risk Engine

Le Risk Engine **n'était pas en C#** : c'était du TypeScript évalué dans l'onglet. Il a été porté en Python (`domain/risk/` : portes, verrous, jour de trading, exposition, dimensionnement, décision) avec ses vecteurs et ses cas, et renforcé : un registre de verrous **persistant** (levée par accusé, pause temporisée sur pertes consécutives, kill switch), un dimensionnement avec les spécifications réelles du symbole (plus de facteur « or » codé en dur), des politiques par compte (FTMO ≠ Exness, par profils, sans `if provider`), `can_i_trade` avec 18 contrôles explicables et des raisons stables, et une décision de risque persistée et à durée de vie courte. Le cockpit n'a plus aucune copie de ces règles.

## L. Migration de l'exécution

Moteur centralisé (`services/execution.py`) : commande → validation → décision de risque → persistance `PENDING` **avant tout envoi** → route (`OBSERVE` n'envoie rien, `PAPER` simule, `CONFIRM`/`ARMED`/`AUTONOMOUS` passent par l'agent) → accusé → rapport → réconciliation. Idempotence par `commandId` aux deux bouts ; états explicites dont `UNKNOWN` (jamais rejoué, jamais ramené sur le chemin nominal) et `RECONCILING` ; un redémarrage ne renvoie jamais un ordre. L'autonomie (`OFF … AUTONOMOUS`, `HALTED`) a un bail d'armement, une readiness de 16 contrôles exigée en continu, et un superviseur qui déclenche SAFE / DISARM / HALT / RECONNECT / RECONCILE. Le lien agent est le seul chemin d'un ordre hors du cœur ; il n'a servi qu'en test, avec un agent simulé sur de vrais sockets.

## M. Tests

| Famille | Résultat |
|---|---|
| Python (pytest) | 2094 tests verts (unitaires, intégration par sockets réels et processus enfants, base jetable, architecture, contrat du terminal) — 10 ignorés : la partie « terminal réel » de la suite de contrat |
| Python (qualité) | `ruff check`, `ruff format --check` et `mypy --strict` propres sur tout `trading_os` et `tests` |
| Cockpit | Vitest 171 tests, `tsc --noEmit`, `eslint .`, `next build` (15 pages) propres |
| Agent MQL5 | MetaEditor : 0 erreur, 0 avertissement ; 9 tests de garde sur sa source, vérifiés par mutation (trois altérations échouent chacune au test voulu) |
| Navigateur | 12 écrans × {clair, sombre} × {bureau, mobile}, sur le build de production (les quatre combinaisons) et en développement, plus le parcours des limites de bout en bout (11 vérifications) |
| Contrat du terminal | 10 assertions × {simulé, réel} ; **le réel n'a pas tourné** |
| **Jamais exécuté** | tout contre un vrai MT5, un vrai agent attaché, la vraie base `tradingos`, `scripts/start.ps1` hors `-Plan` |

Les tests demandés par la mission (§ 49) — compte (connexion, déconnexion, mauvais serveur, désaccord de compte), MT5 (connexion, symbole, tick, positions, ordres, compte), risque (perte du jour, drawdown, risque maximal, risque ouvert, corrélation, spread, actualité, symbole, règles du compte), exécution (doublon, expirée, inconnue, échec, désaccord de compte et de symbole), réconciliation (position manquante, inattendue, mauvais volume, SL, TP), autonomie (pas d'armement si malsain, rien d'exécuté en HALTED, homme mort, kill switch) — ont chacun leurs tests dans `python/tests/` ; « mauvais identifiants » se teste sans jamais manipuler un vrai mot de passe (des sentinelles : un faux mot de passe ne doit apparaître ni dans les journaux, ni dans les réponses, ni dans les événements, ni dans les exceptions, ni dans les tables).

## N. Problèmes rencontrés

Trouvés **en vérifiant pour de vrai**, pas en relisant du code :

- Rattacher un compte ouvrait un verrou persistant « Max drawdown guard » avant la première lecture du compte (un verrou n'est plus ouvert que sur un instantané mesuré).
- uvicorn réinstallait son propre format de journal et écrivait la ligne d'acceptation du WebSocket avec **`?access_token=…` en clair** (corrigé : `log_config=None`, test de non-régression à travers le vrai `uvicorn.Config`).
- Le fichier de types généré dépendait de ce que les tests avaient enregistré dans le registre d'événements du processus : une exécution complète n'écrivait pas le même contrat qu'une exécution isolée (corrigé : seuls les événements de l'application comptent).
- Le journal demandait à la stratégie une fenêtre de 90 jours alors que le cœur refuse plus de 31 (HTTP 422), et affichait alors « 0 / 3 trades pris sur une proposition » au lieu de tirets (corrigé : fenêtre bornée par une constante générée depuis le cœur, tiret quand la lecture manque ou ne couvre pas la période).
- Le message de confirmation d'un enregistrement de limites disparaissait avec le formulaire, que l'enregistrement lui-même remplace (corrigé : le message vit dans la page).
- « Niveaux enregistrés » comptait les lignes de capture, pas les trades dont le R se calcule : un trade reconstitué depuis l'historique a une ligne et pas de stop (remplacé par « R calculable »).
- Deux contrastes sous 4,5 : 1 (la pastille « Bloquant » sur une carte teintée ; le rouge du thème sombre sur une pastille teintée) — corrigés avec des valeurs calculées, pas estimées.
- Un onglet de navigateur **caché** ne peint rien : React n'y révèle pas le contenu diffusé en flux et la page reste sur « Chargement de l'écran… » alors que le serveur a répondu. Faux positif de l'outil de vérification, pas un défaut de l'application (prouvé par curl et par un Chrome headless).
- Les tests qui gardent la source de l'agent ont été éprouvés par **mutation** : trois altérations de la source (un ordre qui compte comme preuve de vie, le contrôle d'homme mort déplacé, la limite désactivable) échouent chacune au test voulu.

## O. Dette restante

- **TD-09 : aucune sortie S01.** `position_management_valid` échoue : AUTONOMOUS est bloqué, c'est voulu.
- **L'entrée `LIMIT` de S01** n'est pas portée par le protocole de l'agent (marché seulement) ; `MODIFY`, `CLOSE`, `PARTIAL_CLOSE`, `CANCEL` n'ont pas de capacité côté agent : refusés à la soumission.
- **Formulaire de connexion avec mot de passe (ADR 0013, T13)** : non construit ; le cœur sait se rattacher à un terminal déjà connecté et accepte un identifiant en écriture seule.
- **La readiness n'exige pas la capacité `dead_man`** : un agent < 1.11 peut encore être attaché ; la documentation le dit.
- **L'évaluation des objectifs de challenge** reste en TypeScript (`lib/accounts/objectives.ts`) : de la présentation de chiffres que le cœur fournit, à porter si elle devait décider quelque chose.
- **Commentaires « port de `lib/…` »** dans le domaine Python : ils renvoient à des fichiers TypeScript supprimés (provenance, récupérables dans Git à `dc8db3e`) ; les commentaires de `0001_baseline.sql` nomment d'anciens fichiers C# — une migration appliquée ne se modifie pas.
- **`gatewaySilentMs`** : une ligne de compatibilité à retirer quand tous les agents sont recompilés.
- **Pas d'intégration continue**, pas de sauvegarde automatique de la base, rien ne relance le cœur s'il s'arrête.
- **Les tables héritées** (`envelopes`, `account_settings`, `legacy_execution_commands`) et la colonne de fenêtre de graphique : scripts prêts, non lancés.

## P. Architecture finale

Voir B, et `python-native-architecture.md` pour les flux de données, d'exécution, de compte, de risque et d'autonomie, l'intégration MT5 et frontend, la sécurité et les pannes. Résumé des invariants de la mission (§ 50) et de leur garde :

| # | Invariant | Garde |
|---|---|---|
| 1 | Python est le cœur | tout le métier est dans `python/trading_os/` |
| 2–3 | .NET et SignalR ne sont plus nécessaires | `backend/` et le client SignalR supprimés ; recherche globale ci-dessous |
| 4–5 | Ni Alpaca ni SnapTrade | aucune référence hors la phrase qui les exclut |
| 6–7 | Exness et FTMO passent par MT5, encapsulé | `infrastructure/mt5/` ; `MetaTrader5` importé dans un seul module (test) |
| 8 | Le frontend parle au cœur | `lib/api`, `lib/websocket` |
| 9–10 | Risk Engine avant l'exécution, aucun contournement | `ExecutionService.submit` exige une décision approuvée (test) |
| 11–12 | Chaque ordre a un `accountId` ; un seul compte actif reçoit les ordres automatiques | champ requis ; compte actif unique |
| 13 | Les identifiants ne sortent jamais du cœur | `SecretStr`, masquage des journaux, sentinelles, test sur `information_schema` |
| 14–16 | L'EA n'est ni le cerveau, ni la stratégie, et reste événementiel | revue du diff MQL5 ; `test_execution_agent.py` |
| 17–18 | Réconciliation et idempotence obligatoires | services et base, tests dédiés |
| 19–20 | Kill switch et homme mort | `halt`, ping / `DEAD_MAN`, tests |
| 21–22 | L'autonomie exige READY ; une erreur critique fait HALT | `AutonomyService`, superviseur, tests |
| 23–25 | Pas de microservice, de pont ni de code mort | un processus ; suppressions ; recherche globale |

## Q. Risques connus

- **Rien n'a tourné contre un vrai terminal.** Les décalages d'horloge, les `retcode`, la trace de commande dans le commentaire d'un deal, la reconstitution d'une position ouverte et fermée entre deux lectures, la réaction de `MetaTrader5` à un terminal fermé : tout cela est modélisé et testé contre un simulateur écrit par nous. La suite de contrat (`MT5_LIVE_TESTS=1`) est faite pour le dire en dix assertions en lecture seule.
- **La vraie base** : le premier `db migrate` s'applique à des données réelles. Les migrations sont additives et vérifiées sur des bases jetables, jamais sur celle-ci.
- **Fenêtre de refus de l'homme mort** : ≤ 5 s après chaque (re)connexion de l'agent, avant le premier ping, tout nouvel ordre est refusé (`DEAD_MAN`) — voulu, mais surprenant au premier essai.
- **Un seul processus** : si le cœur tombe, le cockpit, la supervision et l'envoi d'ordres s'arrêtent ; les stops posés chez le courtier restent. Rien ne relance le cœur.
- **Windows seulement** pour le cœur (le paquet `MetaTrader5`) ; le reste se teste partout.
- **Un compte Windows compromis lit `.env`, la mémoire et les fichiers MT5** : hors du modèle de menace assumé (ADR 0013).
- **Le plafond de mode** : `OBSERVE` à la compilation de l'agent ET par défaut dans le cœur. Le relever est un geste de l'utilisateur, dans l'ordre ADR → fiche → incrément ; rien dans cette migration ne le fait.

## Recherche globale (mission § 52)

Faite sur les fichiers suivis par Git, à la fin de la phase 7 (`git grep -I`). **Aucune dépendance fonctionnelle à l'ancienne architecture ne subsiste** : aucun code, test, script, configuration ni commande ne cite plus `dotnet`, `.csproj`, SignalR, un hub, le Gateway, l'observateur, `start-live`, les ports 5080 et 8765 ni les anciennes variables d'environnement, hors ce qui suit.

| Motif | Reste | Nature |
|---|---|---|
| `dotnet`, `.NET`, `C#`, `.csproj`, SignalR, Gateway, observateur, `start-live`, `mt5-observer`, noms des anciens ponts et classes (`CockpitHub`, `Mt5AgentServer`…) | `context/project/session-log.md`, les fiches d'outil `context/product/tools/*` (journaux datés), les ADR 0003, 0004, 0010, 0012, 0013, 0014, 0016, `docs/architecture/migration-map.md`, quelques commentaires de `0001_baseline.sql` | **Archives** : ce qui a été décidé ou fait, à sa date (ADR 0008). Chaque archive qui décrit l'ancien système porte une note d'amendement datée en tête, et chaque fiche son « ancrage actuel » |
| `Gateway` | `python/trading_os/infrastructure/mt5/wire.py` (2), son test | l'alias de lecture `gatewaySilentMs` d'un agent < 1.11, documenté, à retirer |
| `Alpaca`, `SnapTrade` | `docs/architecture/python-native-architecture.md` | la phrase qui les exclut |
| `TRADINGOS_ACCOUNT_ID` et variantes | aucun | — (le serveur MCP lit `ACTIVE_ACCOUNT_ID`) |
| `lib/<ancien module>` dans les commentaires Python | 37 lignes dans 35 fichiers (« port de `lib/…` ») | provenance des portages ; les fichiers sont dans Git (`git show dc8db3e:lib/analysis/atr.ts`) |

Les mots « hub » et « gateway » ont aussi disparu du vocabulaire du code Python : le diffuseur WebSocket est `CockpitStream`, les routes d'envoi d'ordres sont des `OrderSender`.

## Reprendre

Pour l'utilisateur, dans cet ordre (rien n'est destructeur avant la deuxième étape) : 1. relire et fusionner la branche ; 2. sauvegarder la base, puis `pwsh -File scripts\start.ps1 -Plan` et sans `-Plan`, ouvrir MT5, recompiler et rattacher l'agent 1.11, enregistrer le compte et ses limites dans Settings, lancer la suite de contrat du terminal en lecture seule ; 3. laisser tourner S01 en `OBSERVE` pendant les killzones ; 4. seulement ensuite les incréments I3 à I8, chacun après son ADR ou sa fiche. Détail : `context/project/state.md` et `context/infrastructure/runbook.md`.

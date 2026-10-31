# Migration Python-native — liste exacte des fichiers

Générée le 2026-10-09 par `git diff --cached --name-status -M e53a4ac` au moment du dernier commit de la migration (parent : `ec51195` ; ce fichier figure lui-même dans « Créés »). `e53a4ac` est le commit « snapshot before python-native migration ». Annexe du rapport `python-native-migration-report.md` (sections C, D, E).

**Lecture.** La plage `e53a4ac..` contient aussi la refonte visuelle du cockpit (ADR 0017, commit `f364122`) : les fichiers de `app/`, `components/` et `context/frontend/` qu'elle a touchés sont dans « Modifiés » ou « Créés » sans être de la migration. Les dossiers `node_modules`, `.next`, `python/.venv` et les données ignorées par Git (`exports/`, fichiers `.env*`) n'en font pas partie.

| | Fichiers |
|---|---:|
| Supprimés | 229 |
| Créés | 337 |
| Modifiés | 139 |
| Renommés (avec ou sans modification) | 2 |

## Supprimés (229)

### `backend` (2)

- `backend/.dockerignore`
- `backend/TradingOs.slnx`

### `backend/src/TradingOs.Contracts` (7)

- `backend/src/TradingOs.Contracts/AccountSettings.cs`
- `backend/src/TradingOs.Contracts/Envelope.cs`
- `backend/src/TradingOs.Contracts/Execution.cs`
- `backend/src/TradingOs.Contracts/Mt5AgentStatus.cs`
- `backend/src/TradingOs.Contracts/Mt5Wire.cs`
- `backend/src/TradingOs.Contracts/ReadModels.cs`
- `backend/src/TradingOs.Contracts/TradingOs.Contracts.csproj`

### `backend/src/TradingOs.Gateway` (8)

- `backend/src/TradingOs.Gateway/FredCalendarClient.cs`
- `backend/src/TradingOs.Gateway/FredReleaseSchedule.cs`
- `backend/src/TradingOs.Gateway/GatewayState.cs`
- `backend/src/TradingOs.Gateway/Mt5AgentServer.cs`
- `backend/src/TradingOs.Gateway/Mt5ObserverClient.cs`
- `backend/src/TradingOs.Gateway/Mt5WireTranslator.cs`
- `backend/src/TradingOs.Gateway/TradingDayAnchor.cs`
- `backend/src/TradingOs.Gateway/TradingOs.Gateway.csproj`

### `backend/src/TradingOs.Host` (12)

- `backend/src/TradingOs.Host/AccountSettingsEndpoints.cs`
- `backend/src/TradingOs.Host/CockpitHub.cs`
- `backend/src/TradingOs.Host/Dockerfile`
- `backend/src/TradingOs.Host/GatewayBridgeService.cs`
- `backend/src/TradingOs.Host/LocalAccessGuard.cs`
- `backend/src/TradingOs.Host/NewsCalendarService.cs`
- `backend/src/TradingOs.Host/Program.cs`
- `backend/src/TradingOs.Host/Properties/launchSettings.json`
- `backend/src/TradingOs.Host/RedactingConsoleFormatter.cs`
- `backend/src/TradingOs.Host/TradingOs.Host.csproj`
- `backend/src/TradingOs.Host/appsettings.Development.json`
- `backend/src/TradingOs.Host/appsettings.json`

### `backend/src/TradingOs.Persistence` (15)

- `backend/src/TradingOs.Persistence/AccountSettingsGuard.cs`
- `backend/src/TradingOs.Persistence/AccountSettingsRepository.cs`
- `backend/src/TradingOs.Persistence/AccountSettingsValidation.cs`
- `backend/src/TradingOs.Persistence/AuditRepository.cs`
- `backend/src/TradingOs.Persistence/CandleRepository.cs`
- `backend/src/TradingOs.Persistence/ExecutionDivergenceRepository.cs`
- `backend/src/TradingOs.Persistence/JournalRepository.cs`
- `backend/src/TradingOs.Persistence/NewsCalendarRepository.cs`
- `backend/src/TradingOs.Persistence/PersistenceMapper.cs`
- `backend/src/TradingOs.Persistence/PersistenceWriter.cs`
- `backend/src/TradingOs.Persistence/RiskLockoutHistoryRepository.cs`
- `backend/src/TradingOs.Persistence/RiskTodayRepository.cs`
- `backend/src/TradingOs.Persistence/SetupProposalRepository.cs`
- `backend/src/TradingOs.Persistence/TradeCaptureRepository.cs`
- `backend/src/TradingOs.Persistence/TradingOs.Persistence.csproj`

### `backend/tests/TradingOs.Gateway.Tests` (16)

- `backend/tests/TradingOs.Gateway.Tests/AccountSettingsGuardTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/AccountSettingsValidationTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/AuditRepositoryIntegrationTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/ExecutionTranslationTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/FredReleaseScheduleTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/LocalAccessGuardTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/Mt5AgentServerTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/Mt5ObserverClientTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/Mt5WireI1Tests.cs`
- `backend/tests/TradingOs.Gateway.Tests/Mt5WireI2Tests.cs`
- `backend/tests/TradingOs.Gateway.Tests/Mt5WireTranslatorTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/PersistenceMapperTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/RedactingConsoleFormatterTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/RiskTodayRepositoryTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/TradingDayAnchorTests.cs`
- `backend/tests/TradingOs.Gateway.Tests/TradingOs.Gateway.Tests.csproj`

### `components/accounts` (6)

- `components/accounts/code-rules-card.tsx`
- `components/accounts/connection-procedure.tsx`
- `components/accounts/exness-settings-form.tsx`
- `components/accounts/firm-account-card.tsx`
- `components/accounts/ftmo-settings-form.tsx`
- `components/accounts/use-settings-submit.ts`

### `components/cockpit` (7)

- `components/cockpit/compliance-card.tsx`
- `components/cockpit/execution-reports-feed.tsx`
- `components/cockpit/kpi-card.tsx`
- `components/cockpit/kpi-strip.tsx`
- `components/cockpit/reconciliation-view.tsx`
- `components/cockpit/risk-status-panel.tsx`
- `components/cockpit/setup-proposals-panel.tsx`

### `components/journal` (1)

- `components/journal/trade-chart.tsx`

### `components/shell` (1)

- `components/shell/app-sidebar.tsx`

### `components/ui` (1)

- `components/ui/sidebar.tsx`

### `context/backend` (3)

- `context/backend/backend_bootstrap.md`
- `context/backend/backend_plan.md`
- `context/backend/persistence.md`

### `context/realtime` (3)

- `context/realtime/live_prototype.md`
- `context/realtime/mt5_agent_realtime_lifecycle.md`
- `context/realtime/websocket_first_architecture.md`

### `docs/project` (1)

- `docs/project/trading-operating-system-blueprint.md`

### `hooks` (1)

- `hooks/use-mobile.ts`

### `lib/accounts` (17)

- `lib/accounts/active-profile.test.ts`
- `lib/accounts/active-profile.ts`
- `lib/accounts/connection.test.ts`
- `lib/accounts/connection.ts`
- `lib/accounts/cost-model.test.ts`
- `lib/accounts/cost-model.ts`
- `lib/accounts/firm.ts`
- `lib/accounts/ftmo.ts`
- `lib/accounts/index.ts`
- `lib/accounts/real.ts`
- `lib/accounts/registry.test.ts`
- `lib/accounts/registry.ts`
- `lib/accounts/settings-api.ts`
- `lib/accounts/settings.test.ts`
- `lib/accounts/settings.ts`
- `lib/accounts/types.ts`
- `lib/accounts/use-account-settings.ts`

### `lib/analysis` (24)

- `lib/analysis/aggregate.test.ts`
- `lib/analysis/aggregate.ts`
- `lib/analysis/atr.test.ts`
- `lib/analysis/atr.ts`
- `lib/analysis/bias.test.ts`
- `lib/analysis/bias.ts`
- `lib/analysis/config.ts`
- `lib/analysis/index.ts`
- `lib/analysis/liquidity.test.ts`
- `lib/analysis/liquidity.ts`
- `lib/analysis/market-context.test.ts`
- `lib/analysis/market-context.ts`
- `lib/analysis/pd-arrays.test.ts`
- `lib/analysis/pd-arrays.ts`
- `lib/analysis/scoring.test.ts`
- `lib/analysis/scoring.ts`
- `lib/analysis/sessions.test.ts`
- `lib/analysis/sessions.ts`
- `lib/analysis/structure.test.ts`
- `lib/analysis/structure.ts`
- `lib/analysis/swings.test.ts`
- `lib/analysis/swings.ts`
- `lib/analysis/test-helpers.ts`
- `lib/analysis/types.ts`

### `lib/compliance` (5)

- `lib/compliance/evaluate.test.ts`
- `lib/compliance/evaluate.ts`
- `lib/compliance/summarize.ts`
- `lib/compliance/violations.test.ts`
- `lib/compliance/violations.ts`

### `lib/contracts` (12)

- `lib/contracts/commands.ts`
- `lib/contracts/enums.ts`
- `lib/contracts/envelope.ts`
- `lib/contracts/events.ts`
- `lib/contracts/execution/idempotency.test.ts`
- `lib/contracts/execution/idempotency.ts`
- `lib/contracts/execution/index.ts`
- `lib/contracts/execution/reject-reason.ts`
- `lib/contracts/mt5-wire.ts`
- `lib/contracts/projections-risk.test.ts`
- `lib/contracts/projections.test.ts`
- `lib/contracts/snapshots.ts`

### `lib/domain` (11)

- `lib/domain/account.ts`
- `lib/domain/analysis.ts`
- `lib/domain/execution-state.test.ts`
- `lib/domain/execution-state.ts`
- `lib/domain/execution.ts`
- `lib/domain/index.ts`
- `lib/domain/market.ts`
- `lib/domain/primitives.ts`
- `lib/domain/risk.ts`
- `lib/domain/setup.ts`
- `lib/domain/strategy.ts`

### `lib/execution` (2)

- `lib/execution/command-builder.test.ts`
- `lib/execution/command-builder.ts`

### `lib/journal` (3)

- `lib/journal/chart-scale.test.ts`
- `lib/journal/chart-scale.ts`
- `lib/journal/types.ts`

### `lib/market` (2)

- `lib/market/symbols/registry.test.ts`
- `lib/market/symbols/registry.ts`

### `lib/mock` (3)

- `lib/mock/candles.ts`
- `lib/mock/envelope.ts`
- `lib/mock/initial-snapshot.ts`

### `lib/realtime` (6)

- `lib/realtime/backend-url.ts`
- `lib/realtime/client.ts`
- `lib/realtime/mock-client.ts`
- `lib/realtime/mt5-translate.test.ts`
- `lib/realtime/mt5-translate.ts`
- `lib/realtime/signalr-client.ts`

### `lib/risk` (16)

- `lib/risk/evaluate.test.ts`
- `lib/risk/evaluate.ts`
- `lib/risk/gates.test.ts`
- `lib/risk/gates.ts`
- `lib/risk/index.ts`
- `lib/risk/lockout.test.ts`
- `lib/risk/lockout.ts`
- `lib/risk/news-calendar.test.ts`
- `lib/risk/news-calendar.ts`
- `lib/risk/open-risk.test.ts`
- `lib/risk/open-risk.ts`
- `lib/risk/policy.test.ts`
- `lib/risk/policy.ts`
- `lib/risk/sizing.test.ts`
- `lib/risk/sizing.ts`
- `lib/risk/types.ts`

### `lib/setup` (22)

- `lib/setup/bias.test.ts`
- `lib/setup/bias.ts`
- `lib/setup/dealing-range.test.ts`
- `lib/setup/dealing-range.ts`
- `lib/setup/displacement.test.ts`
- `lib/setup/displacement.ts`
- `lib/setup/gates.test.ts`
- `lib/setup/gates.ts`
- `lib/setup/liquidity.test.ts`
- `lib/setup/liquidity.ts`
- `lib/setup/poi.test.ts`
- `lib/setup/poi.ts`
- `lib/setup/preconditions.test.ts`
- `lib/setup/preconditions.ts`
- `lib/setup/proposal.test.ts`
- `lib/setup/proposal.ts`
- `lib/setup/reconciliation.test.ts`
- `lib/setup/reconciliation.ts`
- `lib/setup/stop.test.ts`
- `lib/setup/stop.ts`
- `lib/setup/sweep.test.ts`
- `lib/setup/sweep.ts`

### `scripts` (4)

- `scripts/dev-submit-command.ts`
- `scripts/import-candles.ts`
- `scripts/run-setup-detection.ts`
- `scripts/start-live.ps1`

### `tools/mcp-server` (2)

- `tools/mcp-server/README.md`
- `tools/mcp-server/index.ts`

### `tools/mt5-observer` (12)

- `tools/mt5-observer/README.md`
- `tools/mt5-observer/analyze_spread.py`
- `tools/mt5-observer/export_m1_candles.py`
- `tools/mt5-observer/import_history.py`
- `tools/mt5-observer/list_symbols.py`
- `tools/mt5-observer/log_spread.py`
- `tools/mt5-observer/mt5_observer.py`
- `tools/mt5-observer/probe_terminal.py`
- `tools/mt5-observer/requirements.txt`
- `tools/mt5-observer/spread_history.py`
- `tools/mt5-observer/test_mt5_observer.py`
- `tools/mt5-observer/test_probe_terminal.py`

### `tools/shared` (1)

- `tools/shared/backend-client.ts`

### `tools/weekly-review` (3)

- `tools/weekly-review/index.ts`
- `tools/weekly-review/render.ts`
- `tools/weekly-review/stats.ts`

## Créés (337)

### `components/accounts` (7)

- `components/accounts/account-metrics.tsx`
- `components/accounts/connection-help.tsx`
- `components/accounts/register-account-form.tsx`
- `components/accounts/registered-account-card.tsx`
- `components/accounts/rules-form.tsx`
- `components/accounts/settings-metrics.tsx`
- `components/accounts/use-account-actions.ts`

### `components/analyse` (1)

- `components/analyse/analysis-metrics.tsx`

### `components/cockpit` (7)

- `components/cockpit/agents-metrics.tsx`
- `components/cockpit/command-center-metrics.tsx`
- `components/cockpit/execution-commands-feed.tsx`
- `components/cockpit/market-metrics.tsx`
- `components/cockpit/risk-gates-panel.tsx`
- `components/cockpit/risk-metrics.tsx`
- `components/cockpit/setups-screen.tsx`

### `components/journal` (5)

- `components/journal/breakdown-table.tsx`
- `components/journal/journal-metrics.tsx`
- `components/journal/month-calendar.tsx`
- `components/journal/trade-file-metrics.tsx`
- `components/journal/trades-table.tsx`

### `components/shell` (5)

- `components/shell/logo.tsx`
- `components/shell/mobile-nav.tsx`
- `components/shell/page-header.tsx`
- `components/shell/sidebar-nav.tsx`
- `components/shell/theme-toggle.tsx`

### `components/ui` (6)

- `components/ui/callout.tsx`
- `components/ui/data-list.tsx`
- `components/ui/filter-bar.tsx`
- `components/ui/metric-panel.tsx`
- `components/ui/split-layout.tsx`
- `components/ui/table.tsx`

### `context/adr` (3)

- `context/adr/0016-architecture-python-native.md`
- `context/adr/0017-design-exponentvalue-monochrome.md`
- `context/adr/0018-suppression-de-la-capture-graphique.md`

### `context/infrastructure` (1)

- `context/infrastructure/persistence.md`

### `docs/architecture` (4)

- `docs/architecture/migration-map.md`
- `docs/architecture/python-native-architecture.md`
- `docs/architecture/python-native-migration-files.md`
- `docs/architecture/python-native-migration-report.md`

### `lib/accounts` (7)

- `lib/accounts/guard-text.test.ts`
- `lib/accounts/guard-text.ts`
- `lib/accounts/profile.test.ts`
- `lib/accounts/profile.ts`
- `lib/accounts/rules-draft.test.ts`
- `lib/accounts/rules-draft.ts`
- `lib/accounts/use-rules.ts`

### `lib/api` (4)

- `lib/api/client.test.ts`
- `lib/api/client.ts`
- `lib/api/generated.ts`
- `lib/api/use-api.ts`

### `lib/cockpit` (6)

- `lib/cockpit/calendar.test.ts`
- `lib/cockpit/calendar.ts`
- `lib/cockpit/command-state.ts`
- `lib/cockpit/market-context-view.test.ts`
- `lib/cockpit/use-market-context.ts`
- `lib/cockpit/use-now.ts`

### `lib/journal` (2)

- `lib/journal/setup-coverage.test.ts`
- `lib/journal/setup-coverage.ts`

### `lib/realtime` (3)

- `lib/realtime/controller.test.ts`
- `lib/realtime/controller.ts`
- `lib/realtime/test-fixtures.ts`

### `lib/websocket` (2)

- `lib/websocket/cockpit-socket.test.ts`
- `lib/websocket/cockpit-socket.ts`

### `python` (1)

- `python/pyproject.toml`

### `python/tests` (2)

- `python/tests/__init__.py`
- `python/tests/conftest.py`

### `python/tests/architecture` (3)

- `python/tests/architecture/__init__.py`
- `python/tests/architecture/test_execution_agent.py`
- `python/tests/architecture/test_invariants.py`

### `python/tests/db` (3)

- `python/tests/db/__init__.py`
- `python/tests/db/test_migrations.py`
- `python/tests/db/test_repositories.py`

### `python/tests/golden` (4)

- `python/tests/golden/README.md`
- `python/tests/golden/analysis.json`
- `python/tests/golden/numbers.json`
- `python/tests/golden/s01.json`

### `python/tests/integration` (4)

- `python/tests/integration/__init__.py`
- `python/tests/integration/test_ea_link.py`
- `python/tests/integration/test_mt5_worker_process.py`
- `python/tests/integration/test_terminal_contract.py`

### `python/tests/support` (7)

- `python/tests/support/__init__.py`
- `python/tests/support/api.py`
- `python/tests/support/builders.py`
- `python/tests/support/candles.py`
- `python/tests/support/core.py`
- `python/tests/support/harness.py`
- `python/tests/support/postgres.py`

### `python/tests/unit` (66)

- `python/tests/unit/__init__.py`
- `python/tests/unit/api/__init__.py`
- `python/tests/unit/api/conftest.py`
- `python/tests/unit/api/test_accounts_routes.py`
- `python/tests/unit/api/test_autonomy_routes.py`
- `python/tests/unit/api/test_execution_routes.py`
- `python/tests/unit/api/test_journal_routes.py`
- `python/tests/unit/api/test_market_routes.py`
- `python/tests/unit/api/test_openapi_contract.py`
- `python/tests/unit/api/test_risk_routes.py`
- `python/tests/unit/api/test_security.py`
- `python/tests/unit/api/test_strategy_routes.py`
- `python/tests/unit/api/test_system_routes.py`
- `python/tests/unit/api/test_websocket.py`
- `python/tests/unit/cli/__init__.py`
- `python/tests/unit/cli/test_cli.py`
- `python/tests/unit/cli/test_spreads.py`
- `python/tests/unit/cli/test_weekly_review.py`
- `python/tests/unit/devtools/__init__.py`
- `python/tests/unit/devtools/test_typescript.py`
- `python/tests/unit/domain/__init__.py`
- `python/tests/unit/domain/analysis/__init__.py`
- `python/tests/unit/domain/analysis/test_behaviour.py`
- `python/tests/unit/domain/analysis/test_golden.py`
- `python/tests/unit/domain/risk/__init__.py`
- `python/tests/unit/domain/risk/fixtures.py`
- `python/tests/unit/domain/risk/test_decision.py`
- `python/tests/unit/domain/risk/test_evaluate_and_gates.py`
- `python/tests/unit/domain/risk/test_exposure.py`
- `python/tests/unit/domain/risk/test_lockout_and_trading_day.py`
- `python/tests/unit/domain/risk/test_sizing.py`
- `python/tests/unit/domain/s01/__init__.py`
- `python/tests/unit/domain/s01/scenario.py`
- `python/tests/unit/domain/s01/test_behaviour.py`
- `python/tests/unit/domain/s01/test_golden.py`
- `python/tests/unit/domain/test_accounts.py`
- `python/tests/unit/domain/test_autonomy.py`
- `python/tests/unit/domain/test_compliance.py`
- `python/tests/unit/domain/test_execution.py`
- `python/tests/unit/domain/test_market.py`
- `python/tests/unit/domain/test_reconciliation_and_supervision.py`
- `python/tests/unit/domain/test_trace_and_resolution.py`
- `python/tests/unit/infrastructure/__init__.py`
- `python/tests/unit/infrastructure/test_fred_client.py`
- `python/tests/unit/infrastructure/test_mt5_protocol_and_client.py`
- `python/tests/unit/infrastructure/test_mt5_semantics.py`
- `python/tests/unit/mcp/__init__.py`
- `python/tests/unit/mcp/test_server.py`
- `python/tests/unit/runtime/__init__.py`
- `python/tests/unit/runtime/test_engine.py`
- `python/tests/unit/runtime/test_readiness.py`
- `python/tests/unit/runtime/test_scheduler_and_heartbeat.py`
- `python/tests/unit/runtime/test_supervisor.py`
- `python/tests/unit/services/__init__.py`
- `python/tests/unit/services/test_accounts_service.py`
- `python/tests/unit/services/test_autonomy_service.py`
- `python/tests/unit/services/test_execution_service.py`
- `python/tests/unit/services/test_journal_service.py`
- `python/tests/unit/services/test_market_data_service.py`
- `python/tests/unit/services/test_news_service.py`
- `python/tests/unit/services/test_position_service.py`
- `python/tests/unit/services/test_reconciliation_service.py`
- `python/tests/unit/services/test_risk_service.py`
- `python/tests/unit/services/test_strategy_service.py`
- `python/tests/unit/test_numbers.py`
- `python/tests/unit/test_shared.py`

### `python/trading_os` (2)

- `python/trading_os/__init__.py`
- `python/trading_os/__main__.py`

### `python/trading_os/api` (26)

- `python/trading_os/api/__init__.py`
- `python/trading_os/api/errors.py`
- `python/trading_os/api/params.py`
- `python/trading_os/api/routes/__init__.py`
- `python/trading_os/api/routes/accounts.py`
- `python/trading_os/api/routes/autonomy.py`
- `python/trading_os/api/routes/execution.py`
- `python/trading_os/api/routes/journal.py`
- `python/trading_os/api/routes/market.py`
- `python/trading_os/api/routes/risk.py`
- `python/trading_os/api/routes/strategy.py`
- `python/trading_os/api/routes/system.py`
- `python/trading_os/api/schemas/__init__.py`
- `python/trading_os/api/schemas/accounts.py`
- `python/trading_os/api/schemas/autonomy.py`
- `python/trading_os/api/schemas/common.py`
- `python/trading_os/api/schemas/execution.py`
- `python/trading_os/api/schemas/journal.py`
- `python/trading_os/api/schemas/market.py`
- `python/trading_os/api/schemas/risk.py`
- `python/trading_os/api/schemas/system.py`
- `python/trading_os/api/security.py`
- `python/trading_os/api/websocket/__init__.py`
- `python/trading_os/api/websocket/models.py`
- `python/trading_os/api/websocket/snapshot.py`
- `python/trading_os/api/websocket/stream.py`

### `python/trading_os/app` (6)

- `python/trading_os/app/__init__.py`
- `python/trading_os/app/audit.py`
- `python/trading_os/app/config.py`
- `python/trading_os/app/container.py`
- `python/trading_os/app/dependencies.py`
- `python/trading_os/app/main.py`

### `python/trading_os/cli` (7)

- `python/trading_os/cli/__init__.py`
- `python/trading_os/cli/candles.py`
- `python/trading_os/cli/history.py`
- `python/trading_os/cli/main.py`
- `python/trading_os/cli/spreads.py`
- `python/trading_os/cli/terminal.py`
- `python/trading_os/cli/weekly_review.py`

### `python/trading_os/devtools` (3)

- `python/trading_os/devtools/__init__.py`
- `python/trading_os/devtools/gen.py`
- `python/trading_os/devtools/typescript.py`

### `python/trading_os/domain` (78)

- `python/trading_os/domain/__init__.py`
- `python/trading_os/domain/accounts/__init__.py`
- `python/trading_os/domain/accounts/anti_tilt.py`
- `python/trading_os/domain/accounts/models.py`
- `python/trading_os/domain/accounts/profiles.py`
- `python/trading_os/domain/accounts/rules_ledger.py`
- `python/trading_os/domain/autonomy/__init__.py`
- `python/trading_os/domain/autonomy/overview.py`
- `python/trading_os/domain/autonomy/readiness.py`
- `python/trading_os/domain/autonomy/state.py`
- `python/trading_os/domain/events.py`
- `python/trading_os/domain/execution/__init__.py`
- `python/trading_os/domain/execution/agent.py`
- `python/trading_os/domain/execution/commands.py`
- `python/trading_os/domain/execution/idempotency.py`
- `python/trading_os/domain/execution/reasons.py`
- `python/trading_os/domain/execution/records.py`
- `python/trading_os/domain/execution/resolution.py`
- `python/trading_os/domain/execution/retcodes.py`
- `python/trading_os/domain/execution/state.py`
- `python/trading_os/domain/execution/trace.py`
- `python/trading_os/domain/execution/validation.py`
- `python/trading_os/domain/journal/__init__.py`
- `python/trading_os/domain/journal/compliance.py`
- `python/trading_os/domain/journal/models.py`
- `python/trading_os/domain/market/__init__.py`
- `python/trading_os/domain/market/analysis/__init__.py`
- `python/trading_os/domain/market/analysis/aggregate.py`
- `python/trading_os/domain/market/analysis/atr.py`
- `python/trading_os/domain/market/analysis/bias.py`
- `python/trading_os/domain/market/analysis/config.py`
- `python/trading_os/domain/market/analysis/liquidity.py`
- `python/trading_os/domain/market/analysis/market_context.py`
- `python/trading_os/domain/market/analysis/models.py`
- `python/trading_os/domain/market/analysis/pd_arrays.py`
- `python/trading_os/domain/market/analysis/scoring.py`
- `python/trading_os/domain/market/analysis/structure.py`
- `python/trading_os/domain/market/analysis/swings.py`
- `python/trading_os/domain/market/calendar.py`
- `python/trading_os/domain/market/hours.py`
- `python/trading_os/domain/market/models.py`
- `python/trading_os/domain/market/sessions.py`
- `python/trading_os/domain/market/symbols.py`
- `python/trading_os/domain/positions/__init__.py`
- `python/trading_os/domain/positions/models.py`
- `python/trading_os/domain/positions/reconciliation.py`
- `python/trading_os/domain/primitives.py`
- `python/trading_os/domain/risk/__init__.py`
- `python/trading_os/domain/risk/decision.py`
- `python/trading_os/domain/risk/evaluate.py`
- `python/trading_os/domain/risk/exposure.py`
- `python/trading_os/domain/risk/gates.py`
- `python/trading_os/domain/risk/lockout.py`
- `python/trading_os/domain/risk/policy.py`
- `python/trading_os/domain/risk/sizing.py`
- `python/trading_os/domain/risk/state.py`
- `python/trading_os/domain/risk/trading_day.py`
- `python/trading_os/domain/risk/view.py`
- `python/trading_os/domain/strategy/__init__.py`
- `python/trading_os/domain/strategy/evaluation.py`
- `python/trading_os/domain/strategy/intent.py`
- `python/trading_os/domain/strategy/s01/__init__.py`
- `python/trading_os/domain/strategy/s01/bias.py`
- `python/trading_os/domain/strategy/s01/config.py`
- `python/trading_os/domain/strategy/s01/dealing_range.py`
- `python/trading_os/domain/strategy/s01/displacement.py`
- `python/trading_os/domain/strategy/s01/gates.py`
- `python/trading_os/domain/strategy/s01/liquidity.py`
- `python/trading_os/domain/strategy/s01/models.py`
- `python/trading_os/domain/strategy/s01/poi.py`
- `python/trading_os/domain/strategy/s01/preconditions.py`
- `python/trading_os/domain/strategy/s01/proposal.py`
- `python/trading_os/domain/strategy/s01/reconciliation.py`
- `python/trading_os/domain/strategy/s01/stop.py`
- `python/trading_os/domain/strategy/s01/sweep.py`
- `python/trading_os/domain/system/__init__.py`
- `python/trading_os/domain/system/incidents.py`
- `python/trading_os/domain/system/supervision.py`

### `python/trading_os/infrastructure` (29)

- `python/trading_os/infrastructure/__init__.py`
- `python/trading_os/infrastructure/database/__init__.py`
- `python/trading_os/infrastructure/database/migrate.py`
- `python/trading_os/infrastructure/database/migrations/0002_core.sql`
- `python/trading_os/infrastructure/database/migrations/0003_captures_are_data.sql`
- `python/trading_os/infrastructure/database/migrations/manual/drop_capture_window.sql`
- `python/trading_os/infrastructure/database/migrations/manual/drop_legacy_tables.sql`
- `python/trading_os/infrastructure/database/pool.py`
- `python/trading_os/infrastructure/database/repositories/__init__.py`
- `python/trading_os/infrastructure/database/repositories/accounts.py`
- `python/trading_os/infrastructure/database/repositories/events.py`
- `python/trading_os/infrastructure/database/repositories/execution.py`
- `python/trading_os/infrastructure/database/repositories/market.py`
- `python/trading_os/infrastructure/database/repositories/positions.py`
- `python/trading_os/infrastructure/database/repositories/risk.py`
- `python/trading_os/infrastructure/database/repositories/strategy.py`
- `python/trading_os/infrastructure/mt5/__init__.py`
- `python/trading_os/infrastructure/mt5/client.py`
- `python/trading_os/infrastructure/mt5/ea_link.py`
- `python/trading_os/infrastructure/mt5/fake.py`
- `python/trading_os/infrastructure/mt5/mt5_semantics.py`
- `python/trading_os/infrastructure/mt5/protocol.py`
- `python/trading_os/infrastructure/mt5/transport.py`
- `python/trading_os/infrastructure/mt5/wire.py`
- `python/trading_os/infrastructure/mt5/worker.py`
- `python/trading_os/infrastructure/news/__init__.py`
- `python/trading_os/infrastructure/news/fred.py`
- `python/trading_os/infrastructure/security/__init__.py`
- `python/trading_os/infrastructure/security/credentials.py`

### `python/trading_os/mcp` (3)

- `python/trading_os/mcp/__init__.py`
- `python/trading_os/mcp/server.py`
- `python/trading_os/mcp/tools.py`

### `python/trading_os/runtime` (5)

- `python/trading_os/runtime/__init__.py`
- `python/trading_os/runtime/engine.py`
- `python/trading_os/runtime/heartbeat.py`
- `python/trading_os/runtime/scheduler.py`
- `python/trading_os/runtime/supervisor.py`

### `python/trading_os/services` (13)

- `python/trading_os/services/__init__.py`
- `python/trading_os/services/accounts.py`
- `python/trading_os/services/autonomy.py`
- `python/trading_os/services/execution.py`
- `python/trading_os/services/journal.py`
- `python/trading_os/services/market_data.py`
- `python/trading_os/services/news.py`
- `python/trading_os/services/positions.py`
- `python/trading_os/services/readiness.py`
- `python/trading_os/services/reconciliation.py`
- `python/trading_os/services/risk.py`
- `python/trading_os/services/senders.py`
- `python/trading_os/services/strategy.py`

### `python/trading_os/shared` (11)

- `python/trading_os/shared/__init__.py`
- `python/trading_os/shared/errors.py`
- `python/trading_os/shared/events/__init__.py`
- `python/trading_os/shared/events/base.py`
- `python/trading_os/shared/events/dispatcher.py`
- `python/trading_os/shared/ids.py`
- `python/trading_os/shared/logging/__init__.py`
- `python/trading_os/shared/logging/redaction.py`
- `python/trading_os/shared/logging/setup.py`
- `python/trading_os/shared/numbers.py`
- `python/trading_os/shared/time.py`

### `scripts` (1)

- `scripts/start.ps1`

## Modifiés (139)

### `.claude` (1)

- `.claude/CLAUDE.md`

### `(racine)` (7)

- `.env.example`
- `.gitignore`
- `README.md`
- `docker-compose.yml`
- `eslint.config.mjs`
- `package-lock.json`
- `package.json`

### `app/(cockpit)` (14)

- `app/(cockpit)/account/page.tsx`
- `app/(cockpit)/agents/page.tsx`
- `app/(cockpit)/analyse/page.tsx`
- `app/(cockpit)/error.tsx`
- `app/(cockpit)/journal/[brokerPositionId]/page.tsx`
- `app/(cockpit)/journal/page.tsx`
- `app/(cockpit)/loading.tsx`
- `app/(cockpit)/market-context/page.tsx`
- `app/(cockpit)/page.tsx`
- `app/(cockpit)/positions/page.tsx`
- `app/(cockpit)/preflight/page.tsx`
- `app/(cockpit)/risk/page.tsx`
- `app/(cockpit)/settings/page.tsx`
- `app/(cockpit)/setups/page.tsx`

### `app` (2)

- `app/globals.css`
- `app/layout.tsx`

### `components/accounts` (7)

- `components/accounts/connection-chain.tsx`
- `components/accounts/form-controls.tsx`
- `components/accounts/objectives-card.tsx`
- `components/accounts/pending-change.tsx`
- `components/accounts/rules-card.tsx`
- `components/accounts/settings-guard-banner.tsx`
- `components/accounts/settings-history.tsx`

### `components/analyse` (2)

- `components/analyse/breakdown-section.tsx`
- `components/analyse/stat-tile.tsx`

### `components/cockpit` (8)

- `components/cockpit/agent-health-panel.tsx`
- `components/cockpit/audit-feed.tsx`
- `components/cockpit/discipline-gauge.tsx`
- `components/cockpit/economic-calendar.tsx`
- `components/cockpit/lockout-history.tsx`
- `components/cockpit/market-context-panel.tsx`
- `components/cockpit/positions-table.tsx`
- `components/cockpit/session-verdict-banner.tsx`

### `components/shell` (8)

- `components/shell/account-menu.tsx`
- `components/shell/cockpit-shell.tsx`
- `components/shell/kill-switch-button.tsx`
- `components/shell/lockout-ack-banner.tsx`
- `components/shell/lockout-violation-banner.tsx`
- `components/shell/nav.ts`
- `components/shell/news-status.tsx`
- `components/shell/site-header.tsx`

### `components/ui` (9)

- `components/ui/badge.tsx`
- `components/ui/button.tsx`
- `components/ui/card.tsx`
- `components/ui/empty-state.tsx`
- `components/ui/input.tsx`
- `components/ui/panel.tsx`
- `components/ui/progress.tsx`
- `components/ui/sheet.tsx`
- `components/ui/status-pill.tsx`

### `context` (1)

- `context/README.md`

### `context/adr` (12)

- `context/adr/0001-le-process-est-le-produit.md`
- `context/adr/0002-fin-de-la-recherche-d-edge.md`
- `context/adr/0003-stack-et-topologie.md`
- `context/adr/0004-contrats-de-domaine.md`
- `context/adr/0007-risk-engine-point-de-controle.md`
- `context/adr/0009-faits-immuables-rendu-a-la-demande.md`
- `context/adr/0010-execution-agent-mt5.md`
- `context/adr/0012-systeme-de-design-shadcn.md`
- `context/adr/0013-connexion-depuis-l-application.md`
- `context/adr/0014-armement-de-l-agent.md`
- `context/adr/0015-mode-autonome.md`
- `context/adr/README.md`

### `context/architecture` (2)

- `context/architecture/bounded_contexts.md`
- `context/architecture/system_overview.md`

### `context/domain` (1)

- `context/domain/domain_model_mvp.md`

### `context/engineering` (5)

- `context/engineering/analysis_engine_mvp.md`
- `context/engineering/risk_engine_mvp.md`
- `context/engineering/stack.md`
- `context/engineering/standards.md`
- `context/engineering/testing_strategy.md`

### `context/execution` (3)

- `context/execution/protocol.md`
- `context/execution/safety.md`
- `context/execution/state-machine.md`

### `context/frontend` (3)

- `context/frontend/design_system.md`
- `context/frontend/information_architecture.md`
- `context/frontend/visual_reference_ftmo_journal.md`

### `context/governance` (1)

- `context/governance/quality_gates.md`

### `context/infrastructure` (2)

- `context/infrastructure/infrastructure_plan.md`
- `context/infrastructure/runbook.md`

### `context/product` (21)

- `context/product/backlog.md`
- `context/product/catalogue.md`
- `context/product/tools/EA-01-detection-s01.md`
- `context/product/tools/EA-02-observe-taux-accord.md`
- `context/product/tools/EA-03-protocole-execution.md`
- `context/product/tools/EA-04-profils-compte.md`
- `context/product/tools/EA-05-agent-mql5.md`
- `context/product/tools/EA-06-reconciliation.md`
- `context/product/tools/README.md`
- `context/product/tools/S01-strategie-sweep-aligne.md`
- `context/product/tools/T01-calculateur-taille.md`
- `context/product/tools/T02-lockout.md`
- `context/product/tools/T03-gate-news.md`
- `context/product/tools/T04-ticket-pretrade.md`
- `context/product/tools/T05-captures-auto.md`
- `context/product/tools/T06-journal-auto.md`
- `context/product/tools/T07-tracker-conformite.md`
- `context/product/tools/T08-revue-hebdomadaire.md`
- `context/product/tools/T09-checklist-prevol.md`
- `context/product/tools/T12-prop-firm-control-center.md`
- `context/product/tools/T15-serveur-mcp.md`

### `context/project` (3)

- `context/project/roadmap.md`
- `context/project/session-log.md`
- `context/project/state.md`

### `context/realtime` (4)

- `context/realtime/README.md`
- `context/realtime/dashboard_realtime_model.md`
- `context/realtime/event_contracts.md`
- `context/realtime/mt5_wire_protocol.md`

### `context/security` (1)

- `context/security/security_principles.md`

### `context/workflows` (1)

- `context/workflows/development_workflow.md`

### `lib/account-analysis` (3)

- `lib/account-analysis/breakdowns.test.ts`
- `lib/account-analysis/breakdowns.ts`
- `lib/account-analysis/use-account-analysis.ts`

### `lib/accounts` (4)

- `lib/accounts/agent-view.test.ts`
- `lib/accounts/agent-view.ts`
- `lib/accounts/objectives.test.ts`
- `lib/accounts/objectives.ts`

### `lib/cockpit` (2)

- `lib/cockpit/verdict.test.ts`
- `lib/cockpit/verdict.ts`

### `lib/compliance` (2)

- `lib/compliance/labels.ts`
- `lib/compliance/use-compliance-rate.ts`

### `lib` (1)

- `lib/format.ts`

### `lib/journal` (1)

- `lib/journal/use-journal-window.ts`

### `lib/realtime` (4)

- `lib/realtime/provider.tsx`
- `lib/realtime/store.test.ts`
- `lib/realtime/store.ts`
- `lib/realtime/use-persistence-health.ts`

### `lib/security` (1)

- `lib/security/cockpit-token.ts`

### `tools/mt5-execution-agent` (3)

- `tools/mt5-execution-agent/Include/CommandStore.mqh`
- `tools/mt5-execution-agent/README.md`
- `tools/mt5-execution-agent/TradingOsAgent.mq5`

## Renommés

- `backend/src/TradingOs.Persistence/schema.sql` → `python/trading_os/infrastructure/database/migrations/0001_baseline.sql` (R092)
- `lib/contracts/projections.ts` → `lib/cockpit/market-context-view.ts` (R051)

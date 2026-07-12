# Phase 10 - Persistence (PostgreSQL/TimescaleDB)

Status: closed 2026-07-12 (committed `bc48110`; design validated first: Dapper + versioned schema.sql; signals/decisions routed through the hub; full slice scope). **Validated live by the user**: `/health` db ok with thousands of envelopes persisted and 0 dropped; direct SQL over the audit tables working; `/api/audit/recent` returning 200 after the reader fix (Dapper timestamptz→DateTime mapping — the 503 had been hidden by a bare catch; the endpoint now logs and surfaces the real exception, and an integration test guards the read path against the live DB). The persistence precondition before paper trading is met.

## Objective

Durable memory for the platform: every candle, tick, signal, risk decision, command, ack and report is written server-side, with a complete JSONB audit trail — the foundation for replay, the real P&L calendar and Phase 11 backtesting. The realtime path must never block on the database.

## Scope

In scope: TimescaleDB via docker-compose (host port **5433**), idempotent embedded `schema.sql` applied at startup, `PersistenceWriter` (bounded channel, fire-and-forget, drop-with-counters, honest `/health`), pure `PersistenceMapper` (+xUnit), hub `PublishEvent` (strict 2-type whitelist, size cap) making the hub the source of truth for signals/decisions (multi-tab consistent), `GET /api/audit/recent` as read proof.

Deferred (ADR 0011): replay UI, DB-backed P&L calendar, retention/compression, backups, Redis/RabbitMQ, EF Core.

## Acceptance Criteria

- `docker compose up -d` → DB ready; schema applied automatically by the host.
- A live Phase 09 loop run leaves rows in: envelopes, candles, ticks, strategy_signals, risk_decisions, execution_commands, command_acks, execution_reports (queries in `context/backend/persistence.md`).
- DB cut mid-run → cockpit unaffected; `/health` reports `db: down` (+`dbError`); clean resume.
- Multi-tab: signals/decisions identical across tabs (hub rebroadcast).
- Gates: dotnet build+test, lint/tsc/Vitest green.

## Implementation Notes (2026-07-12)

Built: `docker-compose.yml` (timescale/timescaledb:latest-pg17, volume, healthcheck, **5433** — 5432 collided with a locally installed Postgres, diagnosed live via `28P01` against the wrong server), `TradingOs.Persistence` (embedded `schema.sql` — 8 tables incl. 2 hypertables; `PersistenceMapper` pure + 5 xUnit tests; `PersistenceWriter` bounded-channel drain with retry and `PersistenceStatus` incl. `LastError`; `AuditRepository`), Host wiring (writer drained alongside the observer in `GatewayBridgeService`; command/rejection envelopes persisted from the hub; `/health` enriched; `/api/audit/recent`), `CockpitHub.PublishEvent` (whitelist + 64KB cap, persist + rebroadcast), `signalr-client.publish()` (hub round-trip with local-apply fallback).

Gates: dotnet build 0 errors, 19/19 xUnit; lint clean, source `tsc` exit 0, 56 Vitest.

# ADR 0011 - Persistence: TimescaleDB, Dapper + Versioned schema.sql, Hub-Published Signals

## Status

Accepted

## Context

Phases 04–09 produced a complete zero-risk trading loop with no durable memory: every candle, signal, decision, command, ack and report vanished on refresh. The user set persistence as the **precondition before any paper trading**. Decisions validated (2026-07-12): Dapper + versioned `schema.sql` (EF Core reconsidered later), signals/decisions routed through the hub, full slice scope (ticks + candles + 5 typed tables + JSONB audit + a minimal read endpoint).

A structural gap surfaced during design: signals and risk decisions were born in the browser (Phase 09 transitional loop) and never reached the backend — unpersistable, and inconsistent across tabs.

## Decision

1. **Infra**: `docker-compose.yml` at the repo root runs `timescale/timescaledb:latest-pg17` (Postgres + Timescale, one container, named volume). Host port **5433** — deliberately not 5432, which collided with a locally installed Postgres during verification (`28P01` against the wrong server).
2. **Schema**: one idempotent `schema.sql`, embedded in `TradingOs.Persistence` and applied at host startup with retry. Hypertables for `candles` (upsert on symbol/timeframe/open_time) and `ticks`; typed tables `strategy_signals`, `risk_decisions`, `execution_commands`, `command_acks`, `execution_reports`; `envelopes` as the complete JSONB audit trail (every envelope, indexed by type/time/correlation).
3. **Write path**: `PersistenceWriter` — bounded `Channel` (10k), fire-and-forget `Enqueue`, background drain via Dapper/Npgsql. **The realtime path is never coupled to the DB**: when the DB is down or the channel full, events are dropped with counters; `/health` reports `db/persisted/dropped/queued/dbError` honestly.
4. **Mapping**: `PersistenceMapper` is pure (payload JSON → typed row records) and unit-tested without a database; unmapped event types still land in the audit table.
5. **Hub as source of truth for signals**: new `CockpitHub.PublishEvent` with a **strict whitelist** (`strategy.signal.created`, `risk.decision.made`) and a size cap; the hub persists and rebroadcasts to every dashboard. The browser no longer applies its own signals locally (fallback local apply only if the invoke fails) — fixing multi-tab inconsistency and making the flow auditable.
6. **Read proof**: `GET /api/audit/recent` (HTTP is allowed for exports/admin). Real consumers — replay, DB-backed P&L calendar, backtesting — are Phase 11.

## Consequences

- Every run now leaves a queryable audit trail: context → signal → decision → command → ack → SIMULATED report, plus market data for replay.
- DB downtime degrades to counted drops, never to a broken cockpit (verified by smoke test).
- Dapper keeps SQL explicit and Timescale-friendly; EF Core can be introduced later if the C# domain grows — revisit, not a lock-in.
- Local credentials in compose are dev-only; secrets management arrives with real deployments.
- Deferred: retention/compression policies, Redis/RabbitMQ, replay UI, DB-backed P&L, backups.

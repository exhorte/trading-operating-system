# Persistence — Runbook

TimescaleDB stores every envelope (audit) plus typed tables for candles, ticks,
signals, risk decisions, commands, acks and reports. Decision record: ADR 0011.
The realtime path never blocks on the database.

## Start

```powershell
# repo root — requires Docker Desktop running
docker compose up -d          # TimescaleDB on localhost:5433 (NOT 5432)
```

Then start the backend as usual (`dotnet run --project src/TradingOs.Host`):
it applies `schema.sql` automatically (idempotent, retries until the DB is up).

Full chain = the same 3 terminals as before (observer, backend, cockpit in
`backend` mode) + the database container.

## Check

```powershell
# health now includes persistence status
curl http://localhost:5080/health
# → { status, observer, db: ok|down, persisted, dropped, queued, dbError }

# recent audit entries over HTTP (export/admin surface)
curl http://localhost:5080/api/audit/recent?limit=20

# straight SQL
docker exec -it tradingos-timescaledb psql -U tradingos -d tradingos
```

Useful queries:

```sql
SELECT type, count(*) FROM envelopes GROUP BY type ORDER BY 2 DESC;
SELECT * FROM risk_decisions ORDER BY decided_at DESC LIMIT 10;
SELECT c.command_id, c.volume, a.status AS ack, r.status AS report
  FROM execution_commands c
  LEFT JOIN command_acks a ON a.command_id = c.command_id
  LEFT JOIN execution_reports r ON r.command_id = c.command_id
  ORDER BY c.issued_at DESC LIMIT 10;
SELECT time_bucket('1 hour', open_time) AS h, count(*) FROM candles GROUP BY h ORDER BY h DESC;
```

## Configuration

| Setting | Default |
| --- | --- |
| `ConnectionStrings:TradingOs` | `Host=localhost;Port=5433;Database=tradingos;Username=tradingos;Password=tradingos_dev` |
| Compose port mapping | `5433:5432` (5432 was taken by a locally installed Postgres) |

Credentials are local-dev only.

## Behavior when the DB is down

The cockpit and the trading loop keep running untouched; the writer drops
events with counters and `/health` reports `db: down` + `dbError`. On recovery
the writer resumes automatically (dropped events are not replayed — by design
in this slice).

## Scope / not yet

Replay UI, DB-backed P&L calendar, retention/compression policies, backups,
Redis/RabbitMQ — later. Signals/decisions are published through the hub
(`PublishEvent`, whitelisted) so they persist and stay consistent across tabs.

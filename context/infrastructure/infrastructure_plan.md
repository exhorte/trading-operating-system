# Infrastructure Plan

## Local Development Target

- Docker Compose
- PostgreSQL with TimescaleDB extension
- Redis
- RabbitMQ
- Seq
- Prometheus
- Grafana

## Deployment Direction

Initial:

- VPS
- Docker Compose
- Traefik
- Cloudflare

Later:

- managed PostgreSQL
- managed Redis
- container orchestration if needed

## Reliability Concerns

- execution command durability
- websocket session supervision
- realtime message replay or resync
- connection supervision
- audit logs
- backups
- secrets management
- observability

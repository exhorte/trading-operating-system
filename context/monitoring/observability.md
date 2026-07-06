# Observability

## What Must Be Observable

- market data latency
- analysis latency
- signal generation
- risk approvals and rejections
- execution command lifecycle
- MT5 agent connectivity
- websocket connection count
- websocket reconnect count
- stale subscription count
- command acknowledgement latency
- order rejections
- slippage
- drawdown
- daily lockouts
- unexpected errors

## Logs

Logs should answer:

- why was a trade opened?
- why was a trade rejected?
- what market context existed?
- what risk policy applied?
- what execution agent handled it?
- what did the broker return?

## Metrics

- uptime
- tick/candle processing rate
- execution latency
- command failure rate
- account drawdown
- open exposure

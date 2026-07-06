# Phase 03 - MT5 Agent Specification

## Objective

Convert the existing EA knowledge into a specification for an MT5 execution and telemetry agent.

## Source

`../NOTES/Ultimate_ICT_Gold_Scalper_v4.0.mq5`

## Target Role

The MT5 agent must:

- stream ticks/candles/account state to the server
- receive execution commands through a persistent WebSocket/SignalR-compatible channel
- execute broker orders
- report confirmations, rejections, fills, and position updates
- enforce emergency local safety gates
- survive reconnects and terminal restarts

## Non-Goals

- It must not own final strategy decisions.
- It must not run hidden grid or martingale logic.
- It must not silently change risk policy.

## Acceptance Criteria

- Message contracts are documented.
- WebSocket session lifecycle is documented.
- Execution lifecycle is documented.
- Retry, idempotency, and reconciliation are specified.
- Existing EA strategy logic is mapped into reusable concepts.

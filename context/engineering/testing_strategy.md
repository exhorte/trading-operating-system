# Testing Strategy

## Current Stage

Early bootstrap. Testing starts with lint/build verification and grows with domain code.

## Frontend

- lint
- build
- component tests when UI logic becomes meaningful
- visual verification for dashboard layouts

## Domain

- unit tests for risk rules
- unit tests for ICT feature detectors
- deterministic fixtures for candles/ticks
- regression tests for known market scenarios

## Execution

- command idempotency tests
- rejection/retry tests
- reconciliation tests
- simulated MT5 agent tests before live execution

## Strategy

- forward test before live money
- prop firm mode dry-run before challenge account


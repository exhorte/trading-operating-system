# ADR 0001 - Platform Over EA

## Status

Accepted

## Context

The source material includes a sophisticated MQL5 Expert Advisor, but the project goal is broader: a professional algorithmic trading platform with dashboard, risk, analytics, multi-account execution, and reusable ICT/SMC framework.

## Decision

The EA will not be the platform brain.

The platform will own strategy intelligence, risk approval, analytics, and orchestration. MT5 will be treated as the first execution endpoint through an EA agent.

## Consequences

- Server-side domain models must be designed before live execution.
- The EA must be refactored toward telemetry and execution responsibilities.
- Strategy logic extracted from the EA becomes reusable platform knowledge.
- The system can later support cTrader, Interactive Brokers, FIX, or broker REST APIs.


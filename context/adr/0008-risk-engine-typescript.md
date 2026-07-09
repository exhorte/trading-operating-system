# ADR 0008 - Risk Engine In TypeScript (MVP)

## Status

Accepted

## Context

Phase 06 builds the first risk engine (FTMO-style guards). Same question as the ICT/SMC engine (ADR 0006): where does it live for the MVP, given the ASP.NET Core backend is deferred and the observe prototype proved the value of building pure domain engines in TS now. `context/domain/risk_ftmo.md` sets the requirements: risk is a first-class gate, approval precedes execution, no execution when locked, and server-side risk is the source of truth.

The Phase 05 live run exposed a concrete constraint: in observe mode the producer streams account/positions/ticks but **not** trade history — so trades-today and consecutive-losses are genuinely unknown at the edge.

## Decision

Build the risk engine as pure, portable TypeScript in `lib/risk/`, mirroring ADR 0006.

- Imports **only** `lib/domain`; transport-agnostic; re-implementable in .NET later.
- `evaluateRiskState(input): RiskState` runs one pure gate per guard (daily loss, max drawdown, open risk, max trades/day, consecutive losses, spread, session; news is a documented stub until a calendar exists) and derives the posture: **locked** if an account-level hard limit is breached (daily loss, drawdown, max trades, consecutive losses), **warning** at ≥60% of a limit, else **normal**. Entry gates (spread, session, open risk) block new entries without locking the account.
- `evaluateSignalRisk(...): RiskDecision` sizes a trade to the risk-per-trade budget and refuses it when locked or gated. Built and unit-tested now, **not wired** into the signal flow this phase (scope).
- **Unknown inputs are null, not zero.** `RiskState.tradesToday` / `consecutiveLosses` (and the `RiskStatus` read model) became `number | null`; the panel renders "n/a". A gate with unknown input reports open with an "n/a" detail — never a fabricated pass.
- Positions without a stop-loss (`sl <= 0`) are excluded from open-risk (undefined risk) rather than producing a nonsensical `|entry − 0|` figure.
- Projection `toRiskStatusReadModel(state, policy)` merges evaluated usage with policy limits for the panel; both mock and live compute through it.
- Drawdown is **static vs initial balance** for the MVP (trailing deferred). In live, the daily-loss baseline is captured at connect (session-based, not the true broker day). All thresholds are a **hypothesis**, never a validated edge.

## Consequences

- The Risk Status panel and risk KPI tiles are computed in both mock and live, filling the last empty panel; live shows real daily-loss (session)/drawdown/open-risk/spread/session gates and honest "n/a" for trade-history gates.
- Nullable trade counts are a small, honest Phase 02 schema refinement (portable: nullable int in .NET).
- The engine and its future C#/MQL5 counterparts are a documented translation, not an automated guarantee (as ADR 0004/0006).
- Deferred: news calendar, trailing drawdown, profit-target lockout, Friday/Sunday blocks, cooldown, ATR gate, multi-symbol risk sizing (generalise the XAUUSD factor via `SymbolMetadata`), and wiring `evaluateSignalRisk` into the Signal → Risk Review → Execution loop.

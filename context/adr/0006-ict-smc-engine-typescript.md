# ADR 0006 - ICT/SMC Analysis Engine In TypeScript (MVP), Vitest For Domain Tests

## Status

Accepted

## Context

Phase 04 builds the first real domain engine: the ICT/SMC analysis engine that turns candles into a `MarketContextState`. Two questions had to be settled before writing code.

1. **Where does the engine live for the MVP?** The long-term target is ASP.NET Core, but the only running code today is this Next.js/TypeScript repository, and the canonical domain schemas are already portable TypeScript in `lib/domain/` (ADR 0004). Waiting for the .NET backend would block the highest-value core (server intelligence) behind infrastructure that is itself deferred (the WebSocket Gateway waits for ASP.NET Core — 2026-07-08 decision).
2. **How is domain logic verified?** Until now the project verified with lint + build only. `context/engineering/testing_strategy.md` already prescribes "unit tests for ICT feature detectors" and "deterministic fixtures for candles/ticks", but no test runner existed. Phase 01 deliberately shipped zero runtime dependencies and deferred libraries "until their first real use case".

## Decision

Build the ICT/SMC engine as pure, portable TypeScript in `lib/analysis/`, and introduce **Vitest** as the test runner for domain logic.

- `lib/analysis/` imports **only** `lib/domain/` — no `lib/contracts`, `lib/realtime`, or UI. It is transport-agnostic and re-implementable in .NET later, mirroring the ADR 0004 stance for schemas.
- Detectors obey a **no-look-ahead** invariant: a bar's state is computed using only candles up to that bar (swings confirm `lookback` bars late; sweeps/mitigation scan forward only). This protects future backtest integrity (Phase 07).
- The engine emits the canonical `MarketContextState`; a projection in `lib/contracts/projections.ts` (`toMarketContextReadModel`) flattens it to the panel read model. The projection may import both domain and contracts; the engine may not.
- Vitest is a **dev-only** dependency (`"test": "vitest run"`), no runtime bundle impact. Tests live beside the code as `lib/**/*.test.ts`.
- Engine version is `v0.1`. Detector weights and tolerances are **hypotheses, not a validated edge**; nothing here is presented as profitable.

## Consequences

- The engine ships and is testable now, without waiting for the backend; the cockpit's Market Context panel renders computed output (synthetic candles → engine → projection) while staying MOCK-badged.
- First new dependency since Phase 01, justified by an existing documented requirement. Runtime dependencies remain zero.
- The engine and its eventual C#/MQL5 counterparts are a documented translation, not an automated guarantee — the same caveat as ADR 0004.
- MVP scope is bounded (structure, liquidity, FVG/OB, session, bias, weighted score). SMT, news/macro, premium-discount/OTE, and entry/trade-management engines are deferred (see `context/engineering/analysis_engine_mvp.md`).
- Tolerances are raw price units in v0.1; a later revision should derive them from ATR / symbol tickSize so one config generalises across instruments.

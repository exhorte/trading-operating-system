# ADR 0004 - TypeScript Domain Schemas As Canonical Source (MVP)

## Status

Accepted

## Context

Phase 02 requires explicit domain models (account, symbol, candle, trade, market context, risk, signal, execution, realtime envelope) before any backend or execution work. The long-term backend is ASP.NET Core with SignalR, and the first execution agent is an MT5 EA speaking WebSocket messages — three languages (TypeScript, C#, MQL5) will eventually express the same shapes.

The only running code today is the Next.js repository. Introducing a schema IDL (JSON Schema, protobuf, OpenAPI) now would add tooling for zero consumers.

## Decision

Portable TypeScript in `lib/domain/` is the canonical schema source for the MVP.

- Data shapes only: plain interfaces and string-literal unions; no classes, `Date`, or `undefined` — absent values are explicit `null`.
- Timestamps are ISO 8601 UTC strings; JSON is camelCase on the wire; discriminated unions use a string `kind` field; schema evolution rides `Envelope.schemaVersion`.
- `lib/contracts/` is the wire layer (envelope, event/command payloads, dashboard read models) and may depend on `lib/domain/`; the domain depends on nothing.
- `EventPayloadMap` in `lib/contracts/events.ts` must cover every `EventType`, keeping code and `context/realtime/event_contracts.md` in sync.

When the ASP.NET Core backend starts, C# contracts are written to mirror `lib/domain/` (manually or generated), and any divergence is treated as a defect. Revisit a language-neutral IDL only when a second producer exists and drift becomes a real cost.

## Consequences

- No new tooling or runtime dependencies; schemas are immediately consumable by the existing mock client and store.
- The .NET and MQL5 mirrors are a documented translation (see `context/domain/domain_model_mvp.md`), not an automated guarantee — reviews must check both sides until generation exists.
- Dashboard read models stay in `lib/contracts/snapshots.ts` as projections; they are explicitly not domain models.
- The legacy `RiskState` union name is preserved as an alias of domain `RiskMode` until the UI migrates.

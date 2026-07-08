# ADR 0007 - Live Observe Prototype: Browser-Side Translation, Read-Only Python Producer

## Status

Accepted (supersedes, for the prototype only, the 2026-07-08 stance that the WebSocket Gateway waits for the ASP.NET Core backend)

## Context

After Phases 01–04 the cockpit still ran only on mock data. The user asked to validate the full connection path concretely against a real Exness demo account ($1000 virtual). On 2026-07-08 we had decided the WebSocket Gateway waits for the ASP.NET Core backend, which would block any concrete connectivity proof behind infrastructure that is itself deferred.

Two constraints shaped the decision:

- **No credentials.** The MT5 terminal is already authenticated on the user's machine; a local reader attaches to it. No login/password is ever shared or needed.
- **No risk.** A first end-to-end test must not be able to place an order.

## Decision

Build a read-only "observe" prototype that streams real MT5 data into the existing cockpit, with the lean→internal translation running **in the browser** for now.

1. **Producer = Python `MetaTrader5`** (`tools/mt5-observer/mt5_observer.py`), running on the user's Windows machine. It reads account, positions, ticks, and M15 candles and emits lean JSON matching `lib/contracts/mt5-wire.ts` over a local WebSocket. It is **strictly read-only**: `mode:"observe"`, no `order_send`, no trade calls of any kind.
2. **Translation in the browser.** A new `LiveRealtimeClient` (`lib/realtime/live-client.ts`) implements the existing `RealtimeClient` seam, connects to the producer, and translates lean messages into the `CockpitStore` via pure mappers (`lib/realtime/mt5-translate.ts`). Real M15 candles feed the Phase 04 ICT/SMC engine, so the Market Context panel is computed from real data.
3. **Opt-in, mock stays default.** `NEXT_PUBLIC_REALTIME_SOURCE=live` selects the live client locally; unset/`mock` keeps `MockRealtimeClient` for build/CI/prod. The environment badge reads **DEMO** (never MOCK) when live.
4. **Honest gaps.** Risk, signals, execution, daily-drawdown/day-baseline are NOT produced (their engines don't exist yet); the cockpit shows honest empty/zero states for them. This proves the data path only.

## Consequences

- Concrete validation with real demo data, zero broker risk, zero credentials, no backend required.
- **Deliberate, scoped debt:** browser-side translation is a prototype shortcut. The definitive design stays: a server-side .NET WebSocket Gateway translates lean MT5 wire → internal `Envelope<T>` (ADR 0005), and the real agent is the MQL5 EA + sidecar (Phase 03). `LiveRealtimeClient` + `mt5-translate.ts` are throwaway/reference, to be replaced when the backend lands. `mt5-translate.ts` mappers are portable and can inform the .NET gateway.
- The 2026-07-08 gateway decision stands for the *production* path; this ADR only carves out the observe prototype.
- Because the producer is read-only, the emergency-stop and all execution controls remain inert — consistent with "no fake live controls".

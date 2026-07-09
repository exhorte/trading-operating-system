# Risk Engine MVP (v0.1)

Home: `lib/risk/`. Pure FTMO-style risk services; imports only `lib/domain`.
Decision in ADR 0008; requirements in `context/domain/risk_ftmo.md`; model in
`lib/domain/risk.ts`.

> Thresholds are a **hypothesis, not a validated constraint**. v0.1.

## Pipeline

```text
account (balance/equity + baseline) + positions + policy + spread + session
  → gates (one pure fn each)
  → evaluateRiskState() → RiskState (usage + gates + mode + lockout)
  → toRiskStatusReadModel(state, policy) → RiskStatus
  → Risk Status panel + risk KPI tiles
```

`evaluateSignalRisk(signal, state, policy) → RiskDecision` sizes/greenlights a
single trade. Built + tested, **not wired** into the signal flow yet.

## Gates (in scope)

| Gate | Blocks | Kind |
| --- | --- | --- |
| Daily loss | used ≥ `dailyLossLimitPercent` | account lockout |
| Max drawdown | used ≥ `maxDrawdownLimitPercent` (static vs initial balance) | account lockout |
| Max trades/day | `tradesToday ≥ maxTradesPerDay` | account lockout |
| Consecutive losses | `consecutiveLosses ≥ maxConsecutiveLosses` | account lockout |
| Open risk | summed `\|entry−SL\|·vol` > `maxOpenRiskPercent` | entry gate |
| Spread | `spreadPoints > maxSpreadPoints` | entry gate |
| Session | session not trading-enabled | entry gate |
| News | stub (no calendar) — never blocks | entry gate |

Posture: **locked** if any account-lockout gate is breached; **warning** at ≥60%
of a limit; else **normal**. Entry gates block new entries without locking.

## Honesty rules

- **Unknown ≠ zero.** In observe mode the producer has no trade history, so
  `tradesToday` / `consecutiveLosses` are `null` (domain + read model) → panel
  shows "n/a"; those gates report open with an "n/a" detail.
- Positions with no stop (`sl ≤ 0`) are excluded from open-risk (undefined
  risk), not priced as `|entry − 0|`.
- Live daily-loss baseline = equity/balance at connect (session-based, not the
  true broker day); recaptured on reconnect.

## Config

`defaultRiskPolicy(accountId)` — 5% daily, 10% total, 1%/trade, 2% open,
6 trades/day, 3 consecutive, 40 spread points (XAUUSD), 15 min news window.
`WARNING_THRESHOLD = 0.6`.

## Deferred

News calendar, trailing drawdown, profit-target lockout, Friday-evening /
Sunday-open blocks, cooldown between trades, ATR gate, multi-symbol open-risk
(generalise the XAUUSD 100 USD/point factor via `SymbolMetadata`), and wiring
`evaluateSignalRisk` into Signal → Risk Review → Execution.

## Testing

Vitest, colocated `lib/risk/*.test.ts` + `lib/contracts/projections-risk.test.ts`.

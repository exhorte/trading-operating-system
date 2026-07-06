# EA Analysis - Ultimate ICT Gold Scalper v4.0

## Source

`../NOTES/Ultimate_ICT_Gold_Scalper_v4.0.mq5`

## What It Already Does Well

- Uses a main class instead of only global procedural code.
- Defines clear input groups for risk, XAUUSD settings, ICT strategy, sessions, context filters, position management, execution, and logging.
- Implements a setup state machine:
  - idle
  - liquidity swept
  - MSS confirmed
  - wait entry
- Detects liquidity using swing highs/lows and previous day high/low.
- Detects fair value gaps with a 3-candle model.
- Detects basic order blocks with displacement.
- Uses New York session logic and Silver Bullet windows.
- Includes news, rollover, Friday evening, Sunday open, spread, ATR, cooldown, and daily limit filters.
- Calculates lot size from risk, tick value, tick size, volume step, and margin.
- Handles broker stops level and retries recoverable execution errors.
- Tracks positions for break-even, trailing stop, and partial close.
- Persists daily state with global variables.
- Uses `OnTradeTransaction` to update consecutive-loss state.

## Important Limitations For The Platform

- Strategy logic, risk logic, execution, and market analysis still live inside MT5.
- Analysis is M5/XAUUSD-centric.
- It uses EMA HTF bias, but the target platform needs a broader market context model.
- News filtering depends on MT5 calendar availability.
- There is no server-side audit trail or decision replay.
- There is no multi-account orchestration.
- There is no formal command/report protocol.
- There is no separation between reusable ICT features and one strategy.

## How To Use It

Treat the EA as:

- a proven checklist of safety concerns
- a strategy prototype
- a source of MQL5 execution patterns
- a future local safety guard
- a future MT5 connector starting point

Do not treat it as:

- the final brain
- the source of truth for domain architecture
- a direct copy-paste backend design

## Concepts To Extract

- risk input model
- setup state machine
- liquidity sweep detector
- FVG detector
- OB detector
- session filter
- news/spread/ATR gates
- daily lockout
- position sizing formula
- execution retry logic
- position management state
- trade transaction reconciliation

## Refactor Direction

Future MT5 agent should split responsibilities:

- `MarketDataPublisher`
- `AccountStatePublisher`
- `ExecutionCommandReceiver`
- `OrderExecutor`
- `ExecutionReporter`
- `LocalRiskGuard`
- `ConnectionSupervisor`


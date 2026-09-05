# Final Interface Specification

## Product Feel

The interface should feel like a professional trading command center:

- operational
- dense
- calm
- realtime
- risk-first
- explainable

It should combine the discipline of a prop firm risk monitor, the clarity of a trading journal, and the control surface of an execution cockpit.

## App Shell

Desktop shell:

- icon rail: narrow, persistent, module shortcuts
- navigation sidebar: collapsible, labels and sections
- top command bar: page title, filters, account, symbol, environment, realtime status
- main content: grid-based cockpit

Primary navigation:

- Command Center
- Market Context
- Signals
- Positions
- Trades Journal
- Replay
- Risk Monitor
- Execution Agents
- Settings

Top command bar should include:

- environment badge: mock, paper, demo, live
- WebSocket status: connected, reconnecting, stale, disconnected
- active account selector
- symbol selector
- date range
- emergency stop when authorized
- AI assistant entry point as secondary action

## Visual System

Theme:

- dark-first interface
- restrained contrast
- thin borders
- compact panels
- no decorative gradients as primary surfaces

Suggested semantic palette:

- background: near black
- surface: charcoal
- elevated surface: slightly lighter charcoal
- border: soft gray
- primary text: off-white
- muted text: gray
- positive/profit: green
- negative/loss: red
- warning/risk: amber
- info/connection: blue
- accent/AI: restrained violet

Use accent colors sparingly. Green/red/amber should carry trading meaning.

Cards:

- radius 8px or less
- no nested decorative cards
- use cards for KPI blocks, repeated panels, and tool surfaces
- maintain tight padding and strong alignment

Typography:

- compact and readable
- tabular numbers for financial metrics
- large numbers only for critical KPIs
- avoid oversized marketing-style text

## Command Center Layout

First viewport should show the operational state immediately.

Top KPI strip:

- Equity
- Daily P&L
- Daily drawdown
- Total drawdown
- Open risk
- Risk state
- Active positions
- Agent connectivity

Main grid:

- left: live market context and/or main XAUUSD chart preview
- center: active signals and risk gate decisions
- right: execution agent health and account status
- lower section: P&L calendar, open positions, recent execution reports

Risk state must be visible without scrolling.

## Market Context Screen

Purpose:

- explain why the system is bullish, bearish, neutral, locked, or waiting.

Panels:

- symbol/timeframe selector
- bias summary
- structure state: trend, BOS, CHOCH, MSS
- liquidity map
- PD arrays: FVG, OB, breaker, mitigation
- session/news state
- SMT/correlation status
- score breakdown
- chart with overlays

## Signals Screen

Purpose:

- show pending, approved, rejected, expired, and executed strategy signals.

Signal lifecycle:

```text
detected -> scored -> risk_review -> approved/rejected -> commanded -> acknowledged -> reported
```

Columns/cards:

- signal id
- symbol
- strategy
- direction
- score
- market context
- risk decision
- execution status
- expires in

## Positions And Execution Screen

Purpose:

- monitor live exposure and execution state.

Sections:

- open positions
- pending commands
- recent execution reports
- broker/agent errors
- reconciliation state

Every execution command should expose:

- command id
- correlation id
- account
- agent
- symbol
- side
- volume
- SL/TP
- risk approval
- ack status
- broker result

## Trades Journal

Inspired by the trade table reference, but adapted for execution audit and strategy research.

Core columns:

- reviewed
- open date
- close date
- account
- symbol
- side
- net P&L
- R multiple
- status
- initial risk
- net ROI
- strategy
- setup
- session
- mistakes/tags
- execution agent
- duration
- replay link

Table requirements:

- dense rows
- sticky header
- horizontal scroll for many columns
- status chips
- setup chips
- filters
- bulk actions only for non-execution review operations

## Replay Workspace

Future screen for decision replay and post-trade review.

Layout:

- left inspector sidebar: trade, setup, tags, risk, outcome
- top playback bar: symbol, time, play/pause, speed, event markers
- main chart: candles with ICT/SMC overlays
- optional second chart: correlated asset or higher timeframe
- bottom event tape: ticks/candles, signal events, risk decisions, commands, reports

Replay should be able to answer:

- what did the framework see?
- why was the signal created?
- why did risk approve or reject?
- what command was sent?
- what did MT5/broker return?

## Realtime States

Every live panel must handle:

- mock
- connecting
- connected
- reconnecting
- stale
- degraded
- disconnected
- error

Never show a live execution action as available when:

- data is mock
- WebSocket is disconnected
- state is stale
- risk is locked
- execution agent is unhealthy

## Responsive Behavior

Desktop is the primary target.

Tablet:

- sidebar collapses
- main grid becomes two columns
- tables keep horizontal scroll

Mobile:

- read-only monitoring first
- critical KPIs first
- execution controls hidden unless explicitly designed and authorized


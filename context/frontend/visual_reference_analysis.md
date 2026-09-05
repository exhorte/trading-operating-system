# Visual Reference Analysis

## Source Files

The visual inspiration files are stored in `context/templates/`:

- `tradezella-dashboard.webp`
- `reference-dashboard-overview.png`
- `reference-trades-table.png`
- `reference-trade-replay.webp`

Use them as inspiration only. The final interface must have its own identity and must fit this platform's WebSocket-first trading operating system.

## Shared Visual Language

The references share these interface traits:

- dark cockpit theme
- fixed left navigation
- top filter/command bar
- dense metric cards
- green/red financial semantics
- compact charts
- status pills and badges
- calendar heatmap for P&L
- table-first trade review workflow
- replay workspace with chart controls
- secondary AI/action button in the top right

## Dashboard Reference

Observed patterns:

- left icon rail plus expanded navigation sidebar
- page title in top bar
- filters for date/account/data mode
- top row of KPI cards
- large P&L calendar as primary analytics surface
- right-side statistical chart panel
- weekly summary cards beside calendar
- bottom sections for yearly calendar, links, trades, or open positions

Useful for our project:

- create a dashboard command center
- place risk and account state in the first KPI row
- keep calendar analytics, but not as the only primary surface
- add realtime connection status because our platform is WebSocket-first
- add execution agent health because MT5 agents are core

## Trade View Reference

Observed patterns:

- top row KPI summary
- dense trade table with horizontal scrolling
- status chips: win, loss, breakeven
- strategy tags
- mistake/habit tags
- reviewed indicator
- bulk actions and table settings
- sticky pagination/footer

Useful for our project:

- build a trade journal and execution audit table
- include account, symbol, strategy, risk approval, execution agent, command id, R multiple, and market context
- add filters by strategy, account, symbol, session, risk state, and execution outcome

## Trade Replay Reference

Observed patterns:

- full-screen analysis workspace
- left trade detail sidebar
- top playback controls
- split-chart layout
- drawing/chart tools
- speed selector
- bottom time-and-sales/order-flow panel
- trade markers over chart

Useful for our project:

- build a future market replay workspace
- show ICT/SMC overlays: liquidity, FVG, OB, MSS, BOS/CHOCH, entry, SL, TP
- replay both market data and decision events
- keep a synchronized event tape: signal -> risk approval -> command -> ack -> execution report

## What To Avoid

- Do not create a direct TradeZella clone.
- Do not use a purple-heavy one-hue theme.
- Do not make the dashboard feel like a static analytics report only.
- Do not hide risk state below the fold.
- Do not show live trade controls while data is mock or disconnected.


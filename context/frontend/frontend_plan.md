# Frontend Plan

## Purpose

The frontend is the trading cockpit.

It should show:

- account status
- equity curve
- drawdown
- positions
- orders
- risk limits
- ICT/SMC market context
- session/news status
- execution connectivity
- alerts

All live widgets should be designed around realtime subscriptions.

Visual direction is defined in:

- `frontend/visual_reference_analysis.md`
- `frontend/final_interface_spec.md`

## MVP Screens

- Dashboard overview
- Accounts
- Market Context
- Signals
- Positions And Orders
- Risk Monitor
- Execution Agents
- Settings

## UI Direction

- Dense and scannable.
- Professional trading terminal feel.
- Dark-first cockpit inspired by the visual references, without copying their brand or exact layout.
- Clear risk states.
- Risk-first first viewport.
- WebSocket connection state visible in the top command area.
- Execution agent health visible in the operational dashboard.
- No fake live controls.
- Mock data clearly labeled until backend connection exists.
- Connection state visible: connected, reconnecting, stale, disconnected, degraded.
- No REST polling for market-time data.

## MVP Command Center Components

- app shell with icon rail, sidebar, top command bar
- environment badge
- realtime status badge
- KPI strip
- risk status panel
- market context panel
- signal queue
- execution agent panel
- open positions table
- P&L calendar or compact P&L heatmap
- recent execution reports

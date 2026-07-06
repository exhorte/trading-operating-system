# Bounded Contexts

## Market Data

Owns ticks, candles, spreads, sessions, calendar data, and time-series persistence.

## ICT/SMC Analysis

Owns market structure, liquidity, PD arrays, FVG, order blocks, premium/discount, SMT, and context generation.

## Strategy

Owns setup definitions, entry models, signal scoring, and scenario validation.

## Risk

Owns risk policies, prop firm limits, daily drawdown, total drawdown, position sizing, exposure limits, and lockouts.

## Portfolio

Owns accounts, balances, equity, open positions, allocation, account groups, and multi-account replication rules.

## Execution

Owns order commands, routing, MT5/cTrader/FIX connectors, idempotency, broker constraints, and execution reports.

Execution commands and reports are realtime-first messages. They must be idempotent, acknowledged, and auditable.

## Analytics

Owns performance metrics, trade attribution, audit trail, replay, and reports.

## Dashboard

Owns user interaction, visualization, configuration screens, monitoring, and explainability views.

Dashboard data must be modeled as live subscriptions, snapshots, and event updates rather than periodic REST polling.

## Identity And Access

Owns users, roles, permissions, API keys, sessions, and access to accounts/strategies.

# Backtesting Plan

## Purpose

Backtesting validates strategy hypotheses before forward or live trading.

## Requirements

- deterministic candle/tick fixtures
- market context replay
- risk rule simulation
- execution cost modeling
- spread and slippage assumptions
- news/session filters
- trade attribution

## Outputs

- win rate
- expectancy
- max drawdown
- daily drawdown
- average R
- profit factor
- setup quality distribution
- risk violations

## Rule

No live strategy should be promoted without backtest and forward-test evidence.


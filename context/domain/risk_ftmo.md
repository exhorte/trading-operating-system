# FTMO And Prop Firm Risk Context

## Business Goal

The platform should support prop firm style constraints such as FTMO, while remaining useful for normal retail accounts.

Targets from source notes:

- monthly gain hypothesis: 11-15%
- daily max loss below 4-5%
- total loss below 8-10%
- challenge completion hypothesis: 20-30 days for a 100k account

These are not guarantees. They must be validated.

## Hard Risk Principles

- No martingale.
- No dangerous grid.
- No hidden exposure multiplication.
- No trade without explicit stop/invalidation.
- No execution when risk state is locked.

## Required Guards

- max risk per trade
- max daily loss
- max total drawdown
- max daily trades
- max open positions
- max consecutive losses
- max spread
- min/max ATR
- high-impact news block
- session filter
- Friday evening block
- Sunday open block
- cooldown between trades
- profit target lockout

## Platform Requirement

Risk approval should be a separate step before execution:

```text
Signal -> Risk Review -> Execution Command -> Agent Execution
```

The execution agent may enforce emergency local guards, but server-side risk remains the source of truth.


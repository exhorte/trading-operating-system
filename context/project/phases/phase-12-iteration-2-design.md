# Phase 12 Part B — Iteration 2: trigger restricted to New York AM

Status: designed 2026-07-18 (user-specified hypothesis). Discipline: `context/backtesting/diagnostics_workflow.md`, ADR 0013.

## Experimental objective

**One question only: what is the effect of excluding London?** The trigger,
its confirmation, its stop, the target, the score, the Risk Engine, the
BUY/SELL mix — nothing else moves. OOS stays locked.

## Why this hypothesis (iteration-1 evidence)

The session split is the only iteration-1 finding that meets all four rule-3
criteria (strong, explainable, train+validation-consistent, n ≥ 30):

| session | train | validation |
| --- | --- | --- |
| new_york_am | n=270, **+0.23R** | n=76, **+0.21R** |
| london | n=226, **−0.22R** | n=55, **−0.36R** |

Mechanical explanation (stated before the run, per the discipline): the setup
forms on Asia-session liquidity and displacement during London, but resolution
— the actual draw on liquidity — concentrates in the NY AM window; London
retests are early and get chopped. This is a plausible ICT reading, **but it
remains a post-hoc selection out of ~15 dimensions**: the multi-comparison
risk is real, and only the campaign-end read on a *fresh* holdout (the current
OOS is compromised by the leak) can settle it.

## Design

The restriction lives in the **strategy layer** — the Risk Engine stays a risk
engine (standing rule). `TriggerConfig` gains:

```ts
/** Sessions the strategy may trade; null = all (iteration-1 behavior). */
allowedSessions: TradingSession[] | null;
```

`evaluateTrigger` gates on `context.session` before anything else. Default
`null` keeps iteration 1 byte-identical; the iteration-2 run passes
`["new_york_am"]` via a runner flag:

```powershell
npx tsx scripts/backtest.ts --strategy trigger --sessions new_york_am
```

The flag is recorded in the run's `config` JSON (runs stay unambiguous). The
risk engine's own session gate is untouched and still runs — London signals
are now never *emitted* rather than emitted-and-approved.

## Pre-registered prediction — this run is also a pipeline invariant test

The trigger is stateless and each trade is simulated independently (no account
state: fixed balance, empty positions, `tradesToday` null). Removing London
signals therefore **cannot change any NY AM trade**. Expected result, stated
a priori:

> Iteration 2 ≡ the `session=new_york_am` buckets of `bt-mrp973lv-965814cc`,
> bit-identical: train n=270 / +0.23R, validation n=76 / +0.21R.

- **If it matches**: the hypothesis is confirmed as arithmetic, the run id
  becomes the auditable record, and the decision moves to "is +0.21R on
  validation n=76 enough to proceed" (with costs still unmodeled).
- **If it deviates**: a hidden coupling exists in the pipeline (seq/window
  drift, session boundary bug) — that is a **defect to fix**, not a result to
  interpret.

n=76 on validation is above the 30-trade floor but not comfortable; the
campaign-end fresh-holdout read remains the arbiter, and costs remain
unmodeled — nothing here promotes to paper trading.

## Not changed (constraint checklist)

- no score filter;
- no Risk Engine change (its session gate keeps its config);
- no target change (2R);
- no confirmation change (middle);
- no stop change (structural invalidation + 0.5 ATR, floor 1 tick);
- no BUY/SELL filter;
- OOS locked; fresh holdout reserved for campaign end.

## Checklist

1. `TriggerConfig.allowedSessions` (+ default null) — `lib/strategy/config.ts`.
2. Session gate first in `evaluateTrigger` — `lib/strategy/trigger.ts`.
3. Tests: blocked session → null; allowed session → fires; null → all fire.
4. Runner `--sessions` CSV flag → config + run-config JSON.
5. Gates (lint, tsc, Vitest), then the run (user, needs DB up):
   train read → validation read → record run id in the brain.

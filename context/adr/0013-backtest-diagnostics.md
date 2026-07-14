# ADR 0013 - Backtest Diagnostics: Feature Capture, Chronological Splits, Locked OOS

## Status

Accepted

## Context

Phase 11's baseline said "no edge" (−0.02R over 1,261 trades) but not WHERE the losses come from: `backtest_trades` didn't store the signal's market context, and the 1,948 rejections weren't recorded at all. The user specified Phase 12 as diagnose-before-changing-rules, with segmented analyses over 13 dimensions and a train/validation/out-of-sample discipline against overfitting.

## Decision

1. **Feature capture at signal time** — `backtest_trades.features jsonb`, frozen by the runner. Stable key set (the report depends on it): `session`, `bias`, `sideVsBias` (`with`|`counter`), `structure` (`bos`|`choch`|`none`), `stopDistance`, `scoreComponents` (label→score), `fvgAligned`/`fvgInside`, `obAligned`/`obInside`, `liqKinds` (string[]). Day-of-week/month derive from `signal_time`. The stub's planned RR is constant (2.0) by construction, so RR segmentation is replaced by stop-distance buckets — stated in the report.
2. **Rejections table** — `backtest_rejections` (seq, time, side, score, session, reason, split): the "risk gates" dimension is analyzed on refusals, since approved trades had open gates by definition.
3. **Chronological 60/20/20 splits**, time-based (not trade-count-based, so trade density can't leak), boundaries stored in the run config, every trade/rejection tagged. Refinement decisions are made on TRAIN, confirmed on VALIDATION.
4. **OOS is locked by tooling**: `backtest-report.ts` hides the OOS split unless `--unlock-oos` is passed — to be used ONCE at the end of the refinement campaign. Reading it earlier turns it into a second validation set.
5. **Report** — `scripts/backtest-report.ts <runId>`: rejection breakdown + per-dimension tables (worst buckets first — it's a loss hunt) per split, console + `backtest-reports/<runId>.md` (gitignored artifact). Buckets with n < 30 are flagged `⚠ low n`; with 13+ dimensions, only strong, explainable, train+validation-consistent effects may drive changes.
6. Pure aggregation in `lib/backtest/segments.ts` (tested); the runner gained `--from/--to` so refinement iterations can run on the train window only.

## First findings (enriched baseline `bt-mrkz8r44-d57578d8`, deterministic re-run of the Phase 11 baseline)

- **Consistent across train AND validation** (actionable candidates):
  - `sideVsBias = counter` loses in both (train −0.19R / n=189; val −0.14R / n=63) — the stub's deliberate counter-trend probes are pure noise injection, mechanically explainable.
  - Low scores lose in both (score 3: −0.23R / −0.49R); score 6 is the only bucket positive in both — the engine's own confluence measure is directionally informative.
  - Diagnostic (not a filter): 1–2-bar losses dominate (train −0.34R / n=316; val −0.23R / n=188) — entries die immediately; stop placement/entry timing is the structural weakness.
- **Train-only mirages killed by validation** (would have been overfit without the split): side (buy>sell reverses), structure (BOS>CHOCH reverses), stopDistance (6.5 best→worst), session (NY edge vanishes), bias direction.
- Rejections: 100% session-filter refusals (Asia/NY-PM/off-session) — gates behaved as configured; no risk-gate anomaly.

## Consequences

- Rule changes are now hypothesis-driven and survivable-by-validation, or they don't ship.
- Old (feature-less) runs remain readable; the report flags them and advises a re-run.
- Deferred still: costs, account-level simulation, paper trading — gated on an improved raw R distribution.

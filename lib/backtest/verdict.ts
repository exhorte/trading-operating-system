/**
 * Pre-registered verdict classifier for the virgin-holdout read (Phase 13).
 * Pure and deterministic — the bootstrap is seeded, so the verdict is
 * reproducible bit-for-bit from the same trades.
 *
 * The bar was fixed by the user on 2026-07-18, BEFORE any holdout number
 * exists. Operationalizations flagged for review before the run:
 *  - "bootstrap interval too wide" → width (p97.5 − p2.5) > 0.40R;
 *  - month concentration only evaluated when net cumulative R > 0
 *    (a share of a negative total is meaningless);
 *  - side-expectancy rules apply to sides with n ≥ minSideN.
 */

export type VerdictOutcome = "PASS" | "INCONCLUSIVE" | "FAIL";

export interface VerdictTrade {
  netR: number;
  side: "buy" | "sell";
  /** "YYYY-MM" from the signal time (UTC). */
  month: string;
}

export interface VerdictCriteria {
  minTrades: number;
  minSideN: number;
  /** PASS needs net expectancy ≥ this. */
  passNetExpectancy: number;
  /** FAIL if a populated side's expectancy ≤ this. */
  sideFailExpectancy: number;
  /** PASS needs max positive month share ≤ this (of a positive total). */
  monthConcentrationMax: number;
  /** PASS needs bootstrap p2.5 of net expectancy > this. */
  bootstrapLowerBound: number;
  /** INCONCLUSIVE if the 95% interval is wider than this. */
  bootstrapMaxWidth: number;
  bootstrapIterations: number;
  bootstrapSeed: number;
}

/** The user's bar, verbatim where quantified; proposals marked in comments. */
export const VERDICT_CRITERIA_2026_07_18: VerdictCriteria = {
  minTrades: 100,
  minSideN: 30,
  passNetExpectancy: 0.05,
  sideFailExpectancy: -0.1,
  monthConcentrationMax: 0.5,
  bootstrapLowerBound: -0.05,
  bootstrapMaxWidth: 0.4, // proposed operationalization of "too wide" — review
  bootstrapIterations: 10_000,
  bootstrapSeed: 20_260_718, // fixed → verdict reproducible
};

export interface VerdictMetrics {
  n: number;
  netExpectancyR: number;
  netCumulativeR: number;
  buyN: number;
  sellN: number;
  buyExpectancyR: number | null;
  sellExpectancyR: number | null;
  /** Largest single-month share of a POSITIVE net cumulative R; null if ≤ 0. */
  maxMonthShare: number | null;
  maxMonth: string | null;
  bootstrapLower: number;
  bootstrapUpper: number;
  bootstrapWidth: number;
}

export interface VerdictResult {
  outcome: VerdictOutcome;
  reasons: string[];
  metrics: VerdictMetrics;
}

function round4(n: number): number {
  return Math.round(n * 10_000) / 10_000;
}

/** mulberry32 — small deterministic PRNG; good enough for resampling. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Seeded percentile bootstrap of the mean of `values`. */
export function bootstrapMeanCi(
  values: number[],
  iterations: number,
  seed: number,
): { lower: number; upper: number } {
  if (values.length === 0) {
    return { lower: 0, upper: 0 };
  }
  const rand = mulberry32(seed);
  const means = new Array<number>(iterations);
  for (let i = 0; i < iterations; i += 1) {
    let sum = 0;
    for (let k = 0; k < values.length; k += 1) {
      sum += values[Math.floor(rand() * values.length)];
    }
    means[i] = sum / values.length;
  }
  means.sort((a, b) => a - b);
  const at = (p: number) => means[Math.min(iterations - 1, Math.max(0, Math.floor(p * iterations)))];
  return { lower: at(0.025), upper: at(0.975) };
}

export function classifyVerdict(
  trades: VerdictTrade[],
  criteria: VerdictCriteria,
): VerdictResult {
  const n = trades.length;
  const netCum = trades.reduce((s, t) => s + t.netR, 0);
  const netExp = n > 0 ? netCum / n : 0;

  const buys = trades.filter((t) => t.side === "buy");
  const sells = trades.filter((t) => t.side === "sell");
  const buyExp = buys.length > 0 ? buys.reduce((s, t) => s + t.netR, 0) / buys.length : null;
  const sellExp = sells.length > 0 ? sells.reduce((s, t) => s + t.netR, 0) / sells.length : null;

  const byMonth = new Map<string, number>();
  for (const t of trades) {
    byMonth.set(t.month, (byMonth.get(t.month) ?? 0) + t.netR);
  }
  let maxMonthShare: number | null = null;
  let maxMonth: string | null = null;
  if (netCum > 0) {
    for (const [month, r] of byMonth) {
      const share = r / netCum;
      if (maxMonthShare === null || share > maxMonthShare) {
        maxMonthShare = share;
        maxMonth = month;
      }
    }
  }

  const ci = bootstrapMeanCi(
    trades.map((t) => t.netR),
    criteria.bootstrapIterations,
    criteria.bootstrapSeed,
  );
  const width = ci.upper - ci.lower;

  const metrics: VerdictMetrics = {
    n,
    netExpectancyR: round4(netExp),
    netCumulativeR: round4(netCum),
    buyN: buys.length,
    sellN: sells.length,
    buyExpectancyR: buyExp === null ? null : round4(buyExp),
    sellExpectancyR: sellExp === null ? null : round4(sellExp),
    maxMonthShare: maxMonthShare === null ? null : round4(maxMonthShare),
    maxMonth,
    bootstrapLower: round4(ci.lower),
    bootstrapUpper: round4(ci.upper),
    bootstrapWidth: round4(width),
  };

  // --- FAIL first: any single failure condition ends it. ---
  const failReasons: string[] = [];
  if (n > 0 && netExp <= 0) {
    failReasons.push(`net expectancy ${metrics.netExpectancyR}R <= 0`);
  }
  if (buys.length >= criteria.minSideN && buyExp !== null && buyExp <= criteria.sideFailExpectancy) {
    failReasons.push(`BUY (n=${buys.length}) expectancy ${metrics.buyExpectancyR}R <= ${criteria.sideFailExpectancy}R`);
  }
  if (sells.length >= criteria.minSideN && sellExp !== null && sellExp <= criteria.sideFailExpectancy) {
    failReasons.push(`SELL (n=${sells.length}) expectancy ${metrics.sellExpectancyR}R <= ${criteria.sideFailExpectancy}R`);
  }
  if (maxMonthShare !== null && maxMonthShare > criteria.monthConcentrationMax) {
    failReasons.push(
      `month ${maxMonth} contributes ${round4(maxMonthShare * 100)}% of net cumulative R (> ${criteria.monthConcentrationMax * 100}%)`,
    );
  }
  if (failReasons.length > 0) {
    return { outcome: "FAIL", reasons: failReasons, metrics };
  }

  // --- PASS: every criterion must hold. ---
  const passMisses: string[] = [];
  if (n < criteria.minTrades) {
    passMisses.push(`n=${n} < ${criteria.minTrades}`);
  }
  if (netExp < criteria.passNetExpectancy) {
    passMisses.push(`net expectancy ${metrics.netExpectancyR}R < ${criteria.passNetExpectancy}R`);
  }
  if (netCum <= 0) {
    passMisses.push(`net cumulative ${metrics.netCumulativeR}R <= 0`);
  }
  if (buys.length < criteria.minSideN) {
    passMisses.push(`BUY n=${buys.length} < ${criteria.minSideN}`);
  }
  if (sells.length < criteria.minSideN) {
    passMisses.push(`SELL n=${sells.length} < ${criteria.minSideN}`);
  }
  if (ci.lower <= criteria.bootstrapLowerBound) {
    passMisses.push(`bootstrap p2.5 ${metrics.bootstrapLower}R <= ${criteria.bootstrapLowerBound}R`);
  }
  if (width > criteria.bootstrapMaxWidth) {
    passMisses.push(`bootstrap interval width ${metrics.bootstrapWidth}R > ${criteria.bootstrapMaxWidth}R`);
  }
  if (passMisses.length === 0) {
    return { outcome: "PASS", reasons: ["all pre-registered criteria met"], metrics };
  }
  return { outcome: "INCONCLUSIVE", reasons: passMisses, metrics };
}

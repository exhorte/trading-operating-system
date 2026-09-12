/**
 * Account-level configuration types (ADR 0010, EA-04): what makes an FTMO
 * challenge and a real account behave differently without a single
 * `if (ftmo)` in the code. None of this decides anything (ADR 0007) — it
 * supplies bounds the Risk Engine enforces and the agent validates locally
 * (context/execution/safety.md, implemented in EA-05).
 *
 * `RiskPolicy` (lib/domain/risk.ts) already IS the per-trade/daily/drawdown
 * risk profile — it is reused here, not duplicated under a second name.
 */

import type { AccountKind } from "@/lib/domain/account";
import type { AccountId, AgentId, SymbolCode } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";

/**
 * Expected round-trip cost and the account's cost-gate threshold (S01
 * "porte de coût" — lib/setup/gates.ts::ViabilityGateInput). The gate itself
 * always reads the LIVE spread ("lu en direct au moment de la décision",
 * fiche S01); `expectedSpreadBySymbol` is informational, never fed into the
 * gate in place of a live read.
 */
export interface CostModel {
  /** Commission in account currency, per 1.0 lot, round trip. */
  commissionPerLotRoundTrip: number;
  /** Expected spread by symbol, price units — display/documentation only. */
  expectedSpreadBySymbol: Partial<Record<SymbolCode, number>>;
  /** `c` threshold above which S01 refuses a setup (fiche S01: provisional 0.25). */
  costThreshold: number;
}

/**
 * The execution mode ladder (ADR 0010): observe -> paper -> confirm.
 * `"auto"` is not a value this type can express — the type is the guard,
 * not a convention. Reaching `"auto"` requires an ADR that supersedes 0010,
 * not a fourth string literal added here.
 */
export type ExecutionMode = "observe" | "paper" | "confirm";

/**
 * Bounds the agent's local barriers enforce (context/execution/safety.md) —
 * a last line of defense, never a decision (ADR 0007). Populated here as
 * configuration; enforced in MQL5 by EA-05.
 */
export interface ExecutionProfile {
  mode: ExecutionMode;
  allowedSymbols: SymbolCode[];
  maxVolumePerOrder: number;
  maxOpenPositions: number;
  maxSpreadPoints: number;
}

/** Isolation per account (ADR 0010): one terminal, one agent instance, one
 *  magic number — never shared across accounts. */
export interface AccountEnvironment {
  terminal: string;
  agentId: AgentId;
  magicNumber: number;
}

/**
 * Everything the platform needs to treat one account correctly. Deliberately
 * excludes live figures (balance, equity) — those come from the realtime
 * `AccountSummary` read model, never duplicated into static configuration.
 */
export interface AccountProfile {
  accountId: AccountId;
  kind: AccountKind;
  riskPolicy: RiskPolicy;
  costModel: CostModel;
  executionProfile: ExecutionProfile;
  environment: AccountEnvironment;
}

/**
 * Account configuration (ADR 0010, EA-04): profiles, cost model, FTMO/real
 * concrete configurations. lib/domain/account.ts (TradingAccount, AccountKind)
 * remains the only account domain model — this module configures it, it
 * does not duplicate it.
 */

export * from "./types";
export * from "./cost-model";
export * from "./ftmo";
export * from "./real";
export * from "./registry";

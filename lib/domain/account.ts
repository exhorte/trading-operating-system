/**
 * Account models. A TradingAccount is the platform's own aggregate (risk
 * policy owner, audit subject); the BrokerAccount describes the external
 * broker/prop-firm account it maps to.
 */

import type { AccountId, UtcTimestamp } from "./primitives";

export type AccountKind = "prop_challenge" | "prop_funded" | "demo" | "live" | "paper";

/** External broker/prop account identity and static limits. */
export interface BrokerAccount {
  /** Broker-side login/number, e.g. MT5 account number as string. */
  brokerAccountNumber: string;
  broker: string;
  server: string;
  currency: string;
  leverage: number;
}

/** Platform-side account aggregate; the unit of risk policy and audit. */
export interface TradingAccount {
  accountId: AccountId;
  label: string;
  kind: AccountKind;
  brokerAccount: BrokerAccount;
  /** Reference balance used for drawdown percentages (e.g. FTMO initial balance). */
  initialBalance: number;
  balance: number;
  equity: number;
  createdAt: UtcTimestamp;
  updatedAt: UtcTimestamp;
}

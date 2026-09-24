/**
 * Which firm an MT5 terminal belongs to, read from the broker name it
 * reports (T12).
 *
 * The cockpit never connects to a broker itself: the observer attaches to
 * whatever terminal the trader has logged into (`mt5.initialize()`, no
 * credentials) and forwards that terminal's `company` string as
 * `account.broker`. Recognising the firm from that string is what lets the
 * right rules apply without a single account number entering the code
 * (`.claude/CLAUDE.md`: « Aucun identifiant de compte n'est jamais demandé,
 * stocké ou partagé »).
 *
 * Deliberately a substring match on a text and nothing more. No FTMO
 * terminal has ever been connected to this system, so the exact `company`
 * string FTMO reports has not been observed — assuming more than "it
 * contains FTMO" would be a guess. Since T12 incrément 2 the text is a
 * setting (Settings screen, `brokerMatch`): the day the real string turns out
 * not to contain it, the trader fixes it there instead of waiting for a
 * commit, and the change goes through the same anti-tilt rule as any other.
 */

export type Firm = "ftmo" | "exness";

/** Checked in this order: the first firm whose text appears wins. */
export const FIRMS: readonly Firm[] = ["ftmo", "exness"];

/** The text searched, case-insensitively, in the broker name — per firm. */
export type BrokerMatchers = Record<Firm, string>;

export const DEFAULT_BROKER_MATCHERS: BrokerMatchers = { ftmo: "ftmo", exness: "exness" };

export function detectFirm(
  broker: string | null | undefined,
  matchers: BrokerMatchers = DEFAULT_BROKER_MATCHERS,
): Firm | null {
  if (!broker) {
    return null;
  }
  const name = broker.toLowerCase();
  return (
    FIRMS.find((firm) => {
      const needle = matchers[firm].trim().toLowerCase();
      return needle.length > 0 && name.includes(needle);
    }) ?? null
  );
}

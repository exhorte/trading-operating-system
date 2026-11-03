-- 0004 weekly anchor — the equity the week started with (ADR 0019: weekly loss limit of 10 %).
--
-- Same shape and same rules as `trading_day_anchors`: one row per account and per week, `starts_at_utc` being Monday
-- 00:00 in the broker's server time (the offset measured on the MT5 terminal, never hard-coded). `week_start_equity` is
-- filled in once, when it is known, and never overwritten: NULL means unknown, never zero. A new week adds a row; a row
-- is never rewritten, so a change of week cannot erase a loss already taken.
--
-- Additive and idempotent: creates a table and an index, touches nothing that exists.

CREATE TABLE IF NOT EXISTS trading_week_anchors (
    account_id        text NOT NULL,
    starts_at_utc     timestamptz NOT NULL,
    week_start_equity double precision,
    PRIMARY KEY (account_id, starts_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_trading_week_anchors_account_time
    ON trading_week_anchors (account_id, starts_at_utc DESC);

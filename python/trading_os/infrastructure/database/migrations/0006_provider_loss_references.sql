-- 0006 provider loss references — the balance recorded at 00:00 of each provider day (ADR 0036).
--
-- A prop contract builds its loss floors from the balance recorded at the start of a day in a named zone (FTMO: 00:00 Central European
-- (Summer) Time): the daily floor from today's, the trailing maximum from the highest of them all. They must survive a restart, a
-- disconnection, a change of settings or of strategy — so they are rows, written once and never rewritten.
--
-- Append-only by construction: a reference is inserted with ``ON CONFLICT DO NOTHING``, so the first one recorded for a day stays, and no
-- statement of the core updates or deletes one. ``source`` says whether it was observed at the day's start or rebuilt later from the
-- deal history (a rebuilt balance is as good as an observed one, but it says what it is).
--
-- Additive and idempotent: creates a table and an index, touches nothing that exists.

CREATE TABLE IF NOT EXISTS provider_loss_references (
    account_id        text             NOT NULL,
    local_date        date             NOT NULL,
    timezone          text             NOT NULL,
    reference_balance double precision NOT NULL,
    recorded_at       timestamptz      NOT NULL,
    source            text             NOT NULL CHECK (source IN ('observed', 'reconstructed')),
    rule_set_id       text             NOT NULL,
    PRIMARY KEY (account_id, local_date)
);
CREATE INDEX IF NOT EXISTS idx_provider_loss_references_account_date
    ON provider_loss_references (account_id, local_date DESC);

-- 0005 strategy evaluations — what every strategy other than S01 saw, proposed or not (ADR 0024).
--
-- `setup_proposals` stays S01's table: EA-02 (agreement between machine and trader) reads it, and its key (symbol, event_at) says
-- nothing about who evaluated. A second strategy evaluating the same candle would collide with it, and replacing a primary key is not
-- an additive change. So the other strategies write here, keyed by who they are. Same columns, same meaning (ADR 0011).
--
-- Additive and idempotent: creates a table and an index, touches nothing that exists.

CREATE TABLE IF NOT EXISTS strategy_evaluations (
    strategy_id       text NOT NULL,
    symbol            text NOT NULL,
    event_at          timestamptz NOT NULL,
    status            text NOT NULL CHECK (status IN ('proposed', 'blocked')),
    stage             text,
    detail            text,
    side              text,
    swept_level_kind  text,
    swept_level_price double precision,
    entry_price       double precision,
    stop_loss         double precision,
    take_profit       double precision,
    cost_ratio        double precision,
    risk_reward_ratio double precision,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, symbol, event_at)
);
CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_time ON strategy_evaluations (event_at DESC);

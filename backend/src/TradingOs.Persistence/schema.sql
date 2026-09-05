-- TradingOS persistence schema v1. Idempotent: safe to run at every
-- host startup. Timescale hypertables for time series; typed tables for the
-- audit-grade entities; a JSONB envelopes table as the complete audit trail.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Full audit trail: every envelope that crossed the backend.
CREATE TABLE IF NOT EXISTS envelopes (
    message_id     text PRIMARY KEY,
    correlation_id text NOT NULL,
    type           text NOT NULL,
    source         text NOT NULL,
    sent_at        timestamptz NOT NULL,
    payload        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_envelopes_type_time ON envelopes (type, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_envelopes_correlation ON envelopes (correlation_id);

-- Market data (hypertables).
CREATE TABLE IF NOT EXISTS candles (
    symbol    text NOT NULL,
    timeframe text NOT NULL,
    open_time timestamptz NOT NULL,
    open      double precision NOT NULL,
    high      double precision NOT NULL,
    low       double precision NOT NULL,
    close     double precision NOT NULL,
    volume    double precision NOT NULL,
    closed    boolean NOT NULL,
    PRIMARY KEY (symbol, timeframe, open_time)
);
SELECT create_hypertable('candles', 'open_time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ticks (
    symbol text NOT NULL,
    ts     timestamptz NOT NULL,
    bid    double precision NOT NULL,
    ask    double precision NOT NULL
);
SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks (symbol, ts DESC);

-- Signal → Risk Review → Execution audit entities.
CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id   text PRIMARY KEY,
    strategy_id text NOT NULL,
    symbol      text NOT NULL,
    side        text NOT NULL,
    entry_price double precision NOT NULL,
    stop_loss   double precision NOT NULL,
    take_profit double precision NOT NULL,
    score       integer NOT NULL,
    max_score   integer NOT NULL,
    context     text NOT NULL,
    created_at  timestamptz NOT NULL,
    expires_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    approval_id     text PRIMARY KEY,
    signal_id       text NOT NULL,
    account_id      text NOT NULL,
    approved        boolean NOT NULL,
    approved_volume double precision,
    reason          text NOT NULL,
    gates           jsonb NOT NULL,
    decided_at      timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_signal ON risk_decisions (signal_id);

CREATE TABLE IF NOT EXISTS execution_commands (
    command_id       text PRIMARY KEY,
    signal_id        text,
    account_id       text NOT NULL,
    agent_id         text NOT NULL,
    risk_approval_id text NOT NULL,
    symbol           text NOT NULL,
    side             text NOT NULL,
    order_type       text NOT NULL,
    volume           double precision NOT NULL,
    stop_loss        double precision NOT NULL,
    take_profit      double precision NOT NULL,
    issued_at        timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS command_acks (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    command_id  text NOT NULL,
    agent_id    text NOT NULL,
    status      text NOT NULL,
    reason      text,
    received_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_command_acks_command ON command_acks (command_id);

CREATE TABLE IF NOT EXISTS execution_reports (
    report_id   text PRIMARY KEY,
    command_id  text NOT NULL,
    account_id  text NOT NULL,
    agent_id    text NOT NULL,
    symbol      text NOT NULL,
    side        text NOT NULL,
    status      text NOT NULL,
    detail      text NOT NULL,
    reported_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_reports_command ON execution_reports (command_id);

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

-- T04: pre-trade tickets. No commandId exists for a manual trade (this repo
-- has no order-sending path), so matched_position_id/matched_trade_id start
-- NULL and stay NULL until T06 reconciles them against positions/trades —
-- never written by the ticket itself.
CREATE TABLE IF NOT EXISTS pretrade_tickets (
    ticket_id           text PRIMARY KEY,
    account_id          text NOT NULL,
    symbol              text NOT NULL,
    setup               text NOT NULL,
    bias                text NOT NULL,
    entry_price         double precision NOT NULL,
    stop_loss           double precision NOT NULL,
    invalidation        double precision NOT NULL,
    confidence          smallint NOT NULL CHECK (confidence BETWEEN 1 AND 5),
    take_profit         double precision,
    target_volume       double precision,
    target_risk_usd     double precision,
    created_at          timestamptz NOT NULL,
    matched_position_id text,
    matched_trade_id    text
);
CREATE INDEX IF NOT EXISTS idx_pretrade_tickets_created ON pretrade_tickets (created_at DESC);

-- T02a: trading-day anchor, resolved from the MT5 terminal's server-UTC
-- offset (never 00:00 UTC, never hardcoded — see TradingDayAnchor.cs).
-- day_start_equity is filled in later, once the live equity stream confirms
-- it (NULL means unknown, never zero, until then).
CREATE TABLE IF NOT EXISTS trading_day_anchors (
    account_id       text NOT NULL,
    starts_at_utc    timestamptz NOT NULL,
    day_start_equity double precision,
    PRIMARY KEY (account_id, starts_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_trading_day_anchors_account_time
    ON trading_day_anchors (account_id, starts_at_utc DESC);

-- T02a: one row per position actually opened (brokerPositionId first seen),
-- detected client-side from real positions.snapshot diffs. tradesToday is a
-- COUNT of these since the current day anchor — no P&L needed for this gate.
CREATE TABLE IF NOT EXISTS position_opens (
    account_id          text NOT NULL,
    broker_position_id  text NOT NULL,
    opened_at           timestamptz NOT NULL,
    PRIMARY KEY (account_id, broker_position_id)
);
CREATE INDEX IF NOT EXISTS idx_position_opens_account_time
    ON position_opens (account_id, opened_at DESC);

-- T02a: the lockout ledger. "Currently locked" is read from here — never
-- re-derived purely from live gate evaluation, which a missing event or a
-- shifted day boundary could otherwise silently undo.
CREATE TABLE IF NOT EXISTS risk_lockouts (
    lockout_id  text PRIMARY KEY,
    account_id  text NOT NULL,
    reason      text NOT NULL,
    since       timestamptz NOT NULL,
    -- NULL = requires manual/next-day clearance (daily loss, max trades,
    -- kill switch). Set = auto-expires (T02b's 30-min consecutive-loss pause).
    until       timestamptz,
    cleared_at  timestamptz,
    cleared_by  text  -- "kill-switch-ack" | "next-day-reset" | "manual"
);
CREATE INDEX IF NOT EXISTS idx_risk_lockouts_account_since
    ON risk_lockouts (account_id, since DESC);

-- T02a: the kill switch never closes anything real (no close_all command
-- exists) — this is the only proof the trader actually saw and acted on the
-- "close your positions manually" banner.
CREATE TABLE IF NOT EXISTS kill_switch_acks (
    account_id      text NOT NULL,
    lockout_id      text NOT NULL REFERENCES risk_lockouts (lockout_id),
    acknowledged_at timestamptz NOT NULL,
    PRIMARY KEY (account_id, lockout_id)
);

-- T02b: one row per position actually closed (observer-detected from MT5
-- deal history). realized_pnl already sums every deal on the position — see
-- Mt5WireTranslator.ToTradeClosed / mt5_observer.py::sum_realized_pnl.
-- No day-anchor scope: unlike position_opens, the consecutive-loss streak
-- does not reset at midnight (T02-lockout.md), so this table is never
-- filtered by trading day, only ordered by closed_at.
CREATE TABLE IF NOT EXISTS closed_trades (
    account_id         text NOT NULL,
    broker_position_id text NOT NULL,
    symbol             text NOT NULL,
    side               text NOT NULL,
    volume             double precision NOT NULL,
    realized_pnl       double precision NOT NULL,
    -- T05: volume-weighted average across every exit deal — marks the exit
    -- fill on a rendered capture (mt5_observer.py::weighted_exit_price).
    exit_price         double precision NOT NULL,
    closed_at          timestamptz NOT NULL,
    PRIMARY KEY (account_id, broker_position_id)
);
CREATE INDEX IF NOT EXISTS idx_closed_trades_account_time
    ON closed_trades (account_id, closed_at DESC);

-- T05 — immutable capture facts, written once per (position, kind) at the
-- moment of the real event (journal.position.opened / journal.trade_closed),
-- never updated afterward. Deliberately NOT an image: the cockpit renders
-- the chart on demand from these frozen numbers using analyzeMarketContext
-- (TypeScript, the canonical analysis engine per ADR 0004) plus candles
-- queried within [window_start_utc, window_end_utc] — a boundary that is
-- stored and can never be widened, which is a stronger non-anticipation
-- guarantee than trusting a static image was rendered correctly once.
-- entry_price/stop_loss/take_profit are duplicated onto the 'exit' row (read
-- from the matching 'entry' row at write time) so a viewer needs only one
-- row per kind, never a join.
CREATE TABLE IF NOT EXISTS trade_captures (
    account_id          text NOT NULL,
    broker_position_id  text NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('entry', 'exit')),
    symbol              text NOT NULL,
    timeframe           text NOT NULL,
    window_start_utc    timestamptz NOT NULL,
    window_end_utc      timestamptz NOT NULL,
    entry_price         double precision NOT NULL,
    stop_loss           double precision NOT NULL,
    take_profit         double precision NOT NULL,
    -- Null on the 'entry' row (no exit yet); set on the 'exit' row.
    exit_price          double precision,
    captured_at         timestamptz NOT NULL,
    PRIMARY KEY (account_id, broker_position_id, kind)
);

-- T03: FRED release calendar cache. A reference-data cache, not a business
-- event — written directly by NewsCalendarRepository (NewsCalendarService),
-- outside the envelope/PersistenceWriter audit pipeline (that pipeline is
-- one-row-per-envelope; a refresh here replaces a whole release's future
-- rows at once — see NewsCalendarRepository.ReplaceUpcomingAsync). Must
-- survive a backend restart with no network: the news gate fails closed on
-- an empty/absent cache (context/product/tools/T03-gate-news.md).
CREATE TABLE IF NOT EXISTS news_releases (
    release_id    integer NOT NULL,
    label         text NOT NULL,
    scheduled_at  timestamptz NOT NULL,
    PRIMARY KEY (release_id, scheduled_at)
);
CREATE INDEX IF NOT EXISTS idx_news_releases_scheduled ON news_releases (scheduled_at);

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

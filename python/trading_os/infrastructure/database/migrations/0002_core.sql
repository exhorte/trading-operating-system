-- 0002 core — what the Python core adds to the baseline. Additive: nothing is dropped, nothing is overwritten.
--
-- * accounts and their versioned rules (the per-account successor of the firm-level `account_settings`)
-- * trade intents and risk decisions (Strategy → Intent → Risk → RiskDecision → Execution is now a persisted chain)
-- * execution commands with their full lifecycle. The previous table of the same name had another shape
--   (agent_id / risk_approval_id NOT NULL, no state): it is RENAMED `legacy_execution_commands`, its rows untouched.
-- * the event store (replaces `envelopes` as the audit trail), incidents, key/value system state.
--
-- Secrets: no table here has a column for a password, a token or a key. A test reads information_schema to keep it so.

CREATE TABLE IF NOT EXISTS accounts (
    account_id        text PRIMARY KEY,
    name              text NOT NULL,
    provider          text NOT NULL CHECK (provider IN ('EXNESS', 'FTMO')),
    platform          text NOT NULL DEFAULT 'MT5',
    account_type      text NOT NULL,
    login             bigint NOT NULL,
    server            text NOT NULL,
    currency          text NOT NULL,
    environment       text NOT NULL CHECK (environment IN ('DEMO', 'SIMULATED', 'LIVE')),
    terminal_path     text,
    symbol_suffix     text NOT NULL DEFAULT '',
    trading_enabled   boolean NOT NULL DEFAULT true,
    risk_profile      jsonb NOT NULL,
    trading_rules     jsonb NOT NULL,
    execution_profile jsonb NOT NULL,
    created_at        timestamptz NOT NULL,
    archived_at       timestamptz
);
-- A broker account (login on a server) is one account of ours — unless the previous one was archived.
CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_login_server ON accounts (login, server) WHERE archived_at IS NULL;

-- Append-only, like the ledger it replaces: a change is a new row; the only update is stamping cancelled_at on a
-- deferred change that has not governed a session yet (domain/accounts/rules_ledger.py).
CREATE TABLE IF NOT EXISTS account_rule_versions (
    version_id       text PRIMARY KEY,
    account_id       text NOT NULL REFERENCES accounts (account_id),
    rules            jsonb NOT NULL,
    requested_at     timestamptz NOT NULL,
    deferred         boolean NOT NULL,
    deferral_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    cancelled_at     timestamptz
);
CREATE INDEX IF NOT EXISTS idx_account_rule_versions_account_time
    ON account_rule_versions (account_id, requested_at DESC);

-- Small durable facts: the active account, the autonomy state and its lease, the news calendar's last sync …
CREATE TABLE IF NOT EXISTS system_state (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_intents (
    intent_id        text PRIMARY KEY,
    account_id       text NOT NULL,
    strategy_id      text NOT NULL,
    strategy_version text NOT NULL,
    symbol           text NOT NULL,
    side             text NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type       text NOT NULL,
    entry_price      double precision NOT NULL,
    stop_loss        double precision NOT NULL,
    take_profit      double precision NOT NULL,
    created_at       timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL,
    rationale        text NOT NULL DEFAULT '',
    details          jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_trade_intents_account_time ON trade_intents (account_id, created_at DESC);

-- Every review, approved or not: the trail explains each refusal. `decision` holds the full model (checks, gates,
-- sizing) the way the API shows it.
CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id     text PRIMARY KEY,
    intent_id       text,
    account_id      text NOT NULL,
    approved        boolean NOT NULL,
    approved_volume double precision,
    symbol          text,
    side            text,
    reasons         jsonb NOT NULL DEFAULT '[]'::jsonb,
    decision        jsonb NOT NULL,
    decided_at      timestamptz NOT NULL,
    expires_at      timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_account_time ON risk_decisions (account_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_intent ON risk_decisions (intent_id);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'execution_commands' AND column_name = 'risk_approval_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = current_schema() AND tablename = 'legacy_execution_commands'
    ) THEN
        ALTER TABLE execution_commands RENAME TO legacy_execution_commands;
        ALTER TABLE legacy_execution_commands
            RENAME CONSTRAINT execution_commands_pkey TO legacy_execution_commands_pkey;
    END IF;
END
$$;

-- ADR 0010 lifecycle. `command_id` is the idempotency key. The row is written in state PENDING *before* anything is
-- sent; every later change goes through the transition table and is mirrored in command_transitions.
CREATE TABLE IF NOT EXISTS execution_commands (
    command_id        text PRIMARY KEY,
    account_id        text NOT NULL,
    kind              text NOT NULL,
    symbol            text NOT NULL,
    side              text,
    state             text NOT NULL,
    route             text NOT NULL,
    mode              text NOT NULL,
    fingerprint       text NOT NULL,
    request           jsonb NOT NULL,
    risk_decision_id  text,
    strategy_id       text NOT NULL DEFAULT 'manual',
    created_at        timestamptz NOT NULL,
    expires_at        timestamptz NOT NULL,
    sent_at           timestamptz,
    acknowledged_at   timestamptz,
    completed_at      timestamptz,
    attempts          integer NOT NULL DEFAULT 0,
    detail            text NOT NULL DEFAULT '',
    reject_code       text,
    broker_order_id   text,
    broker_position_id text,
    filled_volume     double precision,
    average_price     double precision,
    broker_retcode    text,
    updated_at        timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_commands_account_time ON execution_commands (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_commands_open
    ON execution_commands (account_id, state)
    WHERE state IN ('PENDING', 'SENT', 'ACKNOWLEDGED', 'UNKNOWN', 'RECONCILING', 'EXECUTED');

CREATE TABLE IF NOT EXISTS command_transitions (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    command_id text NOT NULL REFERENCES execution_commands (command_id),
    from_state text,
    to_state   text NOT NULL,
    event      text NOT NULL,
    at         timestamptz NOT NULL,
    detail     text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_command_transitions_command ON command_transitions (command_id, id);

-- The audit trail. One row per event (id is unique: replaying a publish cannot duplicate it). High-rate telemetry
-- (ticks, heartbeats, snapshots) is broadcast to the cockpit but never lands here — see Event.persist.
CREATE TABLE IF NOT EXISTS events (
    event_id       text PRIMARY KEY,
    type           text NOT NULL,
    occurred_at    timestamptz NOT NULL,
    account_id     text,
    correlation_id text,
    payload        jsonb NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_account_time ON events (account_id, occurred_at DESC) WHERE account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id) WHERE correlation_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS incidents (
    incident_id text PRIMARY KEY,
    code        text NOT NULL,
    component   text NOT NULL,
    severity    text NOT NULL,
    detail      text NOT NULL,
    account_id  text,
    opened_at   timestamptz NOT NULL,
    resolved_at timestamptz,
    resolution  text
);
CREATE INDEX IF NOT EXISTS idx_incidents_open ON incidents (opened_at DESC) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents (opened_at DESC);

-- 0003 captures are data — the graphic capture was removed (ADR 0018); the numbers it recorded stay.
--
-- `trade_captures` keeps what a trade needs to be understood afterwards: the symbol, the entry price, the stop, the target and
-- the exit price, with the moment they were recorded. The three columns that only served to draw a chart —
-- `timeframe`, `window_start_utc`, `window_end_utc` (the frozen window of candles the cockpit used to render) — are no longer
-- written or read. Additive: this only makes them optional, so a row can be written without them; rows already there keep
-- their values untouched. Removing the columns for good is a decision about history, not about function, hence a manual
-- script (`python -m trading_os db manual drop_capture_window`), never part of the migrator.
--
-- Idempotent: dropping NOT NULL on a column that is already nullable is a no-op.

ALTER TABLE trade_captures ALTER COLUMN timeframe DROP NOT NULL;
ALTER TABLE trade_captures ALTER COLUMN window_start_utc DROP NOT NULL;
ALTER TABLE trade_captures ALTER COLUMN window_end_utc DROP NOT NULL;

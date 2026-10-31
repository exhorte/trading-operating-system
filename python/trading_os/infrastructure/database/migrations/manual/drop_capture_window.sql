-- MANUAL, DESTRUCTIVE — never run by the migrator. Run with:  python -m trading_os db manual drop_capture_window
--
-- Drops the three columns of `trade_captures` that only served to draw a chart (ADR 0018, the graphic capture was removed):
--   timeframe          the timeframe of the chart the cockpit rendered
--   window_start_utc   the start of the frozen window of candles it drew
--   window_end_utc     the end of that window
--
-- What stays — symbol, entry_price, stop_loss, take_profit, exit_price, captured_at — is the data of the trade, and nothing here
-- touches it. Nothing in the Python core reads or writes these columns (migration 0003 made them optional); dropping them is a
-- decision about history, not about function.
--
-- Before running it, if you want to keep the windows: pg_dump -t trade_captures

ALTER TABLE trade_captures DROP COLUMN IF EXISTS timeframe;
ALTER TABLE trade_captures DROP COLUMN IF EXISTS window_start_utc;
ALTER TABLE trade_captures DROP COLUMN IF EXISTS window_end_utc;

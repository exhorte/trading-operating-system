-- MANUAL, DESTRUCTIVE — never run by the migrator. Run with:  python -m trading_os db manual drop_legacy_tables
--
-- Drops what the Python core replaced and no longer reads:
--   envelopes                  the old JSONB audit trail (replaced by `events`)
--   legacy_execution_commands  the previous shape of execution_commands (renamed, not dropped, by 0002)
--   account_settings           the firm-level settings ledger (replaced by account_rule_versions)
--
-- Before running it: export what you want to keep (pg_dump -t envelopes -t legacy_execution_commands -t account_settings).
-- Nothing in the Python core reads these tables; dropping them is a decision about history, not about function.

DROP TABLE IF EXISTS envelopes;
DROP TABLE IF EXISTS legacy_execution_commands;
DROP TABLE IF EXISTS account_settings;

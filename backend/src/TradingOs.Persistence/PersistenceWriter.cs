using System.Reflection;
using System.Threading.Channels;
using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>Honest persistence status surfaced on /health.</summary>
public sealed class PersistenceStatus
{
    public bool DbUp { get; internal set; }

    public long Written { get; internal set; }

    public long Dropped { get; internal set; }

    public int Queued { get; internal set; }

    /// <summary>Last persistence error message (diagnostics), null when healthy.</summary>
    public string? LastError { get; internal set; }
}

/// <summary>
/// Asynchronous, never-blocking persistence: envelopes are enqueued on a
/// bounded channel and drained by a background loop. The realtime path is
/// NEVER coupled to the database — when the DB is down or the channel is
/// full, events are dropped with a counter and the flow continues.
/// </summary>
public sealed class PersistenceWriter
{
    private const int Capacity = 10_000;
    private const int RetryDelayMs = 5_000;

    private readonly Channel<PersistedEvent> _channel = Channel.CreateBounded<PersistedEvent>(
        new BoundedChannelOptions(Capacity)
        {
            FullMode = BoundedChannelFullMode.DropWrite,
        });

    private readonly string _connectionString;

    public PersistenceStatus Status { get; } = new();

    public PersistenceWriter(string connectionString)
    {
        _connectionString = connectionString;
    }

    /// <summary>Fire-and-forget enqueue; returns immediately, never throws.</summary>
    public void Enqueue(PersistedEvent evt)
    {
        if (!_channel.Writer.TryWrite(evt))
        {
            Status.Dropped += 1;
        }
        Status.Queued = _channel.Reader.Count;
    }

    /// <summary>Apply schema.sql (idempotent), retrying until the DB is reachable.</summary>
    public async Task EnsureSchemaAsync(CancellationToken ct)
    {
        var schema = ReadEmbeddedSchema();
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await using var conn = new NpgsqlConnection(_connectionString);
                await conn.OpenAsync(ct);
                await conn.ExecuteAsync(schema);
                Status.DbUp = true;
                Status.LastError = null;
                return;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                Status.DbUp = false;
                Status.LastError = $"schema: {ex.Message}";
                await Task.Delay(RetryDelayMs, ct);
            }
        }
    }

    /// <summary>Drain loop: typed insert (when mapped) + audit insert, per event.</summary>
    public async Task RunAsync(CancellationToken ct)
    {
        await EnsureSchemaAsync(ct);

        await foreach (var evt in _channel.Reader.ReadAllAsync(ct))
        {
            Status.Queued = _channel.Reader.Count;
            try
            {
                await using var conn = new NpgsqlConnection(_connectionString);
                await conn.OpenAsync(ct);
                await WriteAsync(conn, evt);
                Status.DbUp = true;
                Status.Written += 1;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                // DB unavailable/mid-restart: drop this event (audited by the
                // counter), pause briefly, keep the realtime path unharmed.
                Status.DbUp = false;
                Status.LastError = $"write({evt.Type}): {ex.Message}";
                Status.Dropped += 1;
                try
                {
                    await Task.Delay(RetryDelayMs, ct);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
            }
        }
    }

    private static async Task WriteAsync(NpgsqlConnection conn, PersistedEvent evt)
    {
        // Complete audit trail first — every envelope lands here.
        await conn.ExecuteAsync(
            """
            INSERT INTO envelopes (message_id, correlation_id, type, source, sent_at, payload)
            VALUES (@MessageId, @CorrelationId, @Type, @Source, @SentAt::timestamptz, @PayloadJson::jsonb)
            ON CONFLICT (message_id) DO NOTHING
            """,
            evt);

        var row = PersistenceMapper.ToTypedRow(evt.Type, evt.PayloadJson);
        var sql = row switch
        {
            CandleRow => """
                INSERT INTO candles (symbol, timeframe, open_time, open, high, low, close, volume, closed)
                VALUES (@Symbol, @Timeframe, @OpenTime, @Open, @High, @Low, @Close, @Volume, @Closed)
                ON CONFLICT (symbol, timeframe, open_time) DO UPDATE
                  SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                      close = EXCLUDED.close, volume = EXCLUDED.volume, closed = EXCLUDED.closed
                """,
            TickRow => "INSERT INTO ticks (symbol, ts, bid, ask) VALUES (@Symbol, @Ts, @Bid, @Ask)",
            SignalRow => """
                INSERT INTO strategy_signals (signal_id, strategy_id, symbol, side, entry_price, stop_loss,
                  take_profit, score, max_score, context, created_at, expires_at)
                VALUES (@SignalId, @StrategyId, @Symbol, @Side, @EntryPrice, @StopLoss,
                  @TakeProfit, @Score, @MaxScore, @Context, @CreatedAt, @ExpiresAt)
                ON CONFLICT (signal_id) DO NOTHING
                """,
            DecisionRow => """
                INSERT INTO risk_decisions (approval_id, signal_id, account_id, approved, approved_volume,
                  reason, gates, decided_at)
                VALUES (@ApprovalId, @SignalId, @AccountId, @Approved, @ApprovedVolume,
                  @Reason, @GatesJson::jsonb, @DecidedAt)
                ON CONFLICT (approval_id) DO NOTHING
                """,
            CommandRow => """
                INSERT INTO execution_commands (command_id, signal_id, account_id, agent_id, risk_approval_id,
                  symbol, side, order_type, volume, stop_loss, take_profit, issued_at, expires_at)
                VALUES (@CommandId, @SignalId, @AccountId, @AgentId, @RiskApprovalId,
                  @Symbol, @Side, @OrderType, @Volume, @StopLoss, @TakeProfit, @IssuedAt, @ExpiresAt)
                ON CONFLICT (command_id) DO NOTHING
                """,
            AckRow => """
                INSERT INTO command_acks (command_id, agent_id, status, reason, received_at)
                VALUES (@CommandId, @AgentId, @Status, @Reason, @ReceivedAt)
                """,
            ReportRow => """
                INSERT INTO execution_reports (report_id, command_id, account_id, agent_id, symbol, side,
                  status, detail, reported_at)
                VALUES (@ReportId, @CommandId, @AccountId, @AgentId, @Symbol, @Side,
                  @Status, @Detail, @ReportedAt)
                ON CONFLICT (report_id) DO NOTHING
                """,
            TicketRow => """
                INSERT INTO pretrade_tickets (ticket_id, account_id, symbol, setup, bias, entry_price,
                  stop_loss, invalidation, confidence, take_profit, target_volume, target_risk_usd, created_at)
                VALUES (@TicketId, @AccountId, @Symbol, @Setup, @Bias, @EntryPrice,
                  @StopLoss, @Invalidation, @Confidence, @TakeProfit, @TargetVolume, @TargetRiskUsd, @CreatedAt)
                ON CONFLICT (ticket_id) DO NOTHING
                """,
            DayAnchorRow => """
                INSERT INTO trading_day_anchors (account_id, starts_at_utc)
                VALUES (@AccountId, @StartsAtUtc)
                ON CONFLICT (account_id, starts_at_utc) DO NOTHING
                """,
            // Only ever fills a still-unknown equity for the latest anchor —
            // never overwrites one already captured, never guesses at a stale one.
            DayAnchorEquityRow => """
                UPDATE trading_day_anchors
                SET day_start_equity = @Equity
                WHERE account_id = @AccountId
                  AND starts_at_utc = @StartsAtUtc
                  AND day_start_equity IS NULL
                """,
            PositionOpenRow => """
                INSERT INTO position_opens (account_id, broker_position_id, opened_at)
                VALUES (@AccountId, @BrokerPositionId, @OpenedAt)
                ON CONFLICT (account_id, broker_position_id) DO NOTHING
                """,
            ClosedTradeRow => """
                INSERT INTO closed_trades (account_id, broker_position_id, symbol, side, volume, realized_pnl, exit_price, closed_at)
                VALUES (@AccountId, @BrokerPositionId, @Symbol, @Side, @Volume, @RealizedPnl, @ExitPrice, @ClosedAt)
                ON CONFLICT (account_id, broker_position_id) DO NOTHING
                """,
            LockoutEnabledRow => """
                INSERT INTO risk_lockouts (lockout_id, account_id, reason, since, until)
                VALUES (@LockoutId, @AccountId, @Reason, @Since, @Until)
                ON CONFLICT (lockout_id) DO NOTHING
                """,
            // Clears the single currently-active lockout for this account —
            // there is never more than one at a time (edge-triggered writes).
            LockoutClearedRow => """
                UPDATE risk_lockouts
                SET cleared_at = now(), cleared_by = @ClearedBy
                WHERE account_id = @AccountId AND cleared_at IS NULL
                """,
            KillSwitchAckRow => """
                INSERT INTO kill_switch_acks (account_id, lockout_id, acknowledged_at)
                VALUES (@AccountId, @LockoutId, @AcknowledgedAt)
                ON CONFLICT (account_id, lockout_id) DO NOTHING
                """,
            _ => null,
        };
        if (sql is not null)
        {
            await conn.ExecuteAsync(sql, row);
        }
    }

    private static string ReadEmbeddedSchema()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var name = assembly.GetManifestResourceNames().Single(n => n.EndsWith("schema.sql"));
        using var stream = assembly.GetManifestResourceStream(name)!;
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
}

using TradingOs.Contracts;

namespace TradingOs.Gateway;

/// <summary>
/// Pure translation lean MT5 wire → read models. C# port of
/// lib/realtime/mt5-translate.ts — keep both in sync (ADR 0004/0009); the
/// TS unit tests are the reference cases mirrored in Mt5WireTranslatorTests.
/// </summary>
public static class Mt5WireTranslator
{
    private static string Iso(long epochMs) =>
        DateTimeOffset.FromUnixTimeMilliseconds(epochMs).UtcDateTime.ToString("o");

    public static string LowercaseSide(string side) => side == "BUY" ? "buy" : "sell";

    /// <summary>
    /// Real fields come straight from MT5; dailyPnl is floating equity−balance
    /// (honest intraday approximation). Drawdown/open-risk stay 0 here — the
    /// dashboard risk engine computes them; never presented as validated risk.
    /// </summary>
    public static AccountSummary ToAccountSummary(Mt5AccountSnapshotMessage account, Mt5HelloMessage? hello)
    {
        return new AccountSummary(
            AccountId: account.AccountId,
            Label: hello is null ? account.AccountId : $"{hello.Broker} • {account.AccountId}",
            Broker: hello?.Broker ?? "MT5",
            Currency: account.Currency,
            Balance: account.Balance,
            Equity: account.Equity,
            DailyPnl: Math.Round(account.Equity - account.Balance, 2),
            DailyDrawdownPercent: 0,
            TotalDrawdownPercent: 0,
            OpenRiskPercent: 0);
    }

    public static Position[] ToPositions(Mt5PositionsSnapshotMessage msg, double? lastPrice)
    {
        var openedAt = Iso(msg.Time);
        return msg.Positions.Select(p => ToPosition(p, msg.AccountId, openedAt, lastPrice)).ToArray();
    }

    private static Position ToPosition(Mt5PositionSnapshot p, string accountId, string openedAtIso, double? lastPrice)
    {
        var side = LowercaseSide(p.Side);
        var currentPrice = lastPrice ?? p.EntryPrice;
        var direction = side == "buy" ? 1 : -1;
        var move = (currentPrice - p.EntryPrice) * direction;
        var risk = Math.Abs(p.EntryPrice - p.StopLoss);
        return new Position(
            PositionId: p.BrokerPositionId,
            AccountId: accountId,
            Symbol: p.Symbol,
            Side: side,
            Volume: p.Volume,
            EntryPrice: p.EntryPrice,
            CurrentPrice: currentPrice,
            StopLoss: p.StopLoss,
            TakeProfit: p.TakeProfit,
            UnrealizedPnl: p.FloatingPnl,
            RMultiple: risk > 0 ? Math.Round(move / risk, 2) : 0,
            StrategyId: "live-observed",
            OpenedAt: openedAtIso);
    }

    /// <summary>T05: lean position.opened → dashboard/persistence payload
    /// (server-side diff, replaces the old client-detected T02a event).</summary>
    public static PositionOpenedPayload ToPositionOpened(Mt5PositionOpenedMessage msg)
    {
        return new PositionOpenedPayload(
            AccountId: msg.AccountId,
            BrokerPositionId: msg.BrokerPositionId,
            Symbol: msg.Symbol,
            Side: LowercaseSide(msg.Side),
            Volume: msg.Volume,
            EntryPrice: msg.EntryPrice,
            StopLoss: msg.StopLoss,
            TakeProfit: msg.TakeProfit,
            OpenedAt: Iso(msg.OpenedAt));
    }

    /// <summary>T02b: lean position.closed → dashboard/persistence payload.
    /// ClosedAt converts the observer's epoch-ms to ISO, like every other
    /// wire timestamp (Iso helper). ExitPrice (T05) passes through as-is.</summary>
    public static JournalTradeClosedPayload ToTradeClosed(Mt5PositionClosedMessage msg)
    {
        return new JournalTradeClosedPayload(
            AccountId: msg.AccountId,
            BrokerPositionId: msg.BrokerPositionId,
            Symbol: msg.Symbol,
            Side: LowercaseSide(msg.Side),
            Volume: msg.Volume,
            RealizedPnl: msg.RealizedPnl,
            ExitPrice: msg.ExitPrice,
            ClosedAt: Iso(msg.ClosedAt));
    }

    public static Candle ToCandle(Mt5CandleMessage msg)
    {
        return new Candle(
            Symbol: msg.Symbol,
            Timeframe: msg.Timeframe,
            OpenTime: Iso(msg.OpenTime),
            Open: msg.Open,
            High: msg.High,
            Low: msg.Low,
            Close: msg.Close,
            Volume: msg.Volume,
            Closed: msg.Closed);
    }

    public static AgentStatus ToAgentStatus(Mt5HelloMessage hello)
    {
        return new AgentStatus(
            AgentId: hello.AgentId,
            AccountId: hello.AccountId,
            Platform: "MT5",
            State: "connected",
            LatencyMs: 0,
            LastHeartbeatAt: Iso(hello.Time),
            Version: hello.AgentVersion);
    }

    // --- Phase 09: command loop (ADR 0005 flatten/enrich tables) ---

    /// <summary>Flatten a dashboard PlaceOrderCommand to the lean edge command:
    /// id=commandId, ISO→epoch-ms expiry, uppercase side/orderType.</summary>
    public static Mt5OrderCommand FlattenPlaceOrder(PlaceOrderCommand command)
    {
        return new Mt5OrderCommand(
            Version: 1,
            Type: "execution.order",
            AccountId: command.AccountId,
            Time: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            Id: command.CommandId,
            ExpiresAt: DateTimeOffset.Parse(command.ExpiresAt).ToUnixTimeMilliseconds(),
            Symbol: command.Symbol,
            Side: command.Side.ToUpperInvariant(),
            OrderType: command.OrderType.ToUpperInvariant(),
            Volume: command.Volume,
            LimitPrice: command.LimitPrice,
            Sl: command.StopLoss,
            Tp: command.TakeProfit);
    }

    /// <summary>Lean execution.ack → dashboard CommandAck (statuses lowercased).</summary>
    public static CommandAck ToCommandAck(Mt5AckMessage ack, string agentId)
    {
        return new CommandAck(
            CommandId: ack.CommandId,
            AgentId: agentId,
            Status: ack.Status.ToLowerInvariant(), // ACCEPTED→accepted, DUPLICATE→duplicate, …
            Reason: ack.Reason,
            ReceivedAt: Iso(ack.Time));
    }

    /// <summary>Lean execution.report → dashboard report view. SIMULATED maps to
    /// the dedicated "simulated" status — never to a fill.</summary>
    public static ExecutionReportView ToExecutionReport(Mt5ReportMessage report, string agentId)
    {
        return new ExecutionReportView(
            ReportId: Guid.NewGuid().ToString(),
            CommandId: report.CommandId,
            CorrelationId: report.CommandId,
            AccountId: report.AccountId,
            AgentId: agentId,
            Symbol: report.Symbol,
            Side: LowercaseSide(report.Side),
            Status: report.Status.ToLowerInvariant(),
            Detail: report.Detail,
            ReportedAt: Iso(report.Time));
    }
}

using TradingOs.Persistence;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// Pure mapping tests: camelCase payload JSON (lib/contracts shapes) → typed
/// rows mirroring schema.sql. No database needed.
/// </summary>
public class PersistenceMapperTests
{
    [Fact]
    public void Maps_closed_candle_to_candle_row()
    {
        var row = PersistenceMapper.ToTypedRow("market.candle.closed",
            """{"candle":{"symbol":"XAUUSDm","timeframe":"M15","openTime":"2026-07-11T13:00:00.000Z","open":4050,"high":4055,"low":4049,"close":4053,"volume":120,"closed":true}}""");
        var candle = Assert.IsType<CandleRow>(row);
        Assert.Equal("XAUUSDm", candle.Symbol);
        Assert.Equal(4053, candle.Close);
        Assert.True(candle.Closed);
    }

    [Fact]
    public void Maps_signal_and_decision_rows()
    {
        var signal = Assert.IsType<SignalRow>(PersistenceMapper.ToTypedRow("strategy.signal.created",
            """{"signal":{"signalId":"sig-a1b2-101","symbol":"XAUUSDm","strategyId":"ict-silver-bullet-v1","side":"buy","status":"risk_review","entryPrice":4053,"stopLoss":4048,"takeProfit":4063,"score":7,"maxScore":10,"contextSummary":"bullish bias · BOS · london","riskDecision":null,"expiresAt":"2026-07-11T13:05:00.000Z","createdAt":"2026-07-11T13:00:00.000Z"}}"""));
        Assert.Equal("sig-a1b2-101", signal.SignalId);
        Assert.Equal(4048, signal.StopLoss);

        var decision = Assert.IsType<DecisionRow>(PersistenceMapper.ToTypedRow("risk.decision.made",
            """{"decision":{"approvalId":"risk-sig-a1b2-101","signalId":"sig-a1b2-101","accountId":"436634705","approved":true,"approvedVolume":0.19,"reason":"Approved: 0.19 lot at 1% risk","gates":[{"gateId":"g","label":"Daily loss guard","state":"open","detail":"0% used"}],"decidedAt":"2026-07-11T13:00:01.000Z"}}"""));
        Assert.True(decision.Approved);
        Assert.Equal(0.19, decision.ApprovedVolume);
        Assert.Contains("Daily loss guard", decision.GatesJson);
    }

    [Fact]
    public void Maps_rejected_decision_with_null_volume()
    {
        var decision = Assert.IsType<DecisionRow>(PersistenceMapper.ToTypedRow("risk.decision.made",
            """{"decision":{"approvalId":"risk-x","signalId":"sig-x","accountId":"a","approved":false,"approvedVolume":null,"reason":"Rejected: Spread gate","gates":[],"decidedAt":"2026-07-11T13:00:01.000Z"}}"""));
        Assert.False(decision.Approved);
        Assert.Null(decision.ApprovedVolume);
    }

    [Fact]
    public void Maps_command_ack_and_simulated_report_rows()
    {
        var command = Assert.IsType<CommandRow>(PersistenceMapper.ToTypedRow("execution.command.place_order",
            """{"command":{"kind":"place_order","commandId":"cmd-sig-a1b2-101","accountId":"436634705","agentId":"mt5-observer-1","riskApprovalId":"risk-sig-a1b2-101","expiresAt":"2026-07-11T13:01:00.000Z","issuedAt":"2026-07-11T13:00:00.000Z","symbol":"XAUUSDm","side":"buy","orderType":"market","volume":0.19,"limitPrice":null,"stopLoss":4048,"takeProfit":4063,"signalId":"sig-a1b2-101","strategyId":"ict-silver-bullet-v1"}}"""));
        Assert.Equal("risk-sig-a1b2-101", command.RiskApprovalId);
        Assert.Equal(0.19, command.Volume);

        var ack = Assert.IsType<AckRow>(PersistenceMapper.ToTypedRow("execution.command.acknowledged",
            """{"ack":{"commandId":"cmd-sig-a1b2-101","agentId":"mt5-observer-1","status":"accepted","reason":null,"receivedAt":"2026-07-11T13:00:02.000Z"}}"""));
        Assert.Equal("accepted", ack.Status);
        Assert.Null(ack.Reason);

        var report = Assert.IsType<ReportRow>(PersistenceMapper.ToTypedRow("execution.order.simulated",
            """{"report":{"reportId":"r1","commandId":"cmd-sig-a1b2-101","correlationId":"cmd-sig-a1b2-101","accountId":"436634705","agentId":"mt5-observer-1","symbol":"XAUUSDm","side":"buy","status":"simulated","detail":"SIMULATED 0.19 lot","reportedAt":"2026-07-11T13:00:03.000Z"}}"""));
        Assert.Equal("simulated", report.Status);
    }

    [Fact]
    public void Unmapped_types_return_null_but_still_audit()
    {
        Assert.Null(PersistenceMapper.ToTypedRow("agent.heartbeat", """{"agentId":"a","latencyMs":10}"""));
    }

    [Fact]
    public void Maps_ticket_row_with_optional_fields_present()
    {
        var ticket = Assert.IsType<TicketRow>(PersistenceMapper.ToTypedRow("journal.ticket.created",
            """{"ticket":{"ticketId":"ticket-1","accountId":"acc-1","symbol":"XAUUSD","setup":"fvg","bias":"long","entryPrice":3300,"stopLoss":3290,"invalidation":3290,"confidence":4,"takeProfit":3320,"targetVolume":0.02,"targetRiskUsd":20,"createdAt":"2026-09-05T10:00:00.000Z"}}"""));
        Assert.Equal("ticket-1", ticket.TicketId);
        Assert.Equal("fvg", ticket.Setup);
        Assert.Equal(3320, ticket.TakeProfit);
        Assert.Equal(0.02, ticket.TargetVolume);
        Assert.Equal(4, ticket.Confidence);
    }

    [Fact]
    public void Maps_ticket_row_with_optional_fields_absent_as_null_not_zero()
    {
        var ticket = Assert.IsType<TicketRow>(PersistenceMapper.ToTypedRow("journal.ticket.created",
            """{"ticket":{"ticketId":"ticket-2","accountId":"acc-1","symbol":"XAUUSD","setup":"retest","bias":"short","entryPrice":3300,"stopLoss":3310,"invalidation":3310,"confidence":2,"takeProfit":null,"targetVolume":null,"targetRiskUsd":null,"createdAt":"2026-09-05T10:00:00.000Z"}}"""));
        Assert.Null(ticket.TakeProfit);
        Assert.Null(ticket.TargetVolume);
        Assert.Null(ticket.TargetRiskUsd);
    }

    [Fact]
    public void Maps_day_anchor_resolved_and_equity_observed_rows()
    {
        var anchor = Assert.IsType<DayAnchorRow>(PersistenceMapper.ToTypedRow("risk.day_anchor.resolved",
            """{"accountId":"acc-1","startsAtUtc":"2026-09-04T21:00:00.000Z"}"""));
        Assert.Equal("acc-1", anchor.AccountId);

        var equity = Assert.IsType<DayAnchorEquityRow>(PersistenceMapper.ToTypedRow("risk.day_anchor.equity_observed",
            """{"accountId":"acc-1","startsAtUtc":"2026-09-04T21:00:00.000Z","equity":101512.3}"""));
        Assert.Equal(101512.3, equity.Equity);
    }

    [Fact]
    public void Maps_position_opened_row()
    {
        var open = Assert.IsType<PositionOpenRow>(PersistenceMapper.ToTypedRow("journal.position.opened",
            """{"accountId":"acc-1","brokerPositionId":"pos-9","openedAt":"2026-09-05T10:00:00.000Z"}"""));
        Assert.Equal("pos-9", open.BrokerPositionId);
    }

    [Fact]
    public void Maps_closed_trade_row()
    {
        var closed = Assert.IsType<ClosedTradeRow>(PersistenceMapper.ToTypedRow("journal.trade_closed",
            """{"accountId":"acc-1","brokerPositionId":"pos-9","symbol":"XAUUSDm","side":"buy","volume":0.02,"realizedPnl":4.45,"exitPrice":4054.0,"closedAt":"2026-09-05T10:00:20.000Z"}"""));
        Assert.Equal("pos-9", closed.BrokerPositionId);
        Assert.Equal(4.45, closed.RealizedPnl);
        Assert.Equal(4054.0, closed.ExitPrice);
    }

    [Fact]
    public void Maps_lockout_enabled_with_and_without_an_expiry()
    {
        var hard = Assert.IsType<LockoutEnabledRow>(PersistenceMapper.ToTypedRow("risk.lockout.enabled",
            """{"lockoutId":"lock-1","accountId":"acc-1","reason":"Daily loss guard","since":"2026-09-05T10:00:00.000Z","until":null}"""));
        Assert.Null(hard.Until);

        var paused = Assert.IsType<LockoutEnabledRow>(PersistenceMapper.ToTypedRow("risk.lockout.enabled",
            """{"lockoutId":"lock-2","accountId":"acc-1","reason":"Consecutive losses","since":"2026-09-05T10:00:00.000Z","until":"2026-09-05T10:30:00.000Z"}"""));
        Assert.Equal(DateTimeOffset.Parse("2026-09-05T10:30:00.000Z"), paused.Until);
    }

    [Fact]
    public void Maps_lockout_cleared_and_kill_switch_ack_rows()
    {
        var cleared = Assert.IsType<LockoutClearedRow>(PersistenceMapper.ToTypedRow("risk.lockout.cleared",
            """{"accountId":"acc-1","clearedBy":"next-day-reset"}"""));
        Assert.Equal("next-day-reset", cleared.ClearedBy);

        var ack = Assert.IsType<KillSwitchAckRow>(PersistenceMapper.ToTypedRow("risk.lockout.acknowledged",
            """{"accountId":"acc-1","lockoutId":"lock-3","acknowledgedAt":"2026-09-05T10:05:00.000Z"}"""));
        Assert.Equal("lock-3", ack.LockoutId);
    }
}

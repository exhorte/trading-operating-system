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
    public void A_rejection_maps_whether_it_carries_an_ack_or_a_report()
    {
        // The Gateway and the agent's ack REJECTED carry an ack; the agent's
        // report REJECTED travels under the same type with a report. Reading
        // only "ack" threw on the second shape, and the writer took that for a
        // database outage.
        var ack = Assert.IsType<AckRow>(PersistenceMapper.ToTypedRow("execution.command.rejected",
            """{"ack":{"commandId":"cmd-1","agentId":"gateway","status":"rejected","reason":"agent unreachable","receivedAt":"2026-09-25T10:00:00.000Z"}}"""));
        Assert.Equal("rejected", ack.Status);

        var report = Assert.IsType<ReportRow>(PersistenceMapper.ToTypedRow("execution.command.rejected",
            """{"report":{"reportId":"r2","commandId":"cmd-2","correlationId":"cmd-2","accountId":"acc-1","agentId":"mt5-execution-agent-1001","symbol":"EURUSDm","side":"buy","status":"rejected","detail":"SYMBOL_NOT_ALLOWED","reportedAt":"2026-09-25T10:00:01.000Z"}}"""));
        Assert.Equal("cmd-2", report.CommandId);
        Assert.Equal("SYMBOL_NOT_ALLOWED", report.Detail);
    }

    [Theory]
    [InlineData("execution.order.submitted")]
    [InlineData("execution.order.filled")]
    [InlineData("execution.order.partially_filled")]
    [InlineData("execution.order.failed")]
    public void Real_execution_outcomes_map_to_report_rows(string type)
    {
        var report = Assert.IsType<ReportRow>(PersistenceMapper.ToTypedRow(type,
            """{"report":{"reportId":"r3","commandId":"cmd-3","correlationId":"cmd-3","accountId":"acc-1","agentId":"mt5-execution-agent-1001","symbol":"EURUSDm","side":"sell","status":"filled","detail":"FILLED 0.01","reportedAt":"2026-09-25T10:00:02.000Z"}}"""));
        Assert.Equal("cmd-3", report.CommandId);
    }

    [Fact]
    public void Unmapped_types_return_null_but_still_audit()
    {
        Assert.Null(PersistenceMapper.ToTypedRow("agent.heartbeat", """{"agentId":"a","latencyMs":10}"""));
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

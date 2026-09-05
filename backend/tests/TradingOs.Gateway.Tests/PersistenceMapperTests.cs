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
}

using TradingOs.Contracts;
using TradingOs.Gateway;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// Phase 09 command-loop translations (ADR 0005 flatten/enrich). The TS side
/// (command-builder + store lifecycle tests) mirrors the same semantics.
/// </summary>
public class ExecutionTranslationTests
{
    private static readonly PlaceOrderCommand Command = new(
        Kind: "place_order",
        CommandId: "cmd-sig-301",
        AccountId: "436634705",
        AgentId: "mt5-observer-1",
        RiskApprovalId: "risk-sig-301",
        ExpiresAt: "2026-07-11T10:01:00.000Z",
        IssuedAt: "2026-07-11T10:00:00.000Z",
        Symbol: "XAUUSDm",
        Side: "buy",
        OrderType: "market",
        Volume: 0.02,
        LimitPrice: null,
        StopLoss: 4048,
        TakeProfit: 4063,
        SignalId: "sig-301",
        StrategyId: "ict-silver-bullet-v1");

    [Fact]
    public void FlattenPlaceOrder_maps_to_lean_wire()
    {
        var lean = Mt5WireTranslator.FlattenPlaceOrder(Command);

        Assert.Equal("execution.order", lean.Type);
        Assert.Equal("cmd-sig-301", lean.Id);           // id = commandId (dedup key)
        Assert.Equal("BUY", lean.Side);                  // uppercase at the edge
        Assert.Equal("MARKET", lean.OrderType);
        Assert.Equal(0.02, lean.Volume);
        Assert.Equal(4048, lean.Sl);
        // ISO expiry becomes epoch milliseconds.
        Assert.Equal(DateTimeOffset.Parse("2026-07-11T10:01:00.000Z").ToUnixTimeMilliseconds(), lean.ExpiresAt);
        Assert.Contains("\"type\":\"execution.order\"", lean.ToJson());
    }

    [Theory]
    [InlineData("ACCEPTED", "accepted")]
    [InlineData("REJECTED", "rejected")]
    [InlineData("DUPLICATE", "duplicate")]
    [InlineData("EXPIRED", "expired")]
    public void ToCommandAck_lowercases_status(string wire, string expected)
    {
        var ack = new Mt5AckMessage(1, "execution.ack", "436634705", 1767618000000, "cmd-sig-301", wire, null);
        var mapped = Mt5WireTranslator.ToCommandAck(ack, "mt5-observer-1");
        Assert.Equal(expected, mapped.Status);
        Assert.Equal("cmd-sig-301", mapped.CommandId);
    }

    [Fact]
    public void ToExecutionReport_maps_SIMULATED_to_simulated_never_filled()
    {
        var report = new Mt5ReportMessage(1, "execution.report", "436634705", 1767618000000,
            "cmd-sig-301", "SIMULATED", "XAUUSDm", "BUY",
            BrokerOrderId: null, BrokerPositionId: null,
            FilledVolume: 0.02, AveragePrice: 4053.2, BrokerRetcode: null,
            Detail: "SIMULATED 0.02 lot BUY XAUUSDm (observe mode, no broker order)");

        var mapped = Mt5WireTranslator.ToExecutionReport(report, "mt5-observer-1");

        Assert.Equal("simulated", mapped.Status);
        Assert.NotEqual("filled", mapped.Status);
        Assert.Equal("buy", mapped.Side);
        Assert.Equal("cmd-sig-301", mapped.CommandId);
    }

    [Fact]
    public void Parser_dispatches_ack_and_report()
    {
        var ack = Mt5WireParser.Parse(
            """{"version":1,"type":"execution.ack","accountId":"a","time":1,"commandId":"c1","status":"ACCEPTED","reason":null}""");
        Assert.IsType<Mt5AckMessage>(ack);

        var report = Mt5WireParser.Parse(
            """{"version":1,"type":"execution.report","accountId":"a","time":1,"commandId":"c1","status":"SIMULATED","symbol":"XAUUSDm","side":"BUY","brokerOrderId":null,"brokerPositionId":null,"filledVolume":0.02,"averagePrice":4053.2,"brokerRetcode":null,"detail":"d"}""");
        Assert.IsType<Mt5ReportMessage>(report);
    }
}

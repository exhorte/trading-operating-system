using TradingOs.Contracts;
using TradingOs.Gateway;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// Mirrors lib/realtime/mt5-translate.test.ts — the TS and C# translators must
/// agree on these cases (ADR 0009). If one side changes, change both.
/// </summary>
public class Mt5WireTranslatorTests
{
    private static readonly Mt5HelloMessage Hello = new(
        Version: 1,
        Type: "agent.hello",
        AccountId: "5099xxxx",
        Time: 1767618000000, // 2026-01-05T13:00:00Z
        AgentId: "mt5-observer-1",
        Symbol: "XAUUSDm",
        Broker: "Exness Technologies Ltd",
        Server: "Exness-MT5Trial8",
        OrderTypes: ["market"],
        MinVolume: 0.01,
        MaxVolume: 200,
        VolumeStep: 0.01,
        FillingMode: "IOC",
        StopsLevelPoints: 0,
        Mode: "observe",
        AgentVersion: "0.1.0-observer");

    [Fact]
    public void ToAccountSummary_maps_real_fields_and_floating_daily_pnl()
    {
        var msg = new Mt5AccountSnapshotMessage(1, "account.snapshot", "5099xxxx",
            Time: 0, Balance: 1000, Equity: 1012.5, Margin: 50, FreeMargin: 962.5, Currency: "USD");

        var acc = Mt5WireTranslator.ToAccountSummary(msg, Hello);

        Assert.Equal(1000, acc.Balance);
        Assert.Equal(1012.5, acc.Equity);
        Assert.Equal(12.5, acc.DailyPnl);
        Assert.Equal("USD", acc.Currency);
        Assert.Equal("Exness Technologies Ltd", acc.Broker);
        // Honest zeros until the risk engine computes them.
        Assert.Equal(0, acc.DailyDrawdownPercent);
        Assert.Equal(0, acc.OpenRiskPercent);
    }

    private static readonly Mt5PositionsSnapshotMessage PositionsMsg = new(
        1, "positions.snapshot", "5099xxxx", Time: 1767619800000,
        Positions:
        [
            new Mt5PositionSnapshot("pos-42", "XAUUSDm", "BUY", 0.1,
                EntryPrice: 3300, StopLoss: 3290, TakeProfit: 3320, FloatingPnl: 7.5),
        ]);

    [Fact]
    public void ToPositions_lowercases_side_keeps_pnl_computes_r()
    {
        var positions = Mt5WireTranslator.ToPositions(PositionsMsg, lastPrice: 3305);
        var pos = Assert.Single(positions);

        Assert.Equal("buy", pos.Side);
        Assert.Equal(7.5, pos.UnrealizedPnl);
        Assert.Equal(3305, pos.CurrentPrice);
        Assert.Equal(0.5, pos.RMultiple); // move +5 on risk 10
        Assert.Equal("live-observed", pos.StrategyId);
    }

    [Fact]
    public void ToPositions_falls_back_to_entry_price_without_tick()
    {
        var pos = Assert.Single(Mt5WireTranslator.ToPositions(PositionsMsg, lastPrice: null));
        Assert.Equal(3300, pos.CurrentPrice);
        Assert.Equal(0, pos.RMultiple);
    }

    [Fact]
    public void ToCandle_maps_iso_open_time()
    {
        var msg = new Mt5CandleMessage(1, "market.candle", "5099xxxx", Time: 0,
            Symbol: "XAUUSDm", Timeframe: "M15", OpenTime: 1767618000000,
            Open: 3300, High: 3305, Low: 3299, Close: 3304, Volume: 120, Closed: true);

        var candle = Mt5WireTranslator.ToCandle(msg);

        Assert.StartsWith("2026-01-05T13:00:00", candle.OpenTime);
        Assert.Equal("M15", candle.Timeframe);
        Assert.Equal(3304, candle.Close);
    }

    [Fact]
    public void ToAgentStatus_maps_hello_to_connected_agent()
    {
        var agent = Mt5WireTranslator.ToAgentStatus(Hello);
        Assert.Equal("MT5", agent.Platform);
        Assert.Equal("connected", agent.State);
        Assert.Equal("0.1.0-observer", agent.Version);
    }

    [Fact]
    public void LowercaseSide_maps_both_sides()
    {
        Assert.Equal("buy", Mt5WireTranslator.LowercaseSide("BUY"));
        Assert.Equal("sell", Mt5WireTranslator.LowercaseSide("SELL"));
    }

    [Fact]
    public void Parser_dispatches_by_type_discriminator()
    {
        var tick = Mt5WireParser.Parse(
            """{"version":1,"type":"market.tick","accountId":"a","time":1,"symbol":"XAUUSDm","bid":4053.2,"ask":4053.5}""");
        var typed = Assert.IsType<Mt5TickMessage>(tick);
        Assert.Equal(4053.2, typed.Bid);

        Assert.Null(Mt5WireParser.Parse("""{"version":1,"type":"execution.report","accountId":"a","time":1}"""));
    }
}

using TradingOs.Contracts;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// I2 (2026-09-26): the account as MT5's own account window shows it, carried
/// from the observer to the cockpit — and the execution agent's status in the
/// hub snapshot.
/// </summary>
public class Mt5WireI2Tests
{
    [Fact]
    public void The_account_window_travels_to_the_read_model()
    {
        const string json =
            """{"version":1,"type":"account.snapshot","accountId":"477029930","time":1790000000000,"balance":1046.84,"equity":1050.10,"margin":12.5,"freeMargin":1037.6,"currency":"USD","server":"Exness-MT5Trial9","company":"Exness Technologies Ltd","tradeMode":"demo","leverage":2000,"marginMode":"hedging","fifoClose":false,"marginLevel":8400.8,"tradeAllowed":true,"tradeExpert":true}""";
        var message = Assert.IsType<Mt5AccountSnapshotMessage>(Mt5WireParser.Parse(json));

        var summary = Mt5WireTranslator.ToAccountSummary(message, hello: null);

        Assert.Equal("Exness-MT5Trial9", summary.Server);
        Assert.Equal("demo", summary.TradeMode);
        Assert.Equal(2000, summary.Leverage);
        Assert.Equal("hedging", summary.MarginMode);
        Assert.Equal(12.5, summary.Margin);
        Assert.Equal(1037.6, summary.FreeMargin);
        Assert.Equal(8400.8, summary.MarginLevel);
        Assert.True(summary.TradeAllowed);
    }

    [Fact]
    public void An_observer_older_than_I2_still_yields_a_summary_with_unknowns()
    {
        const string json =
            """{"version":1,"type":"account.snapshot","accountId":"1","time":1,"balance":10,"equity":10,"margin":0,"freeMargin":10,"currency":"USD"}""";
        var summary = Mt5WireTranslator.ToAccountSummary((Mt5AccountSnapshotMessage)Mt5WireParser.Parse(json)!, hello: null);
        Assert.Null(summary.TradeMode);
        Assert.Null(summary.MarginMode);
        Assert.Null(summary.TradeAllowed);
    }

    [Fact]
    public void The_read_models_have_no_place_for_the_holder_name()
    {
        Assert.Null(typeof(Mt5AccountSnapshotMessage).GetProperty("Name"));
        Assert.Null(typeof(AccountSummary).GetProperty("Name"));
    }

    [Fact]
    public void Same_state_ignores_the_clocks_and_compares_experts_by_content()
    {
        var hello = (Mt5HelloMessage)Mt5WireParser.Parse(
            """{"version":1,"type":"agent.hello","accountId":"a","time":1,"agentId":"x","symbol":"EURUSDm","broker":"b","server":"s","orderTypes":["market"],"minVolume":0.01,"maxVolume":1,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"observe","agentVersion":"1.10","serverUtcOffsetMinutes":0,"attachedExperts":["X"]}""")!;
        var beat1 = new Mt5HeartbeatMessage(1, "agent.heartbeat", "a", 1, "x", 0, GatewaySilentMs: 10, AttachedExperts: ["X"]);
        var beat2 = new Mt5HeartbeatMessage(1, "agent.heartbeat", "a", 2, "x", 0, GatewaySilentMs: 99, AttachedExperts: ["X"]);
        var beat3 = new Mt5HeartbeatMessage(1, "agent.heartbeat", "a", 3, "x", 0, AttachedExperts: ["X", "Y"]);

        Assert.True(Mt5AgentStatus.From(hello, beat1).SameStateAs(Mt5AgentStatus.From(hello, beat2)));
        Assert.False(Mt5AgentStatus.From(hello, beat1).SameStateAs(Mt5AgentStatus.From(hello, beat3)));
    }

    [Fact]
    public void The_hub_snapshot_carries_the_agent_of_its_own_account()
    {
        var state = new GatewayState();
        var account = (Mt5AccountSnapshotMessage)Mt5WireParser.Parse(
            """{"version":1,"type":"account.snapshot","accountId":"477029930","time":1,"balance":10,"equity":10,"margin":0,"freeMargin":10,"currency":"USD"}""")!;
        state.SetAccount(Mt5WireTranslator.ToAccountSummary(account, hello: null));
        var hello = (Mt5HelloMessage)Mt5WireParser.Parse(
            """{"version":1,"type":"agent.hello","accountId":"477029930","time":1,"agentId":"mt5-execution-agent-1001","symbol":"EURUSDm","broker":"b","server":"s","orderTypes":["market"],"minVolume":0.01,"maxVolume":1,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"observe","agentVersion":"1.10","serverUtcOffsetMinutes":0,"identity":"ok"}""")!;
        var asked = new List<string>();

        var snapshot = state.Snapshot(true, accountId =>
        {
            asked.Add(accountId);
            return Mt5AgentStatus.From(hello, null);
        });

        Assert.Equal(new[] { "477029930" }, asked);
        Assert.Equal("mt5-execution-agent-1001", snapshot.ExecutionAgent!.AgentId);
        Assert.Null(state.Snapshot(true).ExecutionAgent);
    }
}

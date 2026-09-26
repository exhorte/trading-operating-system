using TradingOs.Contracts;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// I1 (2026-09-26): the wire as the MQL5 agent now writes it. Two of these
/// pin down defects found while writing I1: broker ids went out as bare
/// numbers where the contract says strings (the first real fill's report
/// would have been dropped as malformed), and a report's id was a fresh GUID
/// (a report sent again after a reconnection would have been stored twice).
/// </summary>
public class Mt5WireI1Tests
{
    // Field for field what TradingOsAgent.mq5 SendHello writes (token included).
    private const string AgentHello =
        """{"version":1,"type":"agent.hello","accountId":"477029930","time":1790000000000,"agentId":"mt5-execution-agent-1001","symbol":"XAUUSDm","broker":"Exness Technologies Ltd","server":"Exness-MT5Trial9","orderTypes":["market"],"minVolume":0.01,"maxVolume":200.00,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"observe","agentVersion":"1.10","serverUtcOffsetMinutes":180,"token":"secret-value","capabilities":["ping","halt"],"buildId":"1.10 2026.09.26 04:00","modeCeiling":"observe","identity":"ok","expectedAccountId":null,"tradeMode":"demo","marginMode":"hedging","fifoClose":false,"leverage":2000,"currency":"USD","terminalTradeAllowed":true,"expertTradeAllowed":false,"accountTradeExpert":true,"accountTradeAllowed":true,"tradable":false,"closable":false,"halted":false,"attachedExperts":["Ultimate_ICT_Gold_Scalper_v4.0"]}""";

    [Fact]
    public void The_agent_hello_parses_with_every_I1_field()
    {
        var hello = Assert.IsType<Mt5HelloMessage>(Mt5WireParser.Parse(AgentHello));
        Assert.Equal("477029930", hello.AccountId);
        Assert.Equal(new[] { "ping", "halt" }, hello.Capabilities);
        Assert.Equal("observe", hello.ModeCeiling);
        Assert.Equal("ok", hello.Identity);
        Assert.Null(hello.ExpectedAccountId);
        Assert.Equal("hedging", hello.MarginMode);
        Assert.Equal(2000, hello.Leverage);
        Assert.False(hello.ExpertTradeAllowed);
        Assert.Equal(new[] { "Ultimate_ICT_Gold_Scalper_v4.0" }, hello.AttachedExperts);
    }

    [Fact]
    public void The_hello_record_has_no_place_for_the_token()
    {
        Assert.Null(typeof(Mt5HelloMessage).GetProperty("Token"));
        var hello = Mt5WireParser.Parse(AgentHello)!;
        Assert.DoesNotContain("secret-value", hello.ToString());
    }

    [Fact]
    public void An_observer_hello_still_parses_its_I1_fields_stay_null()
    {
        const string observerHello =
            """{"version":1,"type":"agent.hello","accountId":"477029930","time":1,"agentId":"mt5-observer-1","symbol":"XAUUSDm","broker":"Exness","server":"Exness-MT5Trial9","orderTypes":["market"],"minVolume":0.01,"maxVolume":200,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"observe","agentVersion":"0.2.0-observer","serverUtcOffsetMinutes":180}""";
        var hello = Assert.IsType<Mt5HelloMessage>(Mt5WireParser.Parse(observerHello));
        Assert.Null(hello.Capabilities);
        Assert.Null(hello.Identity);
        Assert.Null(hello.Halted);
    }

    [Theory]
    [InlineData("\"123456789012\"", "\"10009\"")]  // the contract: strings (agent since I1)
    [InlineData("123456789012", "10009")]          // bare numbers (agent before I1) — no longer dropped
    public void A_fill_report_parses_whether_broker_ids_are_strings_or_numbers(string orderId, string retcode)
    {
        var json = $$"""{"version":1,"type":"execution.report","accountId":"477029930","time":1790000000000,"commandId":"cmd-1","status":"FILLED","symbol":"EURUSDm","side":"BUY","brokerOrderId":{{orderId}},"brokerPositionId":{{orderId}},"filledVolume":0.01,"averagePrice":1.17,"brokerRetcode":{{retcode}},"detail":"FILLED 0.01 lot"}""";

        var report = Assert.IsType<Mt5ReportMessage>(Mt5WireParser.Parse(json));
        Assert.Equal("123456789012", report.BrokerOrderId);
        Assert.Equal("123456789012", report.BrokerPositionId);
        Assert.Equal("10009", report.BrokerRetcode);
    }

    [Fact]
    public void A_reconciled_message_accepts_numeric_ids_too()
    {
        const string json =
            """{"version":1,"type":"execution.reconciled","accountId":"477029930","time":1,"commandId":"cmd-1","outcome":"executed","symbol":"EURUSDm","side":"BUY","brokerOrderId":42,"brokerPositionId":"43","filledVolume":0.01,"averagePrice":1.17,"brokerRetcode":null,"attempts":1,"detail":"d"}""";
        var reconciled = Assert.IsType<Mt5ReconciledMessage>(Mt5WireParser.Parse(json));
        Assert.Equal("42", reconciled.BrokerOrderId);
        Assert.Equal("43", reconciled.BrokerPositionId);
        Assert.Null(reconciled.BrokerRetcode);
    }

    [Fact]
    public void A_report_sent_again_after_a_reconnection_keeps_its_id()
    {
        const string original =
            """{"version":1,"type":"execution.report","accountId":"a","time":1790000000000,"commandId":"cmd-7","status":"SIMULATED","symbol":"EURUSDm","side":"BUY","brokerOrderId":null,"brokerPositionId":null,"filledVolume":null,"averagePrice":null,"brokerRetcode":null,"detail":"d"}""";
        const string replayed =
            """{"version":1,"type":"execution.report","accountId":"a","time":1790000000000,"commandId":"cmd-7","status":"SIMULATED","symbol":"EURUSDm","side":"BUY","brokerOrderId":null,"brokerPositionId":null,"filledVolume":null,"averagePrice":null,"brokerRetcode":null,"replayed":true,"detail":"d"}""";

        var first = Mt5WireTranslator.ToExecutionReport((Mt5ReportMessage)Mt5WireParser.Parse(original)!, "agent");
        var second = Mt5WireTranslator.ToExecutionReport((Mt5ReportMessage)Mt5WireParser.Parse(replayed)!, "agent");

        Assert.Equal(first.ReportId, second.ReportId);
        Assert.Equal("cmd-7:SIMULATED:1790000000000", first.ReportId);
        Assert.True(((Mt5ReportMessage)Mt5WireParser.Parse(replayed)!).Replayed);
    }
}

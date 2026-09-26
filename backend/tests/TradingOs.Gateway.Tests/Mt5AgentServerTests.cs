using System.Net;
using System.Net.Sockets;
using System.Text;
using TradingOs.Contracts;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// Loopback socket tests for Mt5AgentServer: a real TcpClient plays the MQL5
/// agent (newline-delimited lean JSON). Covers the framing (no BOM) and the
/// per-account registry — the parts that were only ever checked against a
/// real terminal until 2026-09-25, and were wrong.
/// </summary>
public class Mt5AgentServerTests
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

    /// <summary>I1: the token every hello must carry (TestGateway configures it).</summary>
    internal const string AgentToken = "test-agent-token";

    internal static string Hello(string accountId, string mode = "observe", string agentId = "mt5-execution-agent-1001", string? token = AgentToken, string extra = "") =>
        $$"""{"version":1,"type":"agent.hello","accountId":"{{accountId}}","time":1790000000000,"agentId":"{{agentId}}","symbol":"EURUSDm","broker":"Test Broker","server":"Test-Server","orderTypes":["market"],"minVolume":0.01,"maxVolume":100.00,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"{{mode}}","agentVersion":"1.00","serverUtcOffsetMinutes":180{{(token is null ? "" : $",\"token\":\"{token}\"")}}{{extra}}}""";

    private static string Heartbeat(string accountId) =>
        $$"""{"version":1,"type":"agent.heartbeat","accountId":"{{accountId}}","time":1790000000000,"agentId":"mt5-execution-agent-1001","latencyMs":0}""";

    [Fact]
    public async Task Commands_reach_the_agent_as_utf8_lines_without_a_byte_order_mark()
    {
        await using var gateway = await TestGateway.StartAsync();
        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1"));
        await Eventually(() => gateway.Server.IsConnected);

        const string command = """{"type":"execution.order","commandId":"cmd-1"}""";
        Assert.True(await gateway.Server.SendCommandAsync("acc-1", command, CancellationToken.None));

        var bytes = await agent.ReadLineBytesAsync();
        Assert.Equal(Encoding.UTF8.GetBytes(command + "\n"), bytes);
    }

    [Fact]
    public async Task Hello_and_routing_are_per_account()
    {
        await using var gateway = await TestGateway.StartAsync();
        using var observe = await gateway.ConnectAsync();
        using var paper = await gateway.ConnectAsync();
        await observe.SendAsync(Hello("acc-1", mode: "observe"));
        await paper.SendAsync(Hello("acc-2", mode: "paper", agentId: "mt5-execution-agent-2001"));
        await Eventually(() => gateway.Server.GetHello("acc-1") is not null && gateway.Server.GetHello("acc-2") is not null);

        Assert.Equal("observe", gateway.Server.GetHello("acc-1")!.Mode);
        Assert.Equal("paper", gateway.Server.GetHello("acc-2")!.Mode);
        Assert.Null(gateway.Server.GetHello("acc-3"));
        Assert.False(await gateway.Server.SendCommandAsync("acc-3", "{}", CancellationToken.None));

        Assert.True(await gateway.Server.SendCommandAsync("acc-2", """{"to":"acc-2"}""", CancellationToken.None));
        Assert.Equal(Encoding.UTF8.GetBytes("""{"to":"acc-2"}""" + "\n"), await paper.ReadLineBytesAsync());

        paper.Dispose();
        await Eventually(() => gateway.Server.GetHello("acc-2") is null);
        Assert.Equal("observe", gateway.Server.GetHello("acc-1")!.Mode);
        Assert.True(gateway.Server.IsConnected);
    }

    [Fact]
    public async Task A_second_live_agent_for_the_same_account_is_refused_and_the_first_keeps_it()
    {
        await using var gateway = await TestGateway.StartAsync();
        var refused = new List<string>();
        var changes = new List<bool>();
        gateway.Server.DuplicateAgentRefused += agentId => { lock (refused) { refused.Add(agentId); } };
        gateway.Server.ConnectionChanged += connected => { lock (changes) { changes.Add(connected); } };

        using var first = await gateway.ConnectAsync();
        await first.SendAsync(Hello("acc-1", agentId: "mt5-execution-agent-1001"));
        await Eventually(() => gateway.Server.IsConnected);

        using var second = await gateway.ConnectAsync();
        await second.SendAsync(Hello("acc-1", agentId: "mt5-execution-agent-1002"));

        Assert.True(await second.IsClosedByServerAsync());
        lock (refused) { Assert.Equal(new[] { "mt5-execution-agent-1002" }, refused); }
        Assert.Equal("mt5-execution-agent-1001", gateway.Server.GetHello("acc-1")!.AgentId);
        Assert.True(await gateway.Server.SendCommandAsync("acc-1", """{"to":"first"}""", CancellationToken.None));
        Assert.Equal(Encoding.UTF8.GetBytes("""{"to":"first"}""" + "\n"), await first.ReadLineBytesAsync());
        // The refused connection never counted: only the first hello changed the registry.
        lock (changes) { Assert.Equal(new[] { true }, changes); }
    }

    [Fact]
    public async Task A_new_hello_replaces_a_silent_agent_whose_late_close_does_not_unregister_it()
    {
        // Watchdog effectively off: the silent agent is still registered when
        // the new hello arrives, so the replacement path closes it AFTER the
        // new registration — the ordering that made the old remove-by-key code
        // report a live agent as disconnected.
        await using var gateway = await TestGateway.StartAsync(staleAfter: TimeSpan.FromMilliseconds(200), watchdogPeriod: TimeSpan.FromHours(1));
        using var stale = await gateway.ConnectAsync();
        await stale.SendAsync(Hello("acc-1", agentId: "mt5-execution-agent-old"));
        await Eventually(() => gateway.Server.IsConnected);
        await Task.Delay(400);

        using var fresh = await gateway.ConnectAsync();
        await fresh.SendAsync(Hello("acc-1", agentId: "mt5-execution-agent-new"));

        Assert.True(await stale.IsClosedByServerAsync());
        await Task.Delay(200); // let the replaced connection's cleanup run
        Assert.True(gateway.Server.IsConnected);
        Assert.Equal("mt5-execution-agent-new", gateway.Server.GetHello("acc-1")!.AgentId);
        Assert.True(await gateway.Server.SendCommandAsync("acc-1", """{"to":"new"}""", CancellationToken.None));
        Assert.Equal(Encoding.UTF8.GetBytes("""{"to":"new"}""" + "\n"), await fresh.ReadLineBytesAsync());
    }

    [Fact]
    public async Task A_silent_agent_is_closed_by_the_watchdog_and_stops_counting_as_connected()
    {
        await using var gateway = await TestGateway.StartAsync(staleAfter: TimeSpan.FromMilliseconds(300));
        var changes = new List<bool>();
        gateway.Server.ConnectionChanged += connected => { lock (changes) { changes.Add(connected); } };

        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1"));
        await Eventually(() => gateway.Server.IsConnected);

        await Eventually(() => !gateway.Server.IsConnected);
        Assert.True(await agent.IsClosedByServerAsync());
        lock (changes) { Assert.Equal(new[] { true, false }, changes); }
    }

    [Fact]
    public async Task Heartbeats_keep_an_agent_registered()
    {
        await using var gateway = await TestGateway.StartAsync(staleAfter: TimeSpan.FromSeconds(1));
        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1"));
        await Eventually(() => gateway.Server.IsConnected);

        for (var i = 0; i < 25; i++)
        {
            await Task.Delay(100);
            await agent.SendAsync(Heartbeat("acc-1"));
        }
        Assert.True(gateway.Server.IsConnected);
    }

    [Theory]
    [InlineData("SIMULATED", EventTypes.ExecutionOrderSimulated)]
    [InlineData("SUBMITTED", EventTypes.ExecutionOrderSubmitted)]
    [InlineData("FILLED", EventTypes.ExecutionOrderFilled)]
    [InlineData("PARTIALLY_FILLED", EventTypes.ExecutionOrderPartiallyFilled)]
    [InlineData("FAILED", EventTypes.ExecutionOrderFailed)]
    [InlineData("REJECTED", EventTypes.ExecutionCommandRejected)]
    public void Report_statuses_map_to_the_event_types_lib_contracts_declares(string status, string expected)
    {
        Assert.Equal(expected, Mt5AgentServer.ReportEventType(status));
    }

    // --- I1 (2026-09-26): agent token, ping, halt, status -------------------

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("wrong-token")]
    public async Task A_hello_without_the_right_token_is_refused_and_never_registered(string? token)
    {
        await using var gateway = await TestGateway.StartAsync();
        var refusals = new List<string>();
        gateway.Server.AgentRefused += (_, reason) => { lock (refusals) { refusals.Add(reason); } };

        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1", token: token));

        Assert.True(await agent.IsClosedByServerAsync());
        Assert.False(gateway.Server.IsConnected);
        Assert.Null(gateway.Server.GetHello("acc-1"));
        lock (refusals)
        {
            Assert.Single(refusals);
            Assert.DoesNotContain(AgentToken, refusals[0]);
            if (!string.IsNullOrEmpty(token))
            {
                Assert.DoesNotContain(token, refusals[0]);
            }
        }
    }

    [Fact]
    public async Task No_token_configured_refuses_every_agent_even_one_that_sends_a_token()
    {
        await using var gateway = await TestGateway.StartAsync(agentToken: "");
        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1"));

        Assert.True(await agent.IsClosedByServerAsync());
        Assert.False(gateway.Server.IsConnected);
    }

    [Fact]
    public async Task Pings_go_only_to_agents_that_declare_the_capability()
    {
        await using var gateway = await TestGateway.StartAsync(pingInterval: TimeSpan.FromMilliseconds(50));
        using var modern = await gateway.ConnectAsync();
        using var legacy = await gateway.ConnectAsync();
        await modern.SendAsync(Hello("acc-1", extra: ""","capabilities":["ping","halt"]"""));
        await legacy.SendAsync(Hello("acc-2", agentId: "mt5-execution-agent-2001"));
        await Eventually(() => gateway.Server.GetHello("acc-1") is not null && gateway.Server.GetHello("acc-2") is not null);

        var line = Encoding.UTF8.GetString(await modern.ReadLineBytesAsync());
        Assert.Contains("\"type\":\"control.ping\"", line);

        // The legacy agent's first line is the command sent now, not a ping.
        await Task.Delay(200);
        Assert.True(await gateway.Server.SendCommandAsync("acc-2", """{"to":"legacy"}""", CancellationToken.None));
        Assert.Equal(Encoding.UTF8.GetBytes("""{"to":"legacy"}""" + "\n"), await legacy.ReadLineBytesAsync());
    }

    [Fact]
    public async Task Halt_reaches_an_agent_that_understands_it_and_nobody_else()
    {
        await using var gateway = await TestGateway.StartAsync();
        using var modern = await gateway.ConnectAsync();
        using var legacy = await gateway.ConnectAsync();
        await modern.SendAsync(Hello("acc-1", extra: ""","capabilities":["ping","halt"]"""));
        await legacy.SendAsync(Hello("acc-2", agentId: "mt5-execution-agent-2001"));
        await Eventually(() => gateway.Server.GetHello("acc-1") is not null && gateway.Server.GetHello("acc-2") is not null);

        Assert.True(await gateway.Server.SendHaltAsync("acc-1", "emergency stop", CancellationToken.None));
        var line = Encoding.UTF8.GetString(await modern.ReadLineBytesAsync());
        Assert.Contains("\"type\":\"control.halt\"", line);
        Assert.Contains("\"reason\":\"emergency stop\"", line);

        Assert.False(await gateway.Server.SendHaltAsync("acc-2", "emergency stop", CancellationToken.None));
        Assert.False(await gateway.Server.SendHaltAsync("acc-9", "emergency stop", CancellationToken.None));
    }

    [Fact]
    public async Task Status_is_the_hello_overlaid_by_the_latest_heartbeat_and_refuses_a_halted_agent()
    {
        await using var gateway = await TestGateway.StartAsync();
        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("acc-1", extra:
            ""","capabilities":["ping","halt"],"identity":"ok","marginMode":"hedging","tradeMode":"demo","terminalTradeAllowed":false,"halted":false,"attachedExperts":[]"""));
        await Eventually(() => gateway.Server.GetStatus("acc-1") is not null);

        var status = gateway.Server.GetStatus("acc-1")!;
        Assert.Equal("ok", status.Identity);
        Assert.Equal("hedging", status.MarginMode);
        Assert.False(status.TerminalTradeAllowed);
        Assert.Null(status.CommandRefusal());

        await agent.SendAsync("""{"version":1,"type":"agent.heartbeat","accountId":"acc-1","time":1790000005000,"agentId":"mt5-execution-agent-1001","latencyMs":0,"mode":"observe","identity":"ok","terminalTradeAllowed":true,"halted":true,"gatewaySilentMs":1200,"attachedExperts":["Ultimate_ICT_Gold_Scalper_v4.0"]}""");
        await Eventually(() => gateway.Server.GetStatus("acc-1")!.Halted == true);

        status = gateway.Server.GetStatus("acc-1")!;
        Assert.True(status.TerminalTradeAllowed);
        Assert.Equal(new[] { "Ultimate_ICT_Gold_Scalper_v4.0" }, status.AttachedExperts);
        Assert.Equal(1200, status.GatewaySilentMs);
        Assert.StartsWith("HALTED:", status.CommandRefusal());
    }

    [Fact]
    public async Task An_identity_mismatch_is_registered_under_the_real_login_but_refuses_commands()
    {
        await using var gateway = await TestGateway.StartAsync();
        using var agent = await gateway.ConnectAsync();
        await agent.SendAsync(Hello("477029930", extra: ""","identity":"mismatch","expectedAccountId":"12345678" """));
        await Eventually(() => gateway.Server.GetStatus("477029930") is not null);

        var status = gateway.Server.GetStatus("477029930")!;
        Assert.Equal("12345678", status.ExpectedAccountId);
        Assert.StartsWith("IDENTITY_REFUSED:", status.CommandRefusal());
    }

    private static async Task Eventually(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow + Timeout;
        while (!condition())
        {
            if (DateTime.UtcNow > deadline)
            {
                throw new TimeoutException("condition not met within the timeout");
            }
            await Task.Delay(20);
        }
    }

    private sealed class TestGateway(Mt5AgentServer server, int port, CancellationTokenSource cts, Task run) : IAsyncDisposable
    {
        public Mt5AgentServer Server { get; } = server;

        public static async Task<TestGateway> StartAsync(
            TimeSpan? staleAfter = null,
            TimeSpan? watchdogPeriod = null,
            string? agentToken = AgentToken,
            TimeSpan? pingInterval = null)
        {
            var server = new Mt5AgentServer(0, IPAddress.Loopback, staleAfter, watchdogPeriod, agentToken, pingInterval);
            var cts = new CancellationTokenSource();
            var run = server.RunAsync(cts.Token);
            var port = await server.Listening.WaitAsync(Timeout);
            return new TestGateway(server, port, cts, run);
        }

        public async Task<Agent> ConnectAsync()
        {
            var client = new TcpClient();
            await client.ConnectAsync(IPAddress.Loopback, port);
            return new Agent(client);
        }

        public async ValueTask DisposeAsync()
        {
            cts.Cancel();
            try
            {
                await run.WaitAsync(Timeout);
            }
            catch (OperationCanceledException)
            {
                // expected on shutdown
            }
            cts.Dispose();
        }
    }

    private sealed class Agent(TcpClient client) : IDisposable
    {
        private readonly NetworkStream _stream = client.GetStream();

        public Task SendAsync(string line) => _stream.WriteAsync(Encoding.UTF8.GetBytes(line + "\n")).AsTask();

        public async Task<byte[]> ReadLineBytesAsync()
        {
            using var cts = new CancellationTokenSource(Timeout);
            var bytes = new List<byte>();
            var one = new byte[1];
            while (true)
            {
                var read = await _stream.ReadAsync(one, cts.Token);
                if (read == 0)
                {
                    throw new IOException("connection closed before a full line arrived");
                }
                bytes.Add(one[0]);
                if (one[0] == (byte)'\n')
                {
                    return bytes.ToArray();
                }
            }
        }

        public async Task<bool> IsClosedByServerAsync()
        {
            using var cts = new CancellationTokenSource(Timeout);
            var buffer = new byte[256];
            try
            {
                while (true)
                {
                    if (await _stream.ReadAsync(buffer, cts.Token) == 0)
                    {
                        return true;
                    }
                }
            }
            catch (IOException)
            {
                return true; // reset by the server
            }
            catch (OperationCanceledException)
            {
                return false; // still open after the timeout
            }
        }

        public void Dispose() => client.Dispose();
    }
}

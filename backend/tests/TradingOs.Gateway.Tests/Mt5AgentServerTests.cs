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

    private static string Hello(string accountId, string mode = "observe", string agentId = "mt5-execution-agent-1001") =>
        $$"""{"version":1,"type":"agent.hello","accountId":"{{accountId}}","time":1790000000000,"agentId":"{{agentId}}","symbol":"EURUSDm","broker":"Test Broker","server":"Test-Server","orderTypes":["market"],"minVolume":0.01,"maxVolume":100.00,"volumeStep":0.01,"fillingMode":"IOC","stopsLevelPoints":0,"mode":"{{mode}}","agentVersion":"1.00","serverUtcOffsetMinutes":180}""";

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

        public static async Task<TestGateway> StartAsync(TimeSpan? staleAfter = null, TimeSpan? watchdogPeriod = null)
        {
            var server = new Mt5AgentServer(0, IPAddress.Loopback, staleAfter, watchdogPeriod);
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

using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using TradingOs.Contracts;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// I0 (2026-09-26): the backend presents the observer token on the
/// handshake, and a connection that never came up is not a disconnection —
/// until then the gateway wrote an agent.disconnected envelope every 3 s for
/// as long as the observer was down. A raw TcpListener plays the observer's
/// side of the handshake.
/// </summary>
public class Mt5ObserverClientTests
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);
    private static readonly TimeSpan FastRetry = TimeSpan.FromMilliseconds(20);

    [Fact]
    public async Task The_handshake_carries_the_observer_token()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var client = new Mt5ObserverClient(new GatewayState(), $"ws://127.0.0.1:{port}/", "obs-token-1", FastRetry);
        using var cts = new CancellationTokenSource();
        var run = client.RunAsync(cts.Token);

        using var socket = await listener.AcceptTcpClientAsync().WaitAsync(Timeout);
        var head = await ReadRequestHeadAsync(socket.GetStream());
        await socket.GetStream().WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"));

        cts.Cancel();
        await run.WaitAsync(Timeout);
        Assert.Contains("Authorization: Bearer obs-token-1\r\n", head);
    }

    [Fact]
    public async Task Without_a_token_no_authorization_header_is_sent()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var client = new Mt5ObserverClient(new GatewayState(), $"ws://127.0.0.1:{port}/", null, FastRetry);
        using var cts = new CancellationTokenSource();
        var run = client.RunAsync(cts.Token);

        using var socket = await listener.AcceptTcpClientAsync().WaitAsync(Timeout);
        var head = await ReadRequestHeadAsync(socket.GetStream());

        cts.Cancel();
        await run.WaitAsync(Timeout);
        Assert.DoesNotContain("Authorization", head, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Failed_attempts_write_nothing_and_are_reported_once()
    {
        // An observer that refuses every handshake (a token mismatch). A port
        // with no listener would do too, but Windows takes ~2 s to refuse a
        // loopback connection — too slow to watch several retries.
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var attempts = 0;
        using var serverCts = new CancellationTokenSource();
        var server = Task.Run(async () =>
        {
            while (!serverCts.IsCancellationRequested)
            {
                using var socket = await listener.AcceptTcpClientAsync(serverCts.Token);
                await ReadRequestHeadAsync(socket.GetStream());
                await socket.GetStream().WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"));
                Interlocked.Increment(ref attempts);
            }
        });

        var client = new Mt5ObserverClient(new GatewayState(), $"ws://127.0.0.1:{port}/", "wrong", FastRetry);
        var envelopes = new List<string>();
        var changes = 0;
        var failures = new List<string>();
        client.EnvelopeReady += (type, _) => { lock (envelopes) { envelopes.Add(type); } };
        client.ConnectionChanged += _ => Interlocked.Increment(ref changes);
        client.ConnectionFailed += reason => { lock (failures) { failures.Add(reason); } };
        using var cts = new CancellationTokenSource();
        var run = client.RunAsync(cts.Token);

        await Eventually(() => Volatile.Read(ref attempts) >= 5);
        cts.Cancel();
        await run.WaitAsync(Timeout);
        serverCts.Cancel();
        try
        {
            await server.WaitAsync(Timeout);
        }
        catch (OperationCanceledException)
        {
            // expected on shutdown
        }

        Assert.Empty(envelopes);
        Assert.Equal(0, changes);
        Assert.Single(failures);
        Assert.Contains("403", failures[0]);
    }

    [Fact]
    public async Task A_lost_connection_is_one_disconnection_not_one_per_retry()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var client = new Mt5ObserverClient(new GatewayState(), $"ws://127.0.0.1:{port}/", "t", FastRetry);
        var disconnected = 0;
        var changes = new List<bool>();
        var failures = 0;
        client.EnvelopeReady += (type, _) =>
        {
            if (type == EventTypes.AgentDisconnected)
            {
                Interlocked.Increment(ref disconnected);
            }
        };
        client.ConnectionChanged += c => { lock (changes) { changes.Add(c); } };
        client.ConnectionFailed += _ => Interlocked.Increment(ref failures);
        using var cts = new CancellationTokenSource();
        var run = client.RunAsync(cts.Token);

        // Accept one real WebSocket handshake, then drop the connection and
        // stop listening: the observer went away and stays away.
        using (var socket = await listener.AcceptTcpClientAsync().WaitAsync(Timeout))
        {
            var stream = socket.GetStream();
            var head = await ReadRequestHeadAsync(stream);
            await stream.WriteAsync(Encoding.ASCII.GetBytes(SwitchingProtocols(head)));
            await Eventually(() => client.IsConnected);
        }
        listener.Stop();

        await Eventually(() => Volatile.Read(ref failures) == 1);
        await Task.Delay(200); // several more refused retries at 20 ms
        cts.Cancel();
        await run.WaitAsync(Timeout);

        Assert.Equal(1, disconnected);
        Assert.Equal([true, false], changes);
        Assert.Equal(1, failures);
    }

    private static string SwitchingProtocols(string requestHead)
    {
        var key = requestHead.Split("\r\n")
            .First(l => l.StartsWith("Sec-WebSocket-Key:", StringComparison.OrdinalIgnoreCase))
            .Split(':', 2)[1].Trim();
        var accept = Convert.ToBase64String(SHA1.HashData(Encoding.ASCII.GetBytes(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")));
        return "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
            $"Sec-WebSocket-Accept: {accept}\r\n\r\n";
    }

    private static async Task<string> ReadRequestHeadAsync(NetworkStream stream)
    {
        var buffer = new byte[8192];
        var total = 0;
        while (true)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(total)).AsTask().WaitAsync(Timeout);
            if (read == 0)
            {
                break;
            }
            total += read;
            if (Encoding.ASCII.GetString(buffer, 0, total).Contains("\r\n\r\n"))
            {
                break;
            }
        }
        return Encoding.ASCII.GetString(buffer, 0, total);
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
            await Task.Delay(10);
        }
    }
}

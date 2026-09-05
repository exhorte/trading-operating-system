using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Persistence;

namespace TradingOs.Host;

/// <summary>
/// Hosted service bridging the MT5 gateway to the SignalR hub: every translated
/// message becomes an Envelope&lt;T&gt; broadcast as an "event" to all dashboards
/// and enqueued for persistence (never blocking the realtime path).
/// </summary>
public sealed class GatewayBridgeService(
    Mt5ObserverClient observer,
    IHubContext<CockpitHub> hub,
    PersistenceWriter writer,
    ILogger<GatewayBridgeService> logger) : BackgroundService
{
    private const string Source = "mt5-gateway";

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    /// <summary>Enqueue an already-built envelope for persistence (shared with the hub).</summary>
    public static void Persist(PersistenceWriter writer, Envelope<object> envelope)
    {
        writer.Enqueue(new PersistedEvent(
            envelope.MessageId,
            envelope.CorrelationId,
            envelope.Type,
            envelope.Source,
            envelope.SentAt,
            JsonSerializer.Serialize(envelope.Payload, Json)));
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        observer.EnvelopeReady += (type, payload) =>
        {
            var envelope = Envelope<object>.Create(type, Source, payload);
            // Fire-and-forget: a broadcast failure must never stall the gateway.
            _ = hub.Clients.All.SendAsync("event", envelope, stoppingToken);
            Persist(writer, envelope);
        };
        observer.ConnectionChanged += (connected) =>
            logger.LogInformation("MT5 observer {State}", connected ? "connected" : "disconnected — retrying");

        // Drain the persistence channel alongside the observer connection.
        await Task.WhenAll(observer.RunAsync(stoppingToken), writer.RunAsync(stoppingToken));
    }
}

using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;

namespace TradingOs.Host;

/// <summary>
/// Hosted service bridging the MT5 gateway to the SignalR hub: every translated
/// message becomes an Envelope&lt;T&gt; broadcast as an "event" to all dashboards.
/// </summary>
public sealed class GatewayBridgeService(
    Mt5ObserverClient observer,
    IHubContext<CockpitHub> hub,
    ILogger<GatewayBridgeService> logger) : BackgroundService
{
    private const string Source = "mt5-gateway";

    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        observer.EnvelopeReady += (type, payload) =>
        {
            var envelope = Envelope<object>.Create(type, Source, payload);
            // Fire-and-forget: a broadcast failure must never stall the gateway.
            _ = hub.Clients.All.SendAsync("event", envelope, stoppingToken);
        };
        observer.ConnectionChanged += (connected) =>
            logger.LogInformation("MT5 observer {State}", connected ? "connected" : "disconnected — retrying");

        return observer.RunAsync(stoppingToken);
    }
}

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
    GatewayState state,
    IHubContext<CockpitHub> hub,
    PersistenceWriter writer,
    TradeCaptureRepository captures,
    ILogger<GatewayBridgeService> logger) : BackgroundService
{
    private const string Source = "mt5-gateway";

    /// <summary>T02a: how often to re-resolve the trading-day anchor even
    /// without a fresh agent.hello — covers a day rolling over on a
    /// long-lived connection. The write is idempotent (ON CONFLICT DO
    /// NOTHING), so re-emitting the same day's anchor is harmless.</summary>
    private static readonly TimeSpan DayAnchorRecheckInterval = TimeSpan.FromMinutes(5);

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
            RecordCaptureFactIfApplicable(type, payload, stoppingToken);
        };
        observer.ConnectionChanged += (connected) =>
            logger.LogInformation("MT5 observer {State}", connected ? "connected" : "disconnected — retrying");

        // Drain the persistence channel alongside the observer connection.
        await Task.WhenAll(
            observer.RunAsync(stoppingToken),
            writer.RunAsync(stoppingToken),
            DayAnchorRecheckLoopAsync(stoppingToken));
    }

    /// <summary>T02a: periodically re-resolve today's anchor from the last
    /// known offset, so a day that rolls over mid-connection (no fresh
    /// agent.hello) still gets its own row.</summary>
    private async Task DayAnchorRecheckLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(DayAnchorRecheckInterval, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            var offsetMinutes = state.ServerUtcOffsetMinutes;
            var accountId = state.Hello?.AccountId;
            if (offsetMinutes is null || accountId is null)
            {
                continue; // no hello received yet this run
            }

            var startsAtUtc = TradingDayAnchor.ResolveTodayStartUtc(DateTimeOffset.UtcNow, offsetMinutes.Value);
            var envelope = Envelope<object>.Create(
                EventTypes.RiskDayAnchorResolved,
                Source,
                new DayAnchorResolvedPayload(accountId, startsAtUtc.ToString("o")));
            _ = hub.Clients.All.SendAsync("event", envelope, ct);
            Persist(writer, envelope);
        }
    }

    /// <summary>
    /// T05: on the two real trade-lifecycle facts, write an immutable
    /// capture-fact row — see TradeCaptureRepository and schema.sql. Fire-
    /// and-forget from this synchronous event handler, like the hub
    /// broadcast above; a DB hiccup here must never stall the gateway.
    /// </summary>
    private void RecordCaptureFactIfApplicable(string type, object payload, CancellationToken ct)
    {
        if (type == EventTypes.JournalPositionOpened && payload is PositionOpenedPayload opened)
        {
            _ = RunCaptureWriteAsync(() => captures.RecordEntryAsync(
                opened.AccountId, opened.BrokerPositionId, opened.Symbol, CurrentTimeframe(),
                DateTimeOffset.Parse(opened.OpenedAt).UtcDateTime,
                opened.EntryPrice, opened.StopLoss, opened.TakeProfit, ct));
        }
        else if (type == EventTypes.JournalTradeClosed && payload is JournalTradeClosedPayload closed)
        {
            _ = RunCaptureWriteAsync(() => captures.RecordExitAsync(
                closed.AccountId, closed.BrokerPositionId, closed.ExitPrice,
                DateTimeOffset.Parse(closed.ClosedAt).UtcDateTime, ct));
        }
    }

    private string CurrentTimeframe() => state.Snapshot().Candles.FirstOrDefault()?.Timeframe ?? "M15";

    private async Task RunCaptureWriteAsync(Func<Task> write)
    {
        try
        {
            await write();
        }
        catch (OperationCanceledException)
        {
            // shutting down
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Failed to write a T05 trade-capture fact");
        }
    }
}

using System.Text.Json;

namespace TradingOs.Contracts;

/// <summary>
/// Lean MT5 edge wire — C# mirror of lib/contracts/mt5-wire.ts (ADR 0005).
/// Flat fields, epoch-ms time, uppercase side. The gateway translates these
/// into Envelope&lt;T&gt; + read models; nothing else may consume them.
/// </summary>
public abstract record Mt5Message(int Version, string Type, string AccountId, long Time);

public sealed record Mt5HelloMessage(
    int Version, string Type, string AccountId, long Time,
    string AgentId, string Symbol, string Broker, string Server,
    string[] OrderTypes, double MinVolume, double MaxVolume, double VolumeStep,
    string FillingMode, int StopsLevelPoints, string Mode, string AgentVersion)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5HeartbeatMessage(
    int Version, string Type, string AccountId, long Time,
    string AgentId, double LatencyMs)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5TickMessage(
    int Version, string Type, string AccountId, long Time,
    string Symbol, double Bid, double Ask)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5CandleMessage(
    int Version, string Type, string AccountId, long Time,
    string Symbol, string Timeframe, long OpenTime,
    double Open, double High, double Low, double Close, double Volume, bool Closed)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5AccountSnapshotMessage(
    int Version, string Type, string AccountId, long Time,
    double Balance, double Equity, double Margin, double FreeMargin, string Currency)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5PositionSnapshot(
    string BrokerPositionId, string Symbol, string Side, double Volume,
    double EntryPrice, double StopLoss, double TakeProfit, double FloatingPnl);

public sealed record Mt5PositionsSnapshotMessage(
    int Version, string Type, string AccountId, long Time,
    Mt5PositionSnapshot[] Positions)
    : Mt5Message(Version, Type, AccountId, Time);

/// <summary>Parses one lean wire JSON message by its "type" discriminator.</summary>
public static class Mt5WireParser
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    public static Mt5Message? Parse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("type", out var typeProp))
        {
            return null;
        }

        var type = typeProp.GetString();
        return type switch
        {
            "agent.hello" => doc.RootElement.Deserialize<Mt5HelloMessage>(Options),
            "agent.heartbeat" => doc.RootElement.Deserialize<Mt5HeartbeatMessage>(Options),
            "market.tick" => doc.RootElement.Deserialize<Mt5TickMessage>(Options),
            "market.candle" => doc.RootElement.Deserialize<Mt5CandleMessage>(Options),
            "account.snapshot" => doc.RootElement.Deserialize<Mt5AccountSnapshotMessage>(Options),
            "positions.snapshot" => doc.RootElement.Deserialize<Mt5PositionsSnapshotMessage>(Options),
            // ack/report/error are not used by the observe slice.
            _ => null,
        };
    }
}

using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;

namespace TradingOs.Host;

/// <summary>
/// Dashboard-facing SignalR hub (ADR 0005: SignalR is dashboard-side only).
/// Pattern: snapshot on connect via GetSnapshot, then "event" messages
/// carrying Envelope&lt;T&gt; (see dashboard_realtime_model.md).
/// </summary>
public sealed class CockpitHub(GatewayState state) : Hub
{
    /// <summary>Latest known state so a client can hydrate before the event stream.</summary>
    public CockpitSnapshotDto GetSnapshot() => state.Snapshot();
}

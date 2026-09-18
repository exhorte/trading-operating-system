using TradingOs.Contracts;

namespace TradingOs.Gateway;

/// <summary>
/// Latest known state translated from the MT5 edge, served to dashboards on
/// connect (snapshot + events pattern from dashboard_realtime_model.md).
/// Thread-safe via a simple lock; this slice is single-agent and stateless
/// beyond the current snapshot.
/// </summary>
public sealed class GatewayState
{
    private readonly object _lock = new();
    private readonly Dictionary<long, Candle> _candles = new();
    private const int MaxCandles = 300;

    private AccountSummary? _account;
    private Position[] _positions = [];
    private AgentStatus? _agent;

    public double? LastBid { get; private set; }

    public Mt5HelloMessage? Hello { get; private set; }

    /// <summary>T02a: last offset the observer measured against the MT5
    /// terminal — used to re-resolve the trading-day anchor periodically,
    /// without needing a fresh agent.hello for every day rollover.</summary>
    public int? ServerUtcOffsetMinutes { get; private set; }

    public void SetHello(Mt5HelloMessage hello, AgentStatus agent)
    {
        lock (_lock)
        {
            Hello = hello;
            _agent = agent;
            ServerUtcOffsetMinutes = hello.ServerUtcOffsetMinutes;
        }
    }

    public void SetAccount(AccountSummary account)
    {
        lock (_lock)
        {
            _account = account;
        }
    }

    public void SetPositions(Position[] positions)
    {
        lock (_lock)
        {
            _positions = positions;
        }
    }

    public void SetTick(double bid)
    {
        lock (_lock)
        {
            LastBid = bid;
        }
    }

    public void AddCandle(long openTimeMs, Candle candle)
    {
        lock (_lock)
        {
            _candles[openTimeMs] = candle;
            if (_candles.Count > MaxCandles)
            {
                _candles.Remove(_candles.Keys.Min());
            }
        }
    }

    public void MarkAgentDisconnected()
    {
        lock (_lock)
        {
            if (_agent is not null)
            {
                _agent = _agent with { State = "disconnected" };
            }
        }
    }

    public void MarkAgentHeartbeat(double latencyMs, string atIso)
    {
        lock (_lock)
        {
            if (_agent is not null)
            {
                _agent = _agent with { State = "connected", LatencyMs = latencyMs, LastHeartbeatAt = atIso };
            }
        }
    }

    /// <summary>
    /// <paramref name="executionAgentConnected"/> is required, not defaulted:
    /// this state object only ever learns about the read-only observer (it is
    /// the observer's hello that calls SetHello), so it cannot answer for the
    /// EA-05 agent on its own — the caller, which holds Mt5AgentServer, must
    /// say. Defaulting it either way would re-create the exact confusion that
    /// made connectionGate read the observer's link as execution readiness.
    /// </summary>
    public CockpitSnapshotDto Snapshot(bool executionAgentConnected)
    {
        lock (_lock)
        {
            var candles = _candles.OrderBy(kv => kv.Key).Select(kv => kv.Value).ToArray();
            var agents = _agent is null ? Array.Empty<AgentStatus>() : [_agent];
            return new CockpitSnapshotDto(_account, _positions, agents, candles, executionAgentConnected);
        }
    }
}

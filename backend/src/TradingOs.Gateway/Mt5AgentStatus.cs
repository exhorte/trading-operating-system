using TradingOs.Contracts;

namespace TradingOs.Gateway;

/// <summary>
/// I1 (2026-09-26): what the execution agent of one account says about
/// itself — its hello, overlaid with its latest heartbeat for everything that
/// can change while it is connected (Algo Trading clicked, another EA
/// attached, the halt set on the chart). Null fields: an agent older than I1,
/// which does not publish them. Never carries the agent token.
///
/// Read by CockpitHub.SubmitCommand (a refused identity or a halted agent
/// gets no command) and, from I2, by the cockpit's account screen.
/// </summary>
public sealed record Mt5AgentStatus(
    string AccountId,
    string AgentId,
    string AgentVersion,
    string? BuildId,
    string Mode,
    string? ModeCeiling,
    string? Identity,
    string? ExpectedAccountId,
    string Server,
    string? TradeMode,
    string? MarginMode,
    bool? FifoClose,
    bool? TerminalTradeAllowed,
    bool? ExpertTradeAllowed,
    bool? AccountTradeExpert,
    bool? AccountTradeAllowed,
    bool? Tradable,
    bool? Closable,
    bool? Halted,
    string[] AttachedExperts,
    long? GatewaySilentMs,
    long? LastHeartbeatTime)
{
    public static Mt5AgentStatus From(Mt5HelloMessage hello, Mt5HeartbeatMessage? beat) => new(
        AccountId: hello.AccountId,
        AgentId: hello.AgentId,
        AgentVersion: hello.AgentVersion,
        BuildId: hello.BuildId,
        Mode: beat?.Mode ?? hello.Mode,
        ModeCeiling: hello.ModeCeiling,
        Identity: beat?.Identity ?? hello.Identity,
        ExpectedAccountId: hello.ExpectedAccountId,
        Server: hello.Server,
        TradeMode: hello.TradeMode,
        MarginMode: hello.MarginMode,
        FifoClose: hello.FifoClose,
        TerminalTradeAllowed: beat?.TerminalTradeAllowed ?? hello.TerminalTradeAllowed,
        ExpertTradeAllowed: beat?.ExpertTradeAllowed ?? hello.ExpertTradeAllowed,
        AccountTradeExpert: beat?.AccountTradeExpert ?? hello.AccountTradeExpert,
        AccountTradeAllowed: beat?.AccountTradeAllowed ?? hello.AccountTradeAllowed,
        Tradable: hello.Tradable,
        Closable: hello.Closable,
        Halted: beat?.Halted ?? hello.Halted,
        AttachedExperts: beat?.AttachedExperts ?? hello.AttachedExperts ?? [],
        GatewaySilentMs: beat?.GatewaySilentMs,
        LastHeartbeatTime: beat?.Time);

    /// <summary>Why no command may go to this agent right now, or null. Only
    /// what the agent itself reported — an absent field (older agent) is not
    /// a refusal here; the agent's own barriers still apply.</summary>
    public string? CommandRefusal() =>
        Halted == true ? "HALTED: the agent's local kill switch is set — lifted only on the MT5 chart"
        : Identity is not null && Identity != "ok"
            ? $"IDENTITY_REFUSED: the agent reports identity '{Identity}' for login {AccountId}"
            : null;
}

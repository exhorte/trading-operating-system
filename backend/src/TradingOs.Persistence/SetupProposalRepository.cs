using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// EA-02 — read surface for GET /api/setup-proposals and GET /api/trades/closed
/// (context/product/tools/EA-02-observe-taux-accord.md). Rows are written by
/// scripts/run-setup-detection.ts (a Node/tsx worker), not by this backend —
/// this repository only reads, same "glue DB, not unit-tested" convention as
/// CandleRepository/TradeCaptureRepository.
/// </summary>
public sealed record SetupProposalRow(
    string Symbol,
    DateTime EventAt,
    string Status,
    string? Stage,
    string? Detail,
    string? Side,
    string? SweptLevelKind,
    double? SweptLevelPrice,
    double? EntryPrice,
    double? StopLoss,
    double? TakeProfit,
    double? CostRatio,
    double? RiskRewardRatio);

/// <summary>Read model for the reconciliation view. Deliberately its own
/// type, not the write-side ClosedTradeRow (PersistenceMapper.cs, DateTimeOffset):
/// that one has never been read back via Dapper, and DateTimeOffset in a
/// record's positional constructor is exactly the class of Dapper
/// materialization bug /api/audit/recent's own comment already warns
/// about (DateTimeOffset vs DateTime, 2026-07-12) — confirmed here the same
/// way, reproduced against the real DB before switching to DateTime. Also:
/// no RealizedPnl field, on purpose (ADR 0011) — this repository has no
/// performance metric to leak into a reconciliation view that must not
/// have one.</summary>
public sealed record ClosedTradeSummaryRow(
    string BrokerPositionId,
    string Symbol,
    string Side,
    double Volume,
    double ExitPrice,
    DateTime ClosedAt,
    DateTime OpenedAt);

public sealed class SetupProposalRepository(string connectionString)
{
    public async Task<IReadOnlyList<SetupProposalRow>> GetRecentAsync(
        DateTime sinceUtc, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<SetupProposalRow>(
            """
            SELECT symbol AS Symbol, event_at AS EventAt, status AS Status,
                   stage AS Stage, detail AS Detail, side AS Side,
                   swept_level_kind AS SweptLevelKind, swept_level_price AS SweptLevelPrice,
                   entry_price AS EntryPrice, stop_loss AS StopLoss, take_profit AS TakeProfit,
                   cost_ratio AS CostRatio, risk_reward_ratio AS RiskRewardRatio
            FROM setup_proposals
            WHERE event_at >= @sinceUtc
            ORDER BY event_at DESC
            """,
            new { sinceUtc });
        return rows.AsList();
    }

    /// <summary>Was missing before EA-02: no GET surface existed for
    /// closed_trades (T02b writes it, nothing read it back over HTTP). The
    /// reconciliation view matches a proposal's detection time against when
    /// a position was OPENED, not closed — closed_trades alone has no open
    /// time, so this joins position_opens (T02a) for it rather than
    /// approximating from closed_at.</summary>
    public async Task<IReadOnlyList<ClosedTradeSummaryRow>> GetClosedTradesAsync(
        string accountId, DateTime fromUtc, DateTime toUtc, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<ClosedTradeSummaryRow>(
            """
            SELECT ct.broker_position_id AS BrokerPositionId, ct.symbol AS Symbol, ct.side AS Side,
                   ct.volume AS Volume, ct.exit_price AS ExitPrice, ct.closed_at AS ClosedAt,
                   po.opened_at AS OpenedAt
            FROM closed_trades ct
            JOIN position_opens po
              ON po.account_id = ct.account_id AND po.broker_position_id = ct.broker_position_id
            WHERE ct.account_id = @accountId AND ct.closed_at >= @fromUtc AND ct.closed_at <= @toUtc
            ORDER BY ct.closed_at ASC
            """,
            new { accountId, fromUtc, toUtc });
        return rows.AsList();
    }
}

using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T06 — read surface for GET /api/journal/trades
/// (context/product/tools/T06-journal-auto.md). Pure read/aggregation over
/// closed_trades (T02b) + position_opens (T02a) + trade_captures (T05) — no
/// new table, per the fiche's Décision 2: those three already carry
/// everything backlog.md described as "a new journal data model".
///
/// LEFT JOINs throughout, not the INNER JOIN SetupProposalRepository.
/// GetClosedTradesAsync uses for its own, narrower purpose: a trade must
/// stay visible here even if its open was never observed (a position
/// already open at first boot) or it predates T05 (no capture) — a journal
/// that silently drops rows on a missing join is worse than one that shows
/// a fact as unknown. EntryPrice/StopLoss only exist via trade_captures —
/// closed_trades/position_opens never store a price — so both are null for
/// any trade without a capture, same reason HasCapture exists (fiche
/// Décision 3: never a dead link).
///
/// DateTime, not DateTimeOffset — same Dapper-materialization convention
/// ClosedTradeSummaryRow's own comment documents (2026-07-12 bug), followed
/// here without re-litigating it.
/// </summary>
public sealed record JournalTradeRow(
    string BrokerPositionId,
    string Symbol,
    string Side,
    double Volume,
    double? EntryPrice,
    double ExitPrice,
    double RealizedPnl,
    double? StopLoss,
    DateTime? OpenedAt,
    DateTime ClosedAt,
    bool HasCapture);

public sealed class JournalRepository(string connectionString)
{
    public async Task<IReadOnlyList<JournalTradeRow>> GetTradesAsync(
        string accountId, DateTime fromUtc, DateTime toUtc, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<JournalTradeRow>(
            """
            SELECT ct.broker_position_id AS BrokerPositionId, ct.symbol AS Symbol, ct.side AS Side,
                   ct.volume AS Volume, tc.entry_price AS EntryPrice, ct.exit_price AS ExitPrice,
                   ct.realized_pnl AS RealizedPnl, tc.stop_loss AS StopLoss,
                   po.opened_at AS OpenedAt, ct.closed_at AS ClosedAt,
                   (tc.broker_position_id IS NOT NULL) AS HasCapture
            FROM closed_trades ct
            LEFT JOIN position_opens po
              ON po.account_id = ct.account_id AND po.broker_position_id = ct.broker_position_id
            LEFT JOIN trade_captures tc
              ON tc.account_id = ct.account_id AND tc.broker_position_id = ct.broker_position_id
              AND tc.kind = 'entry'
            WHERE ct.account_id = @accountId AND ct.closed_at >= @fromUtc AND ct.closed_at <= @toUtc
            ORDER BY ct.closed_at DESC
            """,
            new { accountId, fromUtc, toUtc });
        return rows.AsList();
    }
}

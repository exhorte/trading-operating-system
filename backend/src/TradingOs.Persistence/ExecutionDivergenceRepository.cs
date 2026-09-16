using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// EA-06 — read surface for GET /api/execution/divergence
/// (context/product/tools/EA-06-reconciliation.md): positions the terminal
/// reports that this agent didn't open, and any commandId it had to resolve
/// after the fact. Not the same "reconciliation" as EA-02's setup-vs-trade
/// view (SetupProposalRepository.GetClosedTradesAsync) — same English word,
/// unrelated feature; do not conflate the two.
///
/// DateTime, not DateTimeOffset — ClosedTradeSummaryRow's own comment
/// documents why (Dapper materialization bug, 2026-07-12), same convention
/// followed here without re-litigating it.
/// </summary>
public sealed record ExternalPositionRow(
    string BrokerPositionId, string Symbol, string Side, double Volume,
    int MagicNumber, string? KnownCommandId, DateTime ScannedAt);

public sealed record ReconciliationRow(
    string CommandId, string Outcome, string? Symbol, string? Side,
    string? BrokerPositionId, double? FilledVolume, double? AveragePrice,
    int Attempts, string Detail, DateTime ReconciledAt);

public sealed class ExecutionDivergenceRepository(string connectionString)
{
    public async Task<IReadOnlyList<ExternalPositionRow>> GetExternalPositionsAsync(
        string accountId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<ExternalPositionRow>(
            """
            SELECT broker_position_id AS BrokerPositionId, symbol AS Symbol, side AS Side,
                   volume AS Volume, magic_number AS MagicNumber, known_command_id AS KnownCommandId,
                   scanned_at AS ScannedAt
            FROM position_scans
            WHERE account_id = @accountId AND is_external = true
            ORDER BY scanned_at DESC
            """,
            new { accountId });
        return rows.AsList();
    }

    public async Task<IReadOnlyList<ReconciliationRow>> GetReconciliationsAsync(
        string accountId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<ReconciliationRow>(
            """
            SELECT command_id AS CommandId, outcome AS Outcome, symbol AS Symbol, side AS Side,
                   broker_position_id AS BrokerPositionId, filled_volume AS FilledVolume,
                   average_price AS AveragePrice, attempts AS Attempts, detail AS Detail,
                   reconciled_at AS ReconciledAt
            FROM command_reconciliations
            WHERE account_id = @accountId
            ORDER BY reconciled_at DESC
            """,
            new { accountId });
        return rows.AsList();
    }
}

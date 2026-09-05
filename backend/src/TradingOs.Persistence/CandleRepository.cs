using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T05 — reads a bounded candle range for the cockpit's on-demand chart
/// render (GET /api/candles). The `candles` hypertable already exists
/// (T02a-era schema); this is its first read repository since the realtime
/// path only ever streams the live tail through SignalR.
/// </summary>
public sealed record CandleRangeRow(
    string Symbol, string Timeframe, DateTime OpenTime,
    double Open, double High, double Low, double Close, double Volume, bool Closed);

public sealed class CandleRepository(string connectionString)
{
    /// <summary>[from, to] inclusive — callers pass a trade-capture's stored
    /// window_start_utc/window_end_utc verbatim, so the non-anticipation
    /// boundary is exactly what was recorded, never widened.</summary>
    public async Task<IReadOnlyList<CandleRangeRow>> GetRangeAsync(
        string symbol, string timeframe, DateTime fromUtc, DateTime toUtc, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<CandleRangeRow>(
            """
            SELECT symbol AS Symbol, timeframe AS Timeframe, open_time AS OpenTime,
                   open AS Open, high AS High, low AS Low, close AS Close,
                   volume AS Volume, closed AS Closed
            FROM candles
            WHERE symbol = @symbol AND timeframe = @timeframe
              AND open_time >= @fromUtc AND open_time <= @toUtc
            ORDER BY open_time ASC
            """,
            new { symbol, timeframe, fromUtc, toUtc });
        return rows.AsList();
    }
}

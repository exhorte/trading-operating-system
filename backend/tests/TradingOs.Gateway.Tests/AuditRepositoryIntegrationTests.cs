using Npgsql;
using TradingOs.Persistence;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// Integration test against the local TimescaleDB (docker compose, port 5433).
/// Guards the read path that silently broke on 2026-07-12: the SQL, the real
/// column names, and the Dapper constructor mapping (timestamptz → DateTime).
/// When the database is not reachable (CI without Docker), the test returns
/// early — xUnit v2 has no runtime skip; treat an early return as "not run".
/// </summary>
public class AuditRepositoryIntegrationTests
{
    private const string ConnectionString =
        "Host=localhost;Port=5433;Database=tradingos;Username=tradingos;Password=tradingos_dev;Timeout=2";

    private static async Task<bool> DbReachableAsync()
    {
        try
        {
            await using var conn = new NpgsqlConnection(ConnectionString);
            await conn.OpenAsync();
            return true;
        }
        catch
        {
            return false;
        }
    }

    [Fact]
    public async Task RecentAsync_maps_rows_and_honors_the_limit()
    {
        if (!await DbReachableAsync())
        {
            return; // DB not running locally — nothing to assert against.
        }

        var repo = new AuditRepository(ConnectionString);

        // Must not throw (SQL + column names + Dapper mapping) and must clamp.
        var rows = await repo.RecentAsync(limit: 3, CancellationToken.None);

        Assert.True(rows.Count <= 3);
        foreach (var row in rows)
        {
            Assert.False(string.IsNullOrEmpty(row.MessageId));
            Assert.False(string.IsNullOrEmpty(row.Type));
            Assert.NotEqual(default, row.SentAt);
        }
    }
}

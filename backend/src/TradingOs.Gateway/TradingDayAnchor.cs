namespace TradingOs.Gateway;

/// <summary>
/// Pure day-boundary math (T02a). The broker's trading day starts at server
/// midnight, not 00:00 UTC — the offset comes from the MT5 terminal (see
/// mt5_observer.py's resolve_server_utc_offset_minutes), never hardcoded,
/// since it shifts with DST. This only resolves "today's" instant; callers
/// re-resolve periodically so a day rollover is picked up without needing a
/// fresh agent.hello.
/// </summary>
public static class TradingDayAnchor
{
    public static DateTimeOffset ResolveTodayStartUtc(DateTimeOffset utcNow, int serverUtcOffsetMinutes)
    {
        var offset = TimeSpan.FromMinutes(serverUtcOffsetMinutes);
        var serverLocalNow = utcNow.ToOffset(offset);
        var serverMidnightLocal = new DateTimeOffset(
            serverLocalNow.Year, serverLocalNow.Month, serverLocalNow.Day, 0, 0, 0, offset);
        return serverMidnightLocal.ToUniversalTime();
    }
}

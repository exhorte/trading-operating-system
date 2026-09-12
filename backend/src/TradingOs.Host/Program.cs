using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Host;
using TradingOs.Persistence;

var builder = WebApplication.CreateBuilder(args);

// Dashboard origin for local dev; SignalR needs credentials-compatible CORS.
var dashboardOrigin = builder.Configuration["Cockpit:DashboardOrigin"] ?? "http://localhost:3000";
var observerUrl = builder.Configuration["Cockpit:ObserverUrl"] ?? "ws://localhost:8765";
var connectionString = builder.Configuration.GetConnectionString("TradingOs")
    ?? "Host=localhost;Port=5433;Database=tradingos;Username=tradingos;Password=tradingos_dev";

builder.Services.AddSignalR();
builder.Services.AddCors(options =>
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(dashboardOrigin).AllowAnyHeader().AllowAnyMethod().AllowCredentials()));

builder.Services.AddSingleton<GatewayState>();
builder.Services.AddSingleton(sp => new Mt5ObserverClient(sp.GetRequiredService<GatewayState>(), observerUrl));
builder.Services.AddSingleton(new PersistenceWriter(connectionString));
builder.Services.AddSingleton(new AuditRepository(connectionString));
builder.Services.AddSingleton(new RiskTodayRepository(connectionString));
builder.Services.AddSingleton(new NewsCalendarRepository(connectionString));
builder.Services.AddSingleton(new TradeCaptureRepository(connectionString));
builder.Services.AddSingleton(new CandleRepository(connectionString));
builder.Services.AddSingleton(new SetupProposalRepository(connectionString));
builder.Services.AddHttpClient("fred");
builder.Services.AddHostedService<GatewayBridgeService>();
builder.Services.AddHostedService<NewsCalendarService>();

var app = builder.Build();

app.UseCors();

// Minimal HTTP surface (backend_plan.md): health + audit export only.
app.MapGet("/health", (PersistenceWriter writer) => Results.Ok(new
{
    status = "ok",
    observer = observerUrl,
    db = writer.Status.DbUp ? "ok" : "down",
    persisted = writer.Status.Written,
    dropped = writer.Status.Dropped,
    queued = writer.Status.Queued,
    dbError = writer.Status.LastError,
}));
app.MapGet("/api/audit/recent", async (
    AuditRepository audit,
    ILogger<Program> logger,
    CancellationToken ct,
    int limit = 50) =>
{
    try
    {
        return Results.Ok(await audit.RecentAsync(limit, ct));
    }
    catch (Exception ex)
    {
        // Log the real exception and surface its message — a bare 503 hid a
        // Dapper mapping bug (DateTimeOffset vs DateTime) on 2026-07-12.
        logger.LogError(ex, "/api/audit/recent failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/risk/today", async (
    RiskTodayRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId) =>
{
    try
    {
        return Results.Ok(await repository.GetAsync(accountId, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/risk/today failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/calendar/upcoming", async (
    NewsCalendarRepository repository,
    ILogger<Program> logger,
    CancellationToken ct) =>
{
    try
    {
        var rows = await repository.GetUpcomingOrNullAsync(DateTime.UtcNow, ct);
        var releases = rows?.Select(r => new UpcomingRelease(r.ReleaseId, r.Label, r.ScheduledAt.ToString("o")));
        return Results.Ok(new { releases });
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/calendar/upcoming failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/captures/{brokerPositionId}", async (
    string brokerPositionId,
    TradeCaptureRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId) =>
{
    try
    {
        var (entry, exit) = await repository.GetAsync(accountId, brokerPositionId, ct);
        return Results.Ok(new { entry, exit });
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/captures/{BrokerPositionId} failed", brokerPositionId);
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/candles", async (
    CandleRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string symbol,
    string timeframe,
    DateTime from,
    DateTime to) =>
{
    try
    {
        return Results.Ok(await repository.GetRangeAsync(symbol, timeframe, from, to, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/candles failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/setup-proposals", async (
    SetupProposalRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    DateTime since) =>
{
    try
    {
        return Results.Ok(await repository.GetRecentAsync(since, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/setup-proposals failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/trades/closed", async (
    SetupProposalRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId,
    DateTime from,
    DateTime to) =>
{
    try
    {
        return Results.Ok(await repository.GetClosedTradesAsync(accountId, from, to, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/trades/closed failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapHub<CockpitHub>("/hub/cockpit");

app.Run("http://localhost:5080");

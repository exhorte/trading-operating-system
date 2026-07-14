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
builder.Services.AddSingleton(new BacktestRepository(connectionString));
builder.Services.AddHostedService<GatewayBridgeService>();

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
app.MapGet("/api/backtests", async (BacktestRepository backtests, ILogger<Program> logger, CancellationToken ct) =>
{
    try
    {
        return Results.Ok(await backtests.RunsAsync(ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/backtests failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/backtests/{runId}", async (string runId, BacktestRepository backtests, ILogger<Program> logger, CancellationToken ct) =>
{
    try
    {
        var (run, trades) = await backtests.RunAsync(runId, ct);
        return run is null ? Results.NotFound() : Results.Ok(new { run, trades });
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/backtests/{RunId} failed", runId);
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapHub<CockpitHub>("/hub/cockpit");

app.Run("http://localhost:5080");

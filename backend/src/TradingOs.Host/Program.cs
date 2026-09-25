using System.Net;
using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Host;
using TradingOs.Persistence;

var builder = WebApplication.CreateBuilder(args);

// Dashboard origins for local dev; SignalR needs credentials-compatible CORS.
// Comma-separated since 2026-09-20: the cockpit runs on 3000 in backend mode
// and on 3001 in the mock preview (.claude/launch.json declares both), and a
// single allowed origin silently broke every HTTP-backed panel on 3001 —
// journal, positions, compliance badge — as an opaque CORS failure.
var dashboardOrigins = (builder.Configuration["Cockpit:DashboardOrigin"] ?? "http://localhost:3000")
    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
var observerUrl = builder.Configuration["Cockpit:ObserverUrl"] ?? "ws://localhost:8765";
// EA-05: plain TCP, not WSS — see Mt5AgentServer's doc comment for why.
// Distinct port from the observer's WS server (8765): two processes, two
// responsibilities, never merged (ADR 0010).
var agentPort = builder.Configuration.GetValue<int?>("Cockpit:AgentPort") ?? 9765;
var connectionString = builder.Configuration.GetConnectionString("TradingOs")
    ?? "Host=localhost;Port=5433;Database=tradingos;Username=tradingos;Password=tradingos_dev";
// Native run stays loopback-only by default (see Mt5AgentServer's doc
// comment); the Docker image is the one caller that sets both of these,
// since a container's own loopback isn't reachable through its published
// ports — the process inside must bind all interfaces for Docker's port
// mapping to reach it. Host-side publishing is still restricted to
// 127.0.0.1 (docker-compose.yml), so the personal/single-machine posture
// doesn't change from outside the container.
var listenUrl = builder.Configuration["Cockpit:ListenUrl"] ?? "http://localhost:5080";
var agentBindAny = builder.Configuration.GetValue<bool>("Cockpit:AgentBindAny");

builder.Services.AddSignalR();
builder.Services.AddCors(options =>
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(dashboardOrigins).AllowAnyHeader().AllowAnyMethod().AllowCredentials()));

builder.Services.AddSingleton<GatewayState>();
builder.Services.AddSingleton(sp => new Mt5ObserverClient(sp.GetRequiredService<GatewayState>(), observerUrl));
// Silence after which an execution agent counts as dead (terminal crash,
// half-open TCP) and stops holding its account — the agent heartbeats every
// InpHeartbeatSeconds (default 5), so keep this well above that.
var agentStaleSeconds = builder.Configuration.GetValue<int?>("Cockpit:AgentStaleSeconds") ?? 30;
builder.Services.AddSingleton(new Mt5AgentServer(
    agentPort,
    agentBindAny ? IPAddress.Any : IPAddress.Loopback,
    TimeSpan.FromSeconds(agentStaleSeconds)));
builder.Services.AddSingleton(new PersistenceWriter(connectionString));
builder.Services.AddSingleton(new AuditRepository(connectionString));
builder.Services.AddSingleton(new RiskTodayRepository(connectionString));
builder.Services.AddSingleton(new NewsCalendarRepository(connectionString));
builder.Services.AddSingleton(new TradeCaptureRepository(connectionString));
builder.Services.AddSingleton(new CandleRepository(connectionString));
builder.Services.AddSingleton(new SetupProposalRepository(connectionString));
builder.Services.AddSingleton(new ExecutionDivergenceRepository(connectionString));
builder.Services.AddSingleton(new JournalRepository(connectionString));
builder.Services.AddSingleton(new RiskLockoutHistoryRepository(connectionString));
builder.Services.AddSingleton(new AccountSettingsRepository(connectionString));
builder.Services.AddHttpClient("fred");
builder.Services.AddHostedService<GatewayBridgeService>();
builder.Services.AddHostedService<NewsCalendarService>();

var app = builder.Build();

app.UseCors();

// Minimal HTTP surface (backend_plan.md): health + audit export only.
app.MapGet("/health", (PersistenceWriter writer, Mt5AgentServer agentServer) => Results.Ok(new
{
    status = "ok",
    observer = observerUrl,
    agentPort,
    agentConnected = agentServer.IsConnected,
    db = writer.Status.DbUp ? "ok" : "down",
    persisted = writer.Status.Written,
    dropped = writer.Status.Dropped,
    queued = writer.Status.Queued,
    dbError = writer.Status.LastError,
    unmapped = writer.Status.Unmapped,
    mappingError = writer.Status.LastMappingError,
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
app.MapGet("/api/journal/trades", async (
    JournalRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId,
    DateTime from,
    DateTime to) =>
{
    try
    {
        return Results.Ok(await repository.GetTradesAsync(accountId, from, to, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/journal/trades failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/risk/lockouts", async (
    RiskLockoutHistoryRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId,
    DateTime to) =>
{
    try
    {
        return Results.Ok(await repository.GetUpToAsync(accountId, to, ct));
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/risk/lockouts failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
app.MapGet("/api/execution/divergence", async (
    ExecutionDivergenceRepository repository,
    ILogger<Program> logger,
    CancellationToken ct,
    string accountId) =>
{
    try
    {
        var externalPositions = await repository.GetExternalPositionsAsync(accountId, ct);
        var reconciliations = await repository.GetReconciliationsAsync(accountId, ct);
        return Results.Ok(new { externalPositions, reconciliations });
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "/api/execution/divergence failed");
        return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
    }
});
// T12 incrément 2: the Settings screen's ledger — see AccountSettingsEndpoints.
app.MapAccountSettingsEndpoints();
app.MapHub<CockpitHub>("/hub/cockpit");

app.Run(listenUrl);

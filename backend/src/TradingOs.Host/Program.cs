using TradingOs.Gateway;
using TradingOs.Host;

var builder = WebApplication.CreateBuilder(args);

// Dashboard origin for local dev; SignalR needs credentials-compatible CORS.
var dashboardOrigin = builder.Configuration["Cockpit:DashboardOrigin"] ?? "http://localhost:3000";
var observerUrl = builder.Configuration["Cockpit:ObserverUrl"] ?? "ws://localhost:8765";

builder.Services.AddSignalR();
builder.Services.AddCors(options =>
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(dashboardOrigin).AllowAnyHeader().AllowAnyMethod().AllowCredentials()));

builder.Services.AddSingleton<GatewayState>();
builder.Services.AddSingleton(sp => new Mt5ObserverClient(sp.GetRequiredService<GatewayState>(), observerUrl));
builder.Services.AddHostedService<GatewayBridgeService>();

var app = builder.Build();

app.UseCors();

// Minimal HTTP surface (backend_plan.md): health only in this slice.
app.MapGet("/health", () => Results.Ok(new { status = "ok", observer = observerUrl }));
app.MapHub<CockpitHub>("/hub/cockpit");

app.Run("http://localhost:5080");

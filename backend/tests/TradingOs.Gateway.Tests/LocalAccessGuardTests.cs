using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using TradingOs.Host;
using Verdict = TradingOs.Host.LocalAccessGuard.Verdict;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// I0 (2026-09-26): the hub and /api writes answer only the cockpit — the
/// right token AND an allowed Origin. Until then any web page, container or
/// local process could join the hub and call SubmitCommand.
/// </summary>
public class LocalAccessGuardTests
{
    private const string Token = "s3cret-token_value";
    private static readonly string[] Origins = ["http://localhost:3000", "http://127.0.0.1:3000"];

    private static Verdict Evaluate(
        string path,
        string method = "GET",
        string? origin = "http://localhost:3000",
        string? authorization = null,
        string? queryToken = Token,
        string? configured = Token) =>
        LocalAccessGuard.Evaluate(new PathString(path), method, origin, authorization, queryToken, configured, Origins);

    [Fact]
    public void The_hub_opens_with_the_token_and_an_allowed_origin()
    {
        Assert.Equal(Verdict.Allowed, Evaluate("/hub/cockpit"));
        Assert.Equal(Verdict.Allowed, Evaluate("/hub/cockpit", queryToken: null, authorization: $"Bearer {Token}"));
    }

    [Fact]
    public void A_foreign_web_page_is_refused_even_with_the_token()
    {
        // CORS does not apply to WebSockets: the Origin check is what stops a
        // page on another site from joining the hub.
        Assert.Equal(Verdict.OriginRefused, Evaluate("/hub/cockpit", origin: "https://evil.example"));
        Assert.Equal(Verdict.OriginRefused, Evaluate("/hub/cockpit", origin: "http://localhost:3000.evil.example"));
        Assert.Equal(Verdict.OriginRefused, Evaluate("/hub/cockpit", origin: "null"));
    }

    [Fact]
    public void A_client_without_origin_is_refused_on_the_hub()
    {
        // curl from a container sends no Origin; the cockpit always does.
        Assert.Equal(Verdict.OriginRefused, Evaluate("/hub/cockpit", origin: null));
    }

    [Fact]
    public void A_wrong_or_missing_token_is_refused()
    {
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit", queryToken: null));
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit", queryToken: "s3cret-token_valuE"));
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit", queryToken: Token + "x"));
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit", queryToken: null, authorization: Token));
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit", queryToken: null, authorization: "Basic " + Token));
    }

    [Fact]
    public void No_configured_token_refuses_everything_guarded()
    {
        Assert.Equal(Verdict.NoTokenConfigured, Evaluate("/hub/cockpit", configured: null));
        Assert.Equal(Verdict.NoTokenConfigured, Evaluate("/hub/cockpit", configured: ""));
        Assert.Equal(Verdict.NoTokenConfigured, Evaluate("/hub/cockpit", configured: "", queryToken: ""));
    }

    [Fact]
    public void Negotiate_and_every_path_under_the_hub_are_guarded()
    {
        Assert.Equal(Verdict.TokenRefused, Evaluate("/hub/cockpit/negotiate", method: "POST", queryToken: null));
        Assert.Equal(Verdict.OriginRefused, Evaluate("/HUB/cockpit", origin: null));
    }

    [Fact]
    public void Api_writes_are_guarded_and_reads_are_not()
    {
        Assert.Equal(Verdict.TokenRefused, Evaluate("/api/account-settings", method: "POST", queryToken: null));
        Assert.Equal(Verdict.OriginRefused, Evaluate("/api/account-settings/v1/cancel", method: "POST", origin: null));
        Assert.Equal(Verdict.Allowed, Evaluate("/api/account-settings", method: "POST", queryToken: null, authorization: $"Bearer {Token}"));

        Assert.Equal(Verdict.NotGuarded, Evaluate("/api/account-settings", origin: null, queryToken: null));
        Assert.Equal(Verdict.NotGuarded, Evaluate("/api/risk/today", method: "HEAD", origin: null, queryToken: null));
        Assert.Equal(Verdict.NotGuarded, Evaluate("/health", method: "POST", origin: null, queryToken: null));
        Assert.Equal(Verdict.NotGuarded, Evaluate("/apixyz", method: "POST", origin: null, queryToken: null));
    }

    [Fact]
    public async Task The_middleware_answers_403_and_never_reaches_the_hub()
    {
        var (status, reachedNext) = await RunAsync("/hub/cockpit", origin: "https://evil.example", query: $"?access_token={Token}");
        Assert.Equal(StatusCodes.Status403Forbidden, status);
        Assert.False(reachedNext);

        (status, reachedNext) = await RunAsync("/hub/cockpit", origin: "http://localhost:3000", query: "?access_token=wrong");
        Assert.Equal(StatusCodes.Status403Forbidden, status);
        Assert.False(reachedNext);
    }

    [Fact]
    public async Task The_middleware_lets_the_cockpit_and_plain_reads_through()
    {
        var (status, reachedNext) = await RunAsync("/hub/cockpit", origin: "http://127.0.0.1:3000", query: $"?id=abc&access_token={Token}");
        Assert.Equal(StatusCodes.Status200OK, status);
        Assert.True(reachedNext);

        (status, reachedNext) = await RunAsync("/api/journal/trades", origin: null, query: "?accountId=x");
        Assert.True(reachedNext);
        Assert.Equal(StatusCodes.Status200OK, status);
    }

    [Fact]
    public async Task A_refused_write_says_why_in_the_settings_page_shape()
    {
        var context = NewContext("/api/account-settings", "");
        context.Request.Method = "POST";
        context.Request.Headers.Origin = "http://localhost:3000";
        context.Request.Headers.Authorization = "Bearer wrong";
        await BuildPipeline(() => { })(context);

        Assert.Equal(StatusCodes.Status403Forbidden, context.Response.StatusCode);
        context.Response.Body.Position = 0;
        using var json = await System.Text.Json.JsonDocument.ParseAsync(context.Response.Body);
        Assert.Equal(
            LocalAccessGuard.RefusalMessage(Verdict.TokenRefused),
            json.RootElement.GetProperty("message").GetString());
        Assert.DoesNotContain(Token, LocalAccessGuard.RefusalMessage(Verdict.TokenRefused));
    }

    [Fact]
    public async Task Two_origin_headers_are_not_an_origin()
    {
        var context = NewContext("/hub/cockpit", $"?access_token={Token}");
        context.Request.Headers.Origin = new(["http://localhost:3000", "https://evil.example"]);
        var reached = false;
        await BuildPipeline(() => reached = true)(context);
        Assert.Equal(StatusCodes.Status403Forbidden, context.Response.StatusCode);
        Assert.False(reached);
    }

    private static async Task<(int Status, bool ReachedNext)> RunAsync(string path, string? origin, string query)
    {
        var context = NewContext(path, query);
        if (origin is not null)
        {
            context.Request.Headers.Origin = origin;
        }
        var reached = false;
        await BuildPipeline(() => reached = true)(context);
        return (context.Response.StatusCode, reached);
    }

    private static DefaultHttpContext NewContext(string path, string query)
    {
        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = path;
        context.Request.QueryString = new QueryString(query);
        context.Response.Body = new MemoryStream();
        return context;
    }

    private static RequestDelegate BuildPipeline(Action onNext)
    {
        var app = new ApplicationBuilder(new ServiceCollection().BuildServiceProvider());
        app.UseLocalAccessGuard(Token, Origins, NullLogger.Instance);
        app.Run(_ =>
        {
            onNext();
            return Task.CompletedTask;
        });
        return app.Build();
    }
}

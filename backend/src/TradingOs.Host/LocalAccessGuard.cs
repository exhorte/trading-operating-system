using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Primitives;

namespace TradingOs.Host;

/// <summary>
/// I0 (2026-09-26): what may drive the backend. Every request under
/// <c>/hub</c> — WebSocket upgrade included — and every write under
/// <c>/api</c> must carry the cockpit token and an allowed Origin.
///
/// Why both: CORS does not apply to WebSockets (Microsoft's SignalR
/// security docs), so until now any web page open in the trader's browser
/// could join the hub, read the stream and call SubmitCommand or publish
/// risk.lockout.cleared. The Origin check stops that — browsers always send
/// Origin on a WebSocket handshake and a page cannot forge it. The token
/// stops clients that can forge headers: other containers reach
/// 127.0.0.1-published ports through host.docker.internal, and local
/// processes reach them directly.
///
/// Limit, written down rather than hidden: the cockpit gets the token from
/// the Next server (app/api/cockpit-token), which checks Host and
/// Sec-Fetch-Site — a browser guard. A client that deliberately forges both
/// against Next can read the token, as can any process running as the
/// trader. The threat model is the network, browsers and generic container
/// traffic, not targeted malware on this machine (study, ADR 0013 plan).
///
/// No token configured = every guarded request is refused (fail closed).
/// Reads under /api and /health stay open: the MCP server, the weekly review
/// and start-live read them without a browser.
/// </summary>
public static class LocalAccessGuard
{
    public enum Verdict
    {
        /// <summary>Not a guarded request (reads, health, preflight).</summary>
        NotGuarded,
        Allowed,
        NoTokenConfigured,
        OriginRefused,
        TokenRefused,
    }

    /// <summary>
    /// Pure decision, testable without a server. <paramref name="queryToken"/>
    /// is SignalR's <c>access_token</c>: browsers cannot set headers on a
    /// WebSocket handshake, so the JS client puts the token in the query.
    /// </summary>
    public static Verdict Evaluate(
        PathString path,
        string method,
        string? origin,
        string? authorization,
        string? queryToken,
        string? configuredToken,
        IReadOnlyCollection<string> allowedOrigins)
    {
        if (!IsGuarded(path, method))
        {
            return Verdict.NotGuarded;
        }
        if (string.IsNullOrEmpty(configuredToken))
        {
            return Verdict.NoTokenConfigured;
        }
        if (origin is null || !allowedOrigins.Contains(origin, StringComparer.Ordinal))
        {
            return Verdict.OriginRefused;
        }
        var presented = BearerToken(authorization) ?? queryToken;
        return presented is not null && FixedTimeEquals(presented, configuredToken)
            ? Verdict.Allowed
            : Verdict.TokenRefused;
    }

    private static bool IsGuarded(PathString path, string method)
    {
        if (path.StartsWithSegments("/hub"))
        {
            return true;
        }
        // Writes only. OPTIONS never reaches here with a preflight (UseCors
        // answers it first); HEAD/GET are reads.
        return path.StartsWithSegments("/api")
            && !HttpMethods.IsGet(method)
            && !HttpMethods.IsHead(method)
            && !HttpMethods.IsOptions(method);
    }

    private static string? BearerToken(string? authorization)
    {
        const string prefix = "Bearer ";
        return authorization is not null && authorization.StartsWith(prefix, StringComparison.Ordinal)
            ? authorization[prefix.Length..].Trim()
            : null;
    }

    private static bool FixedTimeEquals(string presented, string expected) =>
        CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(presented),
            Encoding.UTF8.GetBytes(expected));

    /// <summary>
    /// Registers the guard. Refusals answer 403 with a short reason and log
    /// one line without the query string — the token travels in it.
    /// </summary>
    public static IApplicationBuilder UseLocalAccessGuard(
        this IApplicationBuilder app,
        string? configuredToken,
        IReadOnlyCollection<string> allowedOrigins,
        ILogger logger)
    {
        return app.Use(async (context, next) =>
        {
            var request = context.Request;
            var verdict = Evaluate(
                request.Path,
                request.Method,
                Single(request.Headers.Origin),
                Single(request.Headers.Authorization),
                Single(request.Query["access_token"]),
                configuredToken,
                allowedOrigins);

            if (verdict is Verdict.NotGuarded or Verdict.Allowed)
            {
                await next(context);
                return;
            }

            logger.LogWarning(
                "Refused {Method} {Path}: {Verdict}",
                request.Method,
                request.Path.Value,
                verdict);
            // Same { message } shape as the Settings endpoints: the page shows
            // it as is (lib/accounts/settings-api.ts).
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            await context.Response.WriteAsJsonAsync(new { message = RefusalMessage(verdict) });
        });
    }

    public static string RefusalMessage(Verdict verdict) => verdict switch
    {
        Verdict.NoTokenConfigured =>
            "Le backend n'a pas de jeton du cockpit : lance scripts/start-live.ps1 (il écrit TRADINGOS_COCKPIT_TOKEN dans .env), puis recrée le conteneur.",
        Verdict.OriginRefused => "Origine refusée : seul le cockpit local peut écrire ou rejoindre le hub.",
        _ => "Jeton du cockpit refusé : .env et le conteneur backend n'ont pas le même TRADINGOS_COCKPIT_TOKEN — recrée le conteneur.",
    };

    private static string? Single(StringValues values) => values.Count == 1 ? values[0] : null;
}

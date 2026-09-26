using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using TradingOs.Host;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// I0 (2026-09-26): SignalR's browser client puts the cockpit token in the
/// WebSocket URL, and ASP.NET Core logs request URLs at Information. The
/// console — what `docker logs` shows — must never carry it.
/// </summary>
public class RedactingConsoleFormatterTests
{
    private const string Token = "Zk3-q_9sT0kEnValue";

    [Fact]
    public void The_request_line_of_a_hub_connection_loses_its_token()
    {
        var line = $"Request starting HTTP/1.1 GET http://localhost:5080/hub/cockpit?id=abc&access_token={Token} - - -";
        var redacted = RedactingConsoleFormatter.Redact(line);
        Assert.DoesNotContain(Token, redacted);
        Assert.Contains("access_token=***", redacted);
        Assert.Contains("id=abc", redacted);
    }

    [Fact]
    public void A_bearer_header_loses_its_token()
    {
        var redacted = RedactingConsoleFormatter.Redact($"Authorization: Bearer {Token}");
        Assert.DoesNotContain(Token, redacted);
        Assert.Equal("Authorization: Bearer ***", redacted);
    }

    [Fact]
    public void Text_without_a_secret_is_unchanged()
    {
        const string text = "MT5 execution agent connected";
        Assert.Equal(text, RedactingConsoleFormatter.Redact(text));
    }

    [Fact]
    public void Written_lines_are_redacted_messages_and_exceptions_alike()
    {
        var formatter = new RedactingConsoleFormatter();
        using var writer = new StringWriter();
        var exception = new InvalidOperationException($"failed on /hub/cockpit?access_token={Token}");
        var entry = new LogEntry<string>(
            LogLevel.Information,
            "Microsoft.AspNetCore.Hosting.Diagnostics",
            new EventId(1),
            $"GET /hub/cockpit?access_token={Token}",
            exception,
            (state, _) => state);

        formatter.Write(in entry, null, writer);

        var output = writer.ToString();
        Assert.DoesNotContain(Token, output);
        Assert.StartsWith("info: Microsoft.AspNetCore.Hosting.Diagnostics[1]", output);
        Assert.Contains("access_token=***", output);
    }
}

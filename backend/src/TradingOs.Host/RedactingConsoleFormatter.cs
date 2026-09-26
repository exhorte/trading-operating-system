using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Logging.Console;

namespace TradingOs.Host;

/// <summary>
/// I0 (2026-09-26): the console log — what <c>docker logs tradingos-backend</c>
/// shows — never carries a secret. SignalR's browser client sends the cockpit
/// token as <c>access_token</c> in the WebSocket URL, and ASP.NET Core logs
/// request URLs at Information; appsettings keeps <c>Microsoft.AspNetCore</c>
/// at Warning today, so nothing leaks now — this formatter holds even if
/// someone lowers that level to debug something. Same line shape as the
/// default "simple" formatter, without colors or scopes.
/// </summary>
public sealed partial class RedactingConsoleFormatter() : ConsoleFormatter(FormatterName)
{
    public const string FormatterName = "tradingos-redacting";

    [GeneratedRegex(@"(access_token=)[^&\s""']+", RegexOptions.IgnoreCase)]
    private static partial Regex QueryToken();

    [GeneratedRegex(@"(Bearer\s+)[A-Za-z0-9\-_\.~\+/=]+", RegexOptions.IgnoreCase)]
    private static partial Regex BearerToken();

    public static string Redact(string text) =>
        BearerToken().Replace(QueryToken().Replace(text, "$1***"), "$1***");

    public override void Write<TState>(
        in LogEntry<TState> logEntry,
        IExternalScopeProvider? scopeProvider,
        TextWriter textWriter)
    {
        var message = logEntry.Formatter?.Invoke(logEntry.State, logEntry.Exception);
        if (message is null && logEntry.Exception is null)
        {
            return;
        }

        textWriter.Write(Label(logEntry.LogLevel));
        textWriter.Write(": ");
        textWriter.Write(logEntry.Category);
        textWriter.Write('[');
        textWriter.Write(logEntry.EventId.Id);
        textWriter.WriteLine(']');
        if (!string.IsNullOrEmpty(message))
        {
            textWriter.Write("      ");
            textWriter.WriteLine(Redact(message));
        }
        if (logEntry.Exception is not null)
        {
            textWriter.Write("      ");
            textWriter.WriteLine(Redact(logEntry.Exception.ToString()));
        }
    }

    private static string Label(LogLevel level) => level switch
    {
        LogLevel.Trace => "trce",
        LogLevel.Debug => "dbug",
        LogLevel.Information => "info",
        LogLevel.Warning => "warn",
        LogLevel.Error => "fail",
        LogLevel.Critical => "crit",
        _ => "none",
    };
}

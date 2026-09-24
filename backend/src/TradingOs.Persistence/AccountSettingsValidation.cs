using System.Text.Json;

namespace TradingOs.Persistence;

/// <summary>
/// T12 incrément 2 — the shape a settings change must have before it enters
/// the ledger. Mirrors lib/accounts/settings.ts (validateFtmoSettings,
/// validateExnessSettings): the page checks for the trader's comfort, this
/// checks because the ledger must never hold a value the risk engine cannot
/// use. Returns the settings rewritten with only the known fields, so nothing
/// unvalidated rides along into jsonb.
///
/// Deliberately limited to what the Settings screen edits: which FTMO
/// challenge is traded, the Exness reference capital, and the text that
/// recognises each broker. The percentages themselves (FTMO's rules, the
/// trader's discipline limits) stay in lib/accounts/, changed by a commit.
/// </summary>
public static class AccountSettingsValidation
{
    public const string Ftmo = "ftmo";
    public const string Exness = "exness";

    private static readonly string[] ChallengeTypes = ["1-step", "2-step"];
    private static readonly string[] Phases = ["challenge", "verification", "funded"];

    /// <summary>Bounds wide enough for every FTMO size and currency, narrow
    /// enough to refuse a typo that would silently disable a loss gate.</summary>
    public const double MinAccountSize = 1_000;
    public const double MaxAccountSize = 10_000_000;
    public const double MinReferenceBalance = 1;
    public const double MaxReferenceBalance = 100_000_000;
    public const int MinBrokerMatchLength = 2;
    public const int MaxBrokerMatchLength = 64;

    public static (string? NormalizedJson, string? Error) Validate(string? firm, JsonElement settings)
    {
        if (settings.ValueKind != JsonValueKind.Object)
        {
            return (null, "settings must be a JSON object");
        }
        return firm switch
        {
            Ftmo => ValidateFtmo(settings),
            Exness => ValidateExness(settings),
            _ => (null, $"unknown firm '{firm}' — expected '{Ftmo}' or '{Exness}'"),
        };
    }

    private static (string?, string?) ValidateFtmo(JsonElement settings)
    {
        if (!settings.TryGetProperty("challenge", out var challenge) || challenge.ValueKind != JsonValueKind.Object)
        {
            return (null, "challenge is required");
        }
        var type = ReadString(challenge, "type");
        if (type is null || !ChallengeTypes.Contains(type))
        {
            return (null, "challenge.type must be '1-step' or '2-step'");
        }
        var phase = ReadString(challenge, "phase");
        if (phase is null || !Phases.Contains(phase))
        {
            return (null, "challenge.phase must be 'challenge', 'verification' or 'funded'");
        }
        if (!TryReadNumber(challenge, "accountSize", out var accountSize) ||
            accountSize < MinAccountSize || accountSize > MaxAccountSize)
        {
            return (null, $"challenge.accountSize must be a number between {MinAccountSize} and {MaxAccountSize}");
        }
        var (brokerMatch, matchError) = ReadBrokerMatch(settings);
        if (matchError is not null)
        {
            return (null, matchError);
        }

        return (JsonSerializer.Serialize(new
        {
            challenge = new { type, accountSize, phase },
            brokerMatch,
        }), null);
    }

    private static (string?, string?) ValidateExness(JsonElement settings)
    {
        if (!settings.TryGetProperty("referenceBalance", out var reference))
        {
            return (null, "referenceBalance is required (null to leave it unset)");
        }
        double? referenceBalance = null;
        if (reference.ValueKind != JsonValueKind.Null)
        {
            if (reference.ValueKind != JsonValueKind.Number ||
                !reference.TryGetDouble(out var value) ||
                value < MinReferenceBalance || value > MaxReferenceBalance)
            {
                return (null, $"referenceBalance must be null or a number between {MinReferenceBalance} and {MaxReferenceBalance}");
            }
            referenceBalance = value;
        }
        var (brokerMatch, matchError) = ReadBrokerMatch(settings);
        if (matchError is not null)
        {
            return (null, matchError);
        }

        return (JsonSerializer.Serialize(new { referenceBalance, brokerMatch }), null);
    }

    /// <summary>The text searched, case-insensitively, in the broker name MT5
    /// reports (lib/accounts/firm.ts). Two characters minimum: a single
    /// letter would recognise almost any broker as this firm.</summary>
    private static (string?, string?) ReadBrokerMatch(JsonElement settings)
    {
        var raw = ReadString(settings, "brokerMatch")?.Trim();
        if (raw is null || raw.Length < MinBrokerMatchLength || raw.Length > MaxBrokerMatchLength)
        {
            return (null, $"brokerMatch must be {MinBrokerMatchLength} to {MaxBrokerMatchLength} characters");
        }
        return (raw, null);
    }

    private static string? ReadString(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;

    private static bool TryReadNumber(JsonElement obj, string name, out double value)
    {
        value = 0;
        return obj.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out value);
    }
}

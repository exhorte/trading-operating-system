using System.Text.Json;

namespace TradingOs.Contracts;

/// <summary>
/// T12 incrément 2 — one entry of the account settings ledger as the cockpit
/// reads it (GET /api/account-settings). Mirror of
/// lib/accounts/settings.ts::SettingsVersion (ADR 0004).
/// `Settings` and `DeferralReasons` stay raw JSON here: their shape is
/// validated on the way in (AccountSettingsValidation) and interpreted by the
/// cockpit, which owns the resolution of which version is in effect.
/// </summary>
public sealed record AccountSettingsVersionDto(
    string VersionId,
    string Firm,
    JsonElement Settings,
    string RequestedAt,
    bool Deferred,
    JsonElement DeferralReasons,
    string? CancelledAt,
    bool DayStartedSince);

/// <summary>Body of POST /api/account-settings.</summary>
public sealed record AccountSettingsRequest(string? Firm, JsonElement Settings);

/// <summary>
/// accounts.settings.changed — backend-originated (the HTTP endpoint that
/// wrote the ledger), broadcast so every open cockpit re-reads its settings,
/// and persisted in `envelopes` so the audit trail carries the change itself,
/// not just its id. Action: "requested" | "cancelled".
/// </summary>
public sealed record AccountSettingsChangedPayload(
    string VersionId,
    string Firm,
    string Action,
    bool Deferred,
    JsonElement Settings,
    JsonElement DeferralReasons);

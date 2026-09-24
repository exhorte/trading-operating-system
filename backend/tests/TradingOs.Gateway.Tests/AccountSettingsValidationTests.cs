using System.Text.Json;
using TradingOs.Persistence;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// T12 incrément 2 — nothing the risk engine cannot use may enter the
/// account settings ledger, and nothing unvalidated rides along.
/// </summary>
public class AccountSettingsValidationTests
{
    private static JsonElement Json(string json) => JsonDocument.Parse(json).RootElement.Clone();

    private const string ValidFtmo =
        """{"challenge":{"type":"2-step","accountSize":10000,"phase":"challenge"},"brokerMatch":"ftmo"}""";

    [Fact]
    public void Accepts_the_configured_ftmo_challenge_and_keeps_only_known_fields()
    {
        var withExtra = Json(
            """{"challenge":{"type":"2-step","accountSize":10000,"phase":"challenge","secret":"x"},"brokerMatch":"  FTMO  ","password":"nope"}""");

        var (normalized, error) = AccountSettingsValidation.Validate("ftmo", withExtra);

        Assert.Null(error);
        Assert.Equal(ValidFtmo.Replace("\"ftmo\"", "\"FTMO\""), normalized);
    }

    [Theory]
    [InlineData("""{"challenge":{"type":"3-step","accountSize":10000,"phase":"challenge"},"brokerMatch":"ftmo"}""", "challenge.type")]
    [InlineData("""{"challenge":{"type":"2-step","accountSize":10000,"phase":"live"},"brokerMatch":"ftmo"}""", "challenge.phase")]
    [InlineData("""{"challenge":{"type":"2-step","accountSize":0,"phase":"challenge"},"brokerMatch":"ftmo"}""", "challenge.accountSize")]
    [InlineData("""{"challenge":{"type":"2-step","accountSize":"10000","phase":"challenge"},"brokerMatch":"ftmo"}""", "challenge.accountSize")]
    [InlineData("""{"challenge":{"type":"2-step","accountSize":10000,"phase":"challenge"},"brokerMatch":"f"}""", "brokerMatch")]
    [InlineData("""{"brokerMatch":"ftmo"}""", "challenge")]
    public void Refuses_an_ftmo_challenge_the_risk_engine_could_not_use(string json, string field)
    {
        var (normalized, error) = AccountSettingsValidation.Validate("ftmo", Json(json));

        Assert.Null(normalized);
        Assert.NotNull(error);
        Assert.Contains(field, error);
    }

    [Fact]
    public void Accepts_an_exness_reference_or_its_explicit_absence()
    {
        Assert.Equal(
            """{"referenceBalance":2500,"brokerMatch":"exness"}""",
            AccountSettingsValidation.Validate("exness", Json("""{"referenceBalance":2500,"brokerMatch":"exness"}""")).NormalizedJson);
        Assert.Equal(
            """{"referenceBalance":null,"brokerMatch":"exness"}""",
            AccountSettingsValidation.Validate("exness", Json("""{"referenceBalance":null,"brokerMatch":"exness"}""")).NormalizedJson);
    }

    [Theory]
    [InlineData("""{"referenceBalance":-5,"brokerMatch":"exness"}""", "referenceBalance")]
    [InlineData("""{"referenceBalance":"2500","brokerMatch":"exness"}""", "referenceBalance")]
    [InlineData("""{"brokerMatch":"exness"}""", "referenceBalance")]
    [InlineData("""{"referenceBalance":2500}""", "brokerMatch")]
    public void Refuses_an_exness_reference_the_risk_engine_could_not_use(string json, string field)
    {
        var (normalized, error) = AccountSettingsValidation.Validate("exness", Json(json));

        Assert.Null(normalized);
        Assert.Contains(field, error);
    }

    [Theory]
    [InlineData("icmarkets")]
    [InlineData("")]
    [InlineData(null)]
    public void Refuses_a_firm_it_has_no_profile_for(string? firm)
    {
        var (normalized, error) = AccountSettingsValidation.Validate(firm, Json(ValidFtmo));

        Assert.Null(normalized);
        Assert.Contains("unknown firm", error);
    }

    [Fact]
    public void Refuses_settings_that_are_not_an_object()
    {
        Assert.Contains("JSON object", AccountSettingsValidation.Validate("ftmo", Json("[]")).Error);
        Assert.Contains("JSON object", AccountSettingsValidation.Validate("ftmo", default).Error);
    }
}

using Azure.Core;
using Azure.Identity;
using Microsoft.Extensions.Logging;

namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Factory that produces the <see cref="TokenCredential"/> used to authenticate
/// against the Service Bus namespace in the remote Entra tenant (Tenant B).
/// </summary>
public interface ICrossTenantCredentialFactory
{
    /// <summary>
    /// Builds a <see cref="TokenCredential"/> that performs the cross-tenant
    /// token-exchange required to access Service Bus in Tenant B.
    /// </summary>
    TokenCredential CreateServiceBusCredential();

    /// <summary>
    /// Builds a <see cref="TokenCredential"/> for same-tenant Blob Storage
    /// access in Tenant A using the UAMI.
    /// </summary>
    TokenCredential CreateStorageCredential();
}

/// <summary>
/// Default implementation of <see cref="ICrossTenantCredentialFactory"/>.
///
/// Cross-tenant authentication flow
/// ──────────────────────────────────
///   1.  A <see cref="ManagedIdentityCredential"/> (scoped to the UAMI in
///       Tenant A) calls the Instance Metadata Service to obtain a short-lived
///       federated token with audience <c>api://AzureADTokenExchange</c>.
///   2.  That federated token is presented as a <em>client assertion</em> to
///       the Tenant B token endpoint via <see cref="ClientAssertionCredential"/>.
///   3.  Tenant B exchanges the assertion for a Tenant B access token scoped to
///       Service Bus (<c>https://servicebus.azure.net/.default</c>).
///
/// Storage credential flow
/// ───────────────────────
///   A <see cref="ManagedIdentityCredential"/> scoped to the UAMI is used
///   directly — no tenant exchange is needed because storage lives in Tenant A.
/// </summary>
internal sealed class CrossTenantCredentialFactory : ICrossTenantCredentialFactory
{
    private readonly IEnvironmentConfiguration _config;
    private readonly ILogger<CrossTenantCredentialFactory> _logger;

    public CrossTenantCredentialFactory(
        IEnvironmentConfiguration config,
        ILogger<CrossTenantCredentialFactory> logger)
    {
        _config = config;
        _logger = logger;
    }

    /// <inheritdoc />
    public TokenCredential CreateServiceBusCredential()
    {
        var tenantId = _config.Require(SettingNames.CrossTenantTenantId);
        var clientId = _config.Require(SettingNames.CrossTenantAppClientId);
        var uamiClientId = _config.Require(SettingNames.UserAssignedMiClientId);

        var uamiCredential = new ManagedIdentityCredential(
            ManagedIdentityId.FromUserAssignedClientId(uamiClientId));

        return new ClientAssertionCredential(
            tenantId,
            clientId,
            async cancellationToken =>
            {
                try
                {
                    var tokenResponse = await uamiCredential.GetTokenAsync(
                        new TokenRequestContext(["api://AzureADTokenExchange"]),
                        cancellationToken);

                    LogTokenClaims(tokenResponse.Token, "UAMI federated assertion");
                    return tokenResponse.Token;
                }
                catch (Exception ex)
                {
                    throw new InvalidOperationException(
                        $"Failed to obtain federated assertion token from IMDS for " +
                        $"cross-tenant Service Bus authentication. Verify that UAMI " +
                        $"'{uamiClientId}' is correctly assigned and IMDS is reachable.",
                        ex);
                }
            });
    }

    /// <inheritdoc />
    public TokenCredential CreateStorageCredential()
    {
        var uamiClientId = _config.Require(SettingNames.UserAssignedMiClientId);
        return new ManagedIdentityCredential(
            ManagedIdentityId.FromUserAssignedClientId(uamiClientId));
    }

    /// <summary>
    /// Decodes a JWT and logs the key claims for diagnostic purposes.
    /// The raw token value is never logged.
    /// </summary>
    private void LogTokenClaims(string token, string label)
    {
        try
        {
            var parts = token.Split('.');
            if (parts.Length < 2)
            {
                _logger.LogWarning("{Label} token does not look like a JWT (no '.' separators).", label);
                return;
            }

            var payload = parts[1];
            // Restore base64url padding
            payload = payload.PadRight(payload.Length + (4 - payload.Length % 4) % 4, '=');

            var json = System.Text.Encoding.UTF8.GetString(
                Convert.FromBase64String(payload.Replace('-', '+').Replace('_', '/')));

            using var doc = System.Text.Json.JsonDocument.Parse(json);
            var root = doc.RootElement;

            string Get(string claim) =>
                root.TryGetProperty(claim, out var v) ? v.ToString() : "n/a";

            string GetTs(string claim)
            {
                if (!root.TryGetProperty(claim, out var v)) return "n/a";
                if (v.TryGetInt64(out var epoch))
                    return DateTimeOffset.FromUnixTimeSeconds(epoch).UtcDateTime.ToString("O");
                return "n/a";
            }

            _logger.LogInformation(
                "{Label} token claims — iss: {Iss} | aud: {Aud} | sub: {Sub} | " +
                "oid: {Oid} | tid: {Tid} | appid: {AppId} | " +
                "iat: {Iat} | nbf: {Nbf} | exp: {Exp}",
                label,
                Get("iss"), Get("aud"), Get("sub"),
                Get("oid"), Get("tid"),
                root.TryGetProperty("appid", out _) ? Get("appid") : Get("azp"),
                GetTs("iat"), GetTs("nbf"), GetTs("exp"));
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to decode {Label} token claims for diagnostics.", label);
        }
    }
}

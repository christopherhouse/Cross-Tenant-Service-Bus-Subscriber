using Microsoft.Extensions.Configuration;

namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Provides access to required and optional environment / application settings.
/// </summary>
public interface IEnvironmentConfiguration
{
    /// <summary>
    /// Returns the value of a required environment variable, or throws if it is
    /// missing or empty.
    /// </summary>
    /// <param name="name">The variable name.</param>
    /// <returns>The non-empty value.</returns>
    /// <exception cref="InvalidOperationException">
    /// Thrown when the variable is not set or is empty.
    /// </exception>
    string Require(string name);

    /// <summary>
    /// Returns the value of an optional environment variable, falling back to
    /// <paramref name="defaultValue"/> when the variable is absent or empty.
    /// </summary>
    string Optional(string name, string defaultValue);
}

/// <summary>
/// Default implementation that reads values from <see cref="IConfiguration"/>
/// (which includes environment variables in Azure Functions).
/// </summary>
internal sealed class EnvironmentConfiguration : IEnvironmentConfiguration
{
    private readonly IConfiguration _configuration;

    public EnvironmentConfiguration(IConfiguration configuration)
    {
        _configuration = configuration;
    }

    /// <inheritdoc />
    public string Require(string name)
    {
        var value = _configuration[name];
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new InvalidOperationException(
                $"Required configuration setting '{name}' is not set.");
        }

        return value;
    }

    /// <inheritdoc />
    public string Optional(string name, string defaultValue)
    {
        var value = _configuration[name];
        return string.IsNullOrWhiteSpace(value) ? defaultValue : value;
    }
}

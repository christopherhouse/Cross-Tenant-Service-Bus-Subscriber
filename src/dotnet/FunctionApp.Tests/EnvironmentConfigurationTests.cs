using CrossTenantServiceBus.FunctionApp;
using Microsoft.Extensions.Configuration;

namespace CrossTenantServiceBus.FunctionApp.Tests;

/// <summary>
/// Unit tests for <see cref="EnvironmentConfiguration"/>.
/// </summary>
public class EnvironmentConfigurationTests
{
    private static IEnvironmentConfiguration BuildConfig(Dictionary<string, string?> values)
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(values)
            .Build();
        return new EnvironmentConfiguration(config);
    }

    [Fact]
    public void Require_ReturnsValue_WhenVariableIsSet()
    {
        var sut = BuildConfig(new() { ["MY_VAR"] = "hello" });

        var result = sut.Require("MY_VAR");

        Assert.Equal("hello", result);
    }

    [Fact]
    public void Require_ThrowsInvalidOperationException_WhenVariableIsMissing()
    {
        var sut = BuildConfig(new());

        var ex = Assert.Throws<InvalidOperationException>(() => sut.Require("MISSING_VAR"));

        Assert.Contains("MISSING_VAR", ex.Message);
    }

    [Fact]
    public void Require_ThrowsInvalidOperationException_WhenVariableIsEmpty()
    {
        var sut = BuildConfig(new() { ["EMPTY_VAR"] = "" });

        Assert.Throws<InvalidOperationException>(() => sut.Require("EMPTY_VAR"));
    }

    [Fact]
    public void Require_ThrowsInvalidOperationException_WhenVariableIsWhitespace()
    {
        var sut = BuildConfig(new() { ["WS_VAR"] = "   " });

        Assert.Throws<InvalidOperationException>(() => sut.Require("WS_VAR"));
    }

    [Fact]
    public void Optional_ReturnsValue_WhenVariableIsSet()
    {
        var sut = BuildConfig(new() { ["OPT_VAR"] = "custom" });

        var result = sut.Optional("OPT_VAR", "default");

        Assert.Equal("custom", result);
    }

    [Fact]
    public void Optional_ReturnsDefault_WhenVariableIsMissing()
    {
        var sut = BuildConfig(new());

        var result = sut.Optional("OPT_VAR", "default");

        Assert.Equal("default", result);
    }

    [Fact]
    public void Optional_ReturnsDefault_WhenVariableIsEmpty()
    {
        var sut = BuildConfig(new() { ["OPT_VAR"] = "" });

        var result = sut.Optional("OPT_VAR", "default");

        Assert.Equal("default", result);
    }
}

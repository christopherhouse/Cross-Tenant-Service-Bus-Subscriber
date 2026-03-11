using Azure.Core;
using Azure.Identity;
using CrossTenantServiceBus.FunctionApp;
using Microsoft.Extensions.Logging;
using Moq;

namespace CrossTenantServiceBus.FunctionApp.Tests;

/// <summary>
/// Unit tests for <see cref="CrossTenantCredentialFactory"/>.
/// </summary>
public class CrossTenantCredentialFactoryTests
{
    private static CrossTenantCredentialFactory BuildSut(
        IEnvironmentConfiguration config)
    {
        var logger = Mock.Of<ILogger<CrossTenantCredentialFactory>>();
        return new CrossTenantCredentialFactory(config, logger);
    }

    private static IEnvironmentConfiguration BuildConfig(
        string tenantId = "tenant-b-id",
        string clientId = "app-client-id",
        string uamiClientId = "uami-client-id")
    {
        var mock = new Mock<IEnvironmentConfiguration>();
        mock.Setup(c => c.Require(SettingNames.CrossTenantTenantId)).Returns(tenantId);
        mock.Setup(c => c.Require(SettingNames.CrossTenantAppClientId)).Returns(clientId);
        mock.Setup(c => c.Require(SettingNames.UserAssignedMiClientId)).Returns(uamiClientId);
        return mock.Object;
    }

    [Fact]
    public void CreateServiceBusCredential_ReturnsClientAssertionCredential()
    {
        var sut = BuildSut(BuildConfig());

        var credential = sut.CreateServiceBusCredential();

        Assert.IsType<ClientAssertionCredential>(credential);
    }

    [Fact]
    public void CreateServiceBusCredential_ReadsRequiredConfigValues()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock.Setup(c => c.Require(SettingNames.CrossTenantTenantId)).Returns("t-id");
        configMock.Setup(c => c.Require(SettingNames.CrossTenantAppClientId)).Returns("c-id");
        configMock.Setup(c => c.Require(SettingNames.UserAssignedMiClientId)).Returns("u-id");

        var sut = BuildSut(configMock.Object);
        sut.CreateServiceBusCredential();

        configMock.Verify(c => c.Require(SettingNames.CrossTenantTenantId), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.CrossTenantAppClientId), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.UserAssignedMiClientId), Times.Once);
    }

    [Fact]
    public void CreateStorageCredential_ReturnsManagedIdentityCredential()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock.Setup(c => c.Require(SettingNames.UserAssignedMiClientId)).Returns("uami-id");

        var sut = BuildSut(configMock.Object);

        var credential = sut.CreateStorageCredential();

        Assert.IsType<ManagedIdentityCredential>(credential);
    }

    [Fact]
    public void CreateStorageCredential_ReadsUamiClientIdFromConfig()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock.Setup(c => c.Require(SettingNames.UserAssignedMiClientId)).Returns("uami-id");

        var sut = BuildSut(configMock.Object);
        sut.CreateStorageCredential();

        configMock.Verify(c => c.Require(SettingNames.UserAssignedMiClientId), Times.Once);
    }

    [Fact]
    public void CreateServiceBusCredential_ThrowsWhenTenantIdMissing()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock
            .Setup(c => c.Require(SettingNames.CrossTenantTenantId))
            .Throws(new InvalidOperationException("Required setting 'CROSS_TENANT_TENANT_ID' is not set."));

        var sut = BuildSut(configMock.Object);

        Assert.Throws<InvalidOperationException>(() => sut.CreateServiceBusCredential());
    }
}

using Azure.Core;
using Azure.Messaging.ServiceBus;
using Azure.Storage.Blobs;
using CrossTenantServiceBus.FunctionApp;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Extensions.Logging;
using Moq;

namespace CrossTenantServiceBus.FunctionApp.Tests;

/// <summary>
/// Unit tests for <see cref="ServiceBusSubscriberFunction"/>.
/// </summary>
public class ServiceBusSubscriberFunctionTests
{
    // ── Helpers ───────────────────────────────────────────────────────────────

    private static IEnvironmentConfiguration BuildBaseConfig(
        Dictionary<string, string>? overrides = null)
    {
        var values = new Dictionary<string, string>
        {
            [SettingNames.CrossTenantServiceBusNamespace] = "test-ns.servicebus.windows.net",
            [SettingNames.CrossTenantTopicName] = "test-topic",
            [SettingNames.CrossTenantSubscriptionName] = "test-sub",
            [SettingNames.StorageAccountName] = "teststorage",
            [SettingNames.StorageContainerName] = "sb-messages",
        };

        if (overrides is not null)
        {
            foreach (var kvp in overrides)
                values[kvp.Key] = kvp.Value;
        }

        var mock = new Mock<IEnvironmentConfiguration>();
        foreach (var kvp in values)
            mock.Setup(c => c.Require(kvp.Key)).Returns(kvp.Value);

        mock.Setup(c => c.Optional(SettingNames.SbMaxMessageCount, It.IsAny<string>()))
            .Returns("10");
        mock.Setup(c => c.Optional(SettingNames.SbMaxWaitTimeSeconds, It.IsAny<string>()))
            .Returns("1");

        return mock.Object;
    }

    private static ServiceBusReceivedMessage MakeMessage(
        string messageId = "msg-001",
        string body = """{"event":"test"}""")
    {
        return ServiceBusModelFactory.ServiceBusReceivedMessage(
            body: BinaryData.FromString(body),
            messageId: messageId);
    }

    private static TimerInfo MakeTimer(bool isPastDue = false)
    {
        return new TimerInfo
        {
            IsPastDue = isPastDue,
            ScheduleStatus = new ScheduleStatus
            {
                Last = DateTime.UtcNow.AddMinutes(-1),
                Next = DateTime.UtcNow.AddMinutes(1),
            },
        };
    }

    private static ServiceBusSubscriberFunction BuildSut(
        IEnvironmentConfiguration? config = null,
        ICrossTenantCredentialFactory? credentialFactory = null,
        IBlobMessageWriter? blobWriter = null,
        IServiceBusClientFactory? sbFactory = null,
        IBlobServiceClientFactory? blobFactory = null,
        ILogger<ServiceBusSubscriberFunction>? logger = null)
    {
        return new ServiceBusSubscriberFunction(
            config ?? BuildBaseConfig(),
            credentialFactory ?? Mock.Of<ICrossTenantCredentialFactory>(),
            blobWriter ?? Mock.Of<IBlobMessageWriter>(),
            sbFactory ?? Mock.Of<IServiceBusClientFactory>(),
            blobFactory ?? Mock.Of<IBlobServiceClientFactory>(),
            logger ?? Mock.Of<ILogger<ServiceBusSubscriberFunction>>());
    }

    // ── Tests ─────────────────────────────────────────────────────────────────

    [Fact]
    public async Task RunAsync_CallsRequireForAllRequiredSettings()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock.Setup(c => c.Require(It.IsAny<string>())).Returns("test-value");
        configMock.Setup(c => c.Optional(It.IsAny<string>(), It.IsAny<string>())).Returns("5");

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage>());

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var sut = BuildSut(
            config: configMock.Object,
            credentialFactory: credMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        await sut.RunAsync(MakeTimer(), CancellationToken.None);

        configMock.Verify(c => c.Require(SettingNames.CrossTenantServiceBusNamespace), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.CrossTenantTopicName), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.CrossTenantSubscriptionName), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.StorageAccountName), Times.Once);
        configMock.Verify(c => c.Require(SettingNames.StorageContainerName), Times.Once);
    }

    [Fact]
    public async Task RunAsync_WritesMessageAndCompletesOnSuccess()
    {
        var message = MakeMessage("msg-001");
        var blobWriterMock = new Mock<IBlobMessageWriter>();
        blobWriterMock
            .Setup(w => w.WriteMessageAsync(
                It.IsAny<BlobServiceClient>(),
                It.IsAny<string>(),
                It.IsAny<ServiceBusReceivedMessage>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync("2024/01/15/msg-001.json");

        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage> { message });
        receiverMock
            .Setup(r => r.CompleteMessageAsync(message, It.IsAny<CancellationToken>()))
            .Returns(Task.CompletedTask);

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var sut = BuildSut(
            credentialFactory: credMock.Object,
            blobWriter: blobWriterMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        await sut.RunAsync(MakeTimer(), CancellationToken.None);

        blobWriterMock.Verify(w => w.WriteMessageAsync(
            It.IsAny<BlobServiceClient>(),
            It.IsAny<string>(),
            message,
            It.IsAny<CancellationToken>()), Times.Once);

        receiverMock.Verify(r => r.CompleteMessageAsync(message, It.IsAny<CancellationToken>()), Times.Once);
        receiverMock.Verify(r => r.AbandonMessageAsync(message, It.IsAny<IDictionary<string, object>>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task RunAsync_AbandonsMessageWhenBlobWriteFails()
    {
        var message = MakeMessage("msg-001");

        var blobWriterMock = new Mock<IBlobMessageWriter>();
        blobWriterMock
            .Setup(w => w.WriteMessageAsync(
                It.IsAny<BlobServiceClient>(),
                It.IsAny<string>(),
                It.IsAny<ServiceBusReceivedMessage>(),
                It.IsAny<CancellationToken>()))
            .ThrowsAsync(new InvalidOperationException("Simulated blob write failure"));

        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage> { message });
        receiverMock
            .Setup(r => r.AbandonMessageAsync(message, It.IsAny<IDictionary<string, object>>(), It.IsAny<CancellationToken>()))
            .Returns(Task.CompletedTask);

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var sut = BuildSut(
            credentialFactory: credMock.Object,
            blobWriter: blobWriterMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        // Should not throw
        await sut.RunAsync(MakeTimer(), CancellationToken.None);

        receiverMock.Verify(
            r => r.AbandonMessageAsync(message, It.IsAny<IDictionary<string, object>>(), It.IsAny<CancellationToken>()),
            Times.Once);
        receiverMock.Verify(
            r => r.CompleteMessageAsync(message, It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task RunAsync_ProcessesEmptyBatch_WithoutError()
    {
        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage>());

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var blobWriterMock = new Mock<IBlobMessageWriter>();

        var sut = BuildSut(
            credentialFactory: credMock.Object,
            blobWriter: blobWriterMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        await sut.RunAsync(MakeTimer(), CancellationToken.None);

        blobWriterMock.Verify(
            w => w.WriteMessageAsync(
                It.IsAny<BlobServiceClient>(),
                It.IsAny<string>(),
                It.IsAny<ServiceBusReceivedMessage>(),
                It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task RunAsync_ProcessesMultipleMessages_IndependentlyOnFailure()
    {
        var msg1 = MakeMessage("msg-001");
        var msg2 = MakeMessage("msg-002");
        var msg3 = MakeMessage("msg-003");

        var blobWriterMock = new Mock<IBlobMessageWriter>();
        // msg1 succeeds, msg2 fails, msg3 succeeds
        blobWriterMock
            .Setup(w => w.WriteMessageAsync(It.IsAny<BlobServiceClient>(), It.IsAny<string>(), msg1, It.IsAny<CancellationToken>()))
            .ReturnsAsync("2024/01/01/msg-001.json");
        blobWriterMock
            .Setup(w => w.WriteMessageAsync(It.IsAny<BlobServiceClient>(), It.IsAny<string>(), msg2, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new Exception("msg2 fail"));
        blobWriterMock
            .Setup(w => w.WriteMessageAsync(It.IsAny<BlobServiceClient>(), It.IsAny<string>(), msg3, It.IsAny<CancellationToken>()))
            .ReturnsAsync("2024/01/01/msg-003.json");

        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage> { msg1, msg2, msg3 });
        receiverMock.Setup(r => r.CompleteMessageAsync(It.IsAny<ServiceBusReceivedMessage>(), It.IsAny<CancellationToken>())).Returns(Task.CompletedTask);
        receiverMock.Setup(r => r.AbandonMessageAsync(It.IsAny<ServiceBusReceivedMessage>(), It.IsAny<IDictionary<string, object>>(), It.IsAny<CancellationToken>())).Returns(Task.CompletedTask);

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var sut = BuildSut(
            credentialFactory: credMock.Object,
            blobWriter: blobWriterMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        await sut.RunAsync(MakeTimer(), CancellationToken.None);

        receiverMock.Verify(r => r.CompleteMessageAsync(msg1, It.IsAny<CancellationToken>()), Times.Once);
        receiverMock.Verify(r => r.AbandonMessageAsync(msg2, It.IsAny<IDictionary<string, object>>(), It.IsAny<CancellationToken>()), Times.Once);
        receiverMock.Verify(r => r.CompleteMessageAsync(msg3, It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task RunAsync_ThrowsWhenRequiredConfigMissing()
    {
        var configMock = new Mock<IEnvironmentConfiguration>();
        configMock
            .Setup(c => c.Require(SettingNames.CrossTenantServiceBusNamespace))
            .Throws(new InvalidOperationException("Required setting not set."));

        var sut = BuildSut(config: configMock.Object);

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => sut.RunAsync(MakeTimer(), CancellationToken.None));
    }

    [Fact]
    public async Task RunAsync_IsPastDue_DoesNotPreventProcessing()
    {
        var receiverMock = new Mock<ServiceBusReceiver>();
        receiverMock
            .Setup(r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ServiceBusReceivedMessage>());

        var sbClientMock = new Mock<ServiceBusClient>();
        sbClientMock
            .Setup(c => c.CreateReceiver(It.IsAny<string>(), It.IsAny<string>()))
            .Returns(receiverMock.Object);

        var credMock = new Mock<ICrossTenantCredentialFactory>();
        credMock.Setup(f => f.CreateServiceBusCredential()).Returns(Mock.Of<TokenCredential>());
        credMock.Setup(f => f.CreateStorageCredential()).Returns(Mock.Of<TokenCredential>());

        var sbFactoryMock = new Mock<IServiceBusClientFactory>();
        sbFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<string>(), It.IsAny<TokenCredential>()))
            .Returns(sbClientMock.Object);

        var blobFactoryMock = new Mock<IBlobServiceClientFactory>();
        blobFactoryMock
            .Setup(f => f.CreateClient(It.IsAny<Uri>(), It.IsAny<TokenCredential>()))
            .Returns(Mock.Of<BlobServiceClient>());

        var sut = BuildSut(
            credentialFactory: credMock.Object,
            sbFactory: sbFactoryMock.Object,
            blobFactory: blobFactoryMock.Object);

        // Should not throw even with isPastDue=true
        await sut.RunAsync(MakeTimer(isPastDue: true), CancellationToken.None);

        receiverMock.Verify(
            r => r.ReceiveMessagesAsync(It.IsAny<int>(), It.IsAny<TimeSpan?>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }
}

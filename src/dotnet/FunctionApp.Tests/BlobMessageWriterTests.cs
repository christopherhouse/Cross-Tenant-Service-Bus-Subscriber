using Azure.Messaging.ServiceBus;
using Azure.Storage.Blobs;
using CrossTenantServiceBus.FunctionApp;
using Microsoft.Extensions.Logging;
using Moq;
using System.Text;
using System.Text.Json;

namespace CrossTenantServiceBus.FunctionApp.Tests;

/// <summary>
/// Unit tests for <see cref="BlobMessageWriter"/>.
/// </summary>
public class BlobMessageWriterTests
{
    private static BlobMessageWriter BuildSut()
    {
        var logger = Mock.Of<ILogger<BlobMessageWriter>>();
        return new BlobMessageWriter(logger);
    }

    private static ServiceBusReceivedMessage MakeMessage(
        string body = """{"event": "test"}""",
        string messageId = "msg-001",
        string contentType = "application/json",
        string subject = "test-subject",
        string correlationId = "corr-001",
        DateTimeOffset? enqueuedTime = null,
        IDictionary<string, object>? applicationProperties = null)
    {
        return ServiceBusModelFactory.ServiceBusReceivedMessage(
            body: BinaryData.FromString(body),
            messageId: messageId,
            contentType: contentType,
            subject: subject,
            correlationId: correlationId,
            enqueuedTime: enqueuedTime ?? new DateTimeOffset(2024, 1, 15, 12, 0, 0, TimeSpan.Zero),
            properties: applicationProperties ?? new Dictionary<string, object> { ["key"] = "value" });
    }

    private static (Mock<BlobServiceClient> ServiceMock, Mock<BlobContainerClient> ContainerMock, Mock<BlobClient> BlobMock)
        BuildBlobClientMocks()
    {
        var blobMock = new Mock<BlobClient>();
        blobMock
            .Setup(b => b.UploadAsync(
                It.IsAny<Stream>(),
                It.IsAny<bool>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(Mock.Of<Azure.Response<Azure.Storage.Blobs.Models.BlobContentInfo>>());

        var containerMock = new Mock<BlobContainerClient>();
        containerMock
            .Setup(c => c.GetBlobClient(It.IsAny<string>()))
            .Returns(blobMock.Object);

        var serviceMock = new Mock<BlobServiceClient>();
        serviceMock
            .Setup(s => s.GetBlobContainerClient(It.IsAny<string>()))
            .Returns(containerMock.Object);

        return (serviceMock, containerMock, blobMock);
    }

    [Fact]
    public async Task WriteMessageAsync_ReturnsBlobNameWithDatePrefix()
    {
        var sut = BuildSut();
        var (serviceMock, _, _) = BuildBlobClientMocks();
        var message = MakeMessage(messageId: "msg-123");

        var blobName = await sut.WriteMessageAsync(
            serviceMock.Object, "my-container", message);

        var todayPrefix = DateTime.UtcNow.ToString("yyyy/MM/dd");
        Assert.StartsWith(todayPrefix + "/", blobName);
        Assert.EndsWith("msg-123.json", blobName);
    }

    [Fact]
    public async Task WriteMessageAsync_GeneratesGuidForMissingMessageId()
    {
        var sut = BuildSut();
        var (serviceMock, _, _) = BuildBlobClientMocks();
        var message = MakeMessage(messageId: "");

        var blobName = await sut.WriteMessageAsync(
            serviceMock.Object, "my-container", message);

        // Should still produce a valid-looking path ending in .json
        Assert.EndsWith(".json", blobName);
        Assert.Matches(@"\d{4}/\d{2}/\d{2}/.+\.json", blobName);
    }

    [Fact]
    public async Task WriteMessageAsync_WritesValidJsonEnvelope()
    {
        var sut = BuildSut();

        // Capture what's written to the blob
        string? capturedJson = null;
        var blobMock = new Mock<BlobClient>();
        blobMock
            .Setup(b => b.UploadAsync(
                It.IsAny<Stream>(),
                It.IsAny<bool>(),
                It.IsAny<CancellationToken>()))
            .Callback<Stream, bool, CancellationToken>(async (stream, _, _) =>
            {
                using var reader = new StreamReader(stream);
                capturedJson = await reader.ReadToEndAsync();
            })
            .ReturnsAsync(Mock.Of<Azure.Response<Azure.Storage.Blobs.Models.BlobContentInfo>>());

        var containerMock = new Mock<BlobContainerClient>();
        containerMock.Setup(c => c.GetBlobClient(It.IsAny<string>())).Returns(blobMock.Object);

        var serviceMock = new Mock<BlobServiceClient>();
        serviceMock.Setup(s => s.GetBlobContainerClient(It.IsAny<string>())).Returns(containerMock.Object);

        var enqueuedTime = new DateTimeOffset(2024, 1, 15, 12, 0, 0, TimeSpan.Zero);
        var message = MakeMessage(
            body: """{"event":"test"}""",
            messageId: "msg-001",
            contentType: "application/json",
            subject: "test-subject",
            correlationId: "corr-001",
            enqueuedTime: enqueuedTime);

        await sut.WriteMessageAsync(serviceMock.Object, "container", message);

        Assert.NotNull(capturedJson);
        var doc = JsonDocument.Parse(capturedJson);
        var root = doc.RootElement;

        Assert.Equal("msg-001", root.GetProperty("messageId").GetString());
        Assert.Equal("application/json", root.GetProperty("contentType").GetString());
        Assert.Equal("test-subject", root.GetProperty("subject").GetString());
        Assert.Equal("corr-001", root.GetProperty("correlationId").GetString());
        Assert.NotNull(root.GetProperty("receivedAt").GetString());
        Assert.Equal("""{"event":"test"}""", root.GetProperty("body").GetString());
    }

    [Fact]
    public async Task WriteMessageAsync_UploadsBlobWithOverwriteTrue()
    {
        var sut = BuildSut();
        var (serviceMock, _, blobMock) = BuildBlobClientMocks();
        var message = MakeMessage();

        await sut.WriteMessageAsync(serviceMock.Object, "container", message);

        blobMock.Verify(
            b => b.UploadAsync(
                It.IsAny<Stream>(),
                true,
                It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task WriteMessageAsync_UsesCorrectContainerName()
    {
        var sut = BuildSut();
        var (serviceMock, _, _) = BuildBlobClientMocks();
        var message = MakeMessage();

        await sut.WriteMessageAsync(serviceMock.Object, "my-messages", message);

        serviceMock.Verify(s => s.GetBlobContainerClient("my-messages"), Times.Once);
    }

    [Fact]
    public async Task WriteMessageAsync_HandlesNonUtf8Body_WithHexFallback()
    {
        var sut = BuildSut();

        string? capturedJson = null;
        var blobMock = new Mock<BlobClient>();
        blobMock
            .Setup(b => b.UploadAsync(
                It.IsAny<Stream>(),
                It.IsAny<bool>(),
                It.IsAny<CancellationToken>()))
            .Callback<Stream, bool, CancellationToken>(async (stream, _, _) =>
            {
                using var reader = new StreamReader(stream);
                capturedJson = await reader.ReadToEndAsync();
            })
            .ReturnsAsync(Mock.Of<Azure.Response<Azure.Storage.Blobs.Models.BlobContentInfo>>());

        var containerMock = new Mock<BlobContainerClient>();
        containerMock.Setup(c => c.GetBlobClient(It.IsAny<string>())).Returns(blobMock.Object);
        var serviceMock = new Mock<BlobServiceClient>();
        serviceMock.Setup(s => s.GetBlobContainerClient(It.IsAny<string>())).Returns(containerMock.Object);

        // Create a message with raw non-UTF8 bytes
        var rawBytes = new byte[] { 0xFF, 0xFE, 0x00, 0x01 };
        var message = ServiceBusModelFactory.ServiceBusReceivedMessage(
            body: BinaryData.FromBytes(rawBytes),
            messageId: "msg-hex");

        await sut.WriteMessageAsync(serviceMock.Object, "container", message);

        Assert.NotNull(capturedJson);
        var doc = JsonDocument.Parse(capturedJson);
        var bodyValue = doc.RootElement.GetProperty("body").GetString();

        // Body should be hex-encoded since raw bytes aren't valid UTF-8
        Assert.Equal(Convert.ToHexString(rawBytes), bodyValue);
    }
}

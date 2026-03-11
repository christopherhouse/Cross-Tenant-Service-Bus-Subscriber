using Azure.Messaging.ServiceBus;
using Azure.Storage.Blobs;
using Microsoft.Extensions.Logging;
using System.Text;
using System.Text.Json;

namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Writes a Service Bus message payload to Azure Blob Storage as a JSON envelope.
/// </summary>
public interface IBlobMessageWriter
{
    /// <summary>
    /// Persists a single Service Bus message as a JSON blob.
    /// </summary>
    /// <param name="blobServiceClient">
    /// A <see cref="BlobServiceClient"/> authenticated to the Tenant A storage account.
    /// </param>
    /// <param name="containerName">Target blob container name.</param>
    /// <param name="message">The Service Bus message to persist.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>
    /// The blob name written, in the form
    /// <c>YYYY/MM/DD/&lt;message-id&gt;.json</c>.
    /// </returns>
    Task<string> WriteMessageAsync(
        BlobServiceClient blobServiceClient,
        string containerName,
        ServiceBusReceivedMessage message,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Default implementation of <see cref="IBlobMessageWriter"/>.
///
/// Blob naming: <c>YYYY/MM/DD/&lt;message-id&gt;.json</c>
///
/// The blob content is a JSON object with the following fields:
/// <code>
/// {
///   "messageId":            "&lt;string&gt;",
///   "enqueuedAt":           "&lt;ISO-8601 UTC or null&gt;",
///   "receivedAt":           "&lt;ISO-8601 UTC&gt;",
///   "contentType":          "&lt;string or null&gt;",
///   "subject":              "&lt;string or null&gt;",
///   "correlationId":        "&lt;string or null&gt;",
///   "applicationProperties": { ... },
///   "body":                 "&lt;UTF-8 string, or hex-encoded fallback&gt;"
/// }
/// </code>
/// </summary>
internal sealed class BlobMessageWriter : IBlobMessageWriter
{
    private readonly ILogger<BlobMessageWriter> _logger;

    public BlobMessageWriter(ILogger<BlobMessageWriter> logger)
    {
        _logger = logger;
    }

    /// <inheritdoc />
    public async Task<string> WriteMessageAsync(
        BlobServiceClient blobServiceClient,
        string containerName,
        ServiceBusReceivedMessage message,
        CancellationToken cancellationToken = default)
    {
        var messageId = string.IsNullOrWhiteSpace(message.MessageId)
            ? Guid.NewGuid().ToString()
            : message.MessageId;

        var datePrefix = DateTime.UtcNow.ToString("yyyy/MM/dd");
        var blobName = $"{datePrefix}/{messageId}.json";

        // Decode the message body as UTF-8; fall back to hex if it isn't valid UTF-8.
        string bodyText;
        try
        {
            // Use strict UTF-8 decoder to detect invalid byte sequences.
            var strictUtf8 = new System.Text.UTF8Encoding(
                encoderShouldEmitUTF8Identifier: false,
                throwOnInvalidBytes: true);
            bodyText = strictUtf8.GetString(message.Body.ToArray());
        }
        catch (Exception ex) when (ex is ArgumentException or System.Text.DecoderFallbackException)
        {
            _logger.LogWarning(ex,
                "Message {MessageId} body is not valid UTF-8; storing as hex.", messageId);
            bodyText = Convert.ToHexString(message.Body.ToArray());
        }

        var envelope = new
        {
            messageId,
            enqueuedAt = message.EnqueuedTime == default
                ? (DateTimeOffset?)null
                : message.EnqueuedTime,
            receivedAt = DateTimeOffset.UtcNow,
            contentType = message.ContentType,
            subject = message.Subject,
            correlationId = message.CorrelationId,
            applicationProperties = message.ApplicationProperties
                .ToDictionary(kvp => kvp.Key, kvp => kvp.Value),
            body = bodyText,
        };

        var json = JsonSerializer.Serialize(envelope, new JsonSerializerOptions
        {
            WriteIndented = false,
        });

        var blobClient = blobServiceClient
            .GetBlobContainerClient(containerName)
            .GetBlobClient(blobName);

        using var stream = new MemoryStream(Encoding.UTF8.GetBytes(json));
        await blobClient.UploadAsync(stream, overwrite: true, cancellationToken);

        return blobName;
    }
}

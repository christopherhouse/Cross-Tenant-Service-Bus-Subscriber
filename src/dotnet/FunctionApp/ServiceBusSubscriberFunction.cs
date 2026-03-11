using Azure.Messaging.ServiceBus;
using Azure.Storage.Blobs;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Extensions.Logging;

namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Timer-triggered Azure Function that polls a Service Bus topic subscription
/// in a remote Entra tenant (Tenant B) and persists each message payload as a
/// JSON blob in Azure Blob Storage in the local tenant (Tenant A).
///
/// Authentication overview
/// ────────────────────────
/// Cross-tenant Service Bus access uses an explicit token-exchange chain:
///
///   UAMI (Tenant A)
///     │  ManagedIdentityCredential → federated token (api://AzureADTokenExchange)
///     ▼
///   ClientAssertionCredential
///     │  client_assertion → Tenant B token exchange
///     ▼
///   ServiceBusClient (Tenant B namespace)
///
/// Blob Storage (same tenant) is accessed via a direct ManagedIdentityCredential:
///
///   ManagedIdentityCredential (UAMI) → BlobServiceClient (Tenant A)
///
/// Required application settings
/// ──────────────────────────────
/// CROSS_TENANT_SERVICE_BUS_NAMESPACE  – FQDN of the Service Bus namespace
/// CROSS_TENANT_TENANT_ID              – Entra Tenant ID of Tenant B
/// CROSS_TENANT_APP_CLIENT_ID          – Client ID of the multitenant App Registration
/// CROSS_TENANT_TOPIC_NAME             – Service Bus topic name
/// CROSS_TENANT_SUBSCRIPTION_NAME      – Service Bus subscription name
/// USER_ASSIGNED_MI_CLIENT_ID          – Client ID of the UAMI in Tenant A
/// STORAGE_ACCOUNT_NAME                – Storage account name (Tenant A)
/// STORAGE_CONTAINER_NAME              – Blob container name for received messages
///
/// Optional application settings
/// ──────────────────────────────
/// TIMER_SCHEDULE          – NCRONTAB schedule; default "0 */1 * * * *" (every minute)
/// SB_MAX_MESSAGE_COUNT    – max messages per poll; default 100
/// SB_MAX_WAIT_TIME_SECONDS – max wait time per poll in seconds; default 5
/// </summary>
public class ServiceBusSubscriberFunction
{
    private readonly IEnvironmentConfiguration _config;
    private readonly ICrossTenantCredentialFactory _credentialFactory;
    private readonly IBlobMessageWriter _blobWriter;
    private readonly IServiceBusClientFactory _sbClientFactory;
    private readonly IBlobServiceClientFactory _blobClientFactory;
    private readonly ILogger<ServiceBusSubscriberFunction> _logger;

    public ServiceBusSubscriberFunction(
        IEnvironmentConfiguration config,
        ICrossTenantCredentialFactory credentialFactory,
        IBlobMessageWriter blobWriter,
        IServiceBusClientFactory sbClientFactory,
        IBlobServiceClientFactory blobClientFactory,
        ILogger<ServiceBusSubscriberFunction> logger)
    {
        _config = config;
        _credentialFactory = credentialFactory;
        _blobWriter = blobWriter;
        _sbClientFactory = sbClientFactory;
        _blobClientFactory = blobClientFactory;
        _logger = logger;
    }

    [Function("ServiceBusSubscriber")]
    public async Task RunAsync(
        [TimerTrigger("%TIMER_SCHEDULE%")] TimerInfo timer,
        CancellationToken cancellationToken)
    {
        if (timer.IsPastDue)
        {
            _logger.LogWarning("Timer is past due; processing may have been delayed.");
        }

        // ── Required configuration ────────────────────────────────────────────
        var sbNamespace = _config.Require(SettingNames.CrossTenantServiceBusNamespace);
        var topicName = _config.Require(SettingNames.CrossTenantTopicName);
        var subscriptionName = _config.Require(SettingNames.CrossTenantSubscriptionName);
        var storageAccountName = _config.Require(SettingNames.StorageAccountName);
        var containerName = _config.Require(SettingNames.StorageContainerName);

        // ── Optional configuration ────────────────────────────────────────────
        var maxMessageCount = int.Parse(_config.Optional(SettingNames.SbMaxMessageCount, "100"));
        var maxWaitTime = TimeSpan.FromSeconds(
            double.Parse(_config.Optional(SettingNames.SbMaxWaitTimeSeconds, "5")));

        // ── Credentials ───────────────────────────────────────────────────────
        var sbCredential = _credentialFactory.CreateServiceBusCredential();
        var storageCredential = _credentialFactory.CreateStorageCredential();

        var storageUrl = new Uri($"https://{storageAccountName}.blob.core.windows.net");
        var blobServiceClient = _blobClientFactory.CreateClient(storageUrl, storageCredential);

        // ── Poll and process messages ─────────────────────────────────────────
        var processed = 0;
        var failed = 0;

        await using var sbClient = _sbClientFactory.CreateClient(sbNamespace, sbCredential);
        var receiver = sbClient.CreateReceiver(topicName, subscriptionName);
        await using var _ = receiver;

        var messages = await receiver.ReceiveMessagesAsync(
            maxMessages: maxMessageCount,
            maxWaitTime: maxWaitTime,
            cancellationToken: cancellationToken);

        foreach (var message in messages)
        {
            try
            {
                var blobName = await _blobWriter.WriteMessageAsync(
                    blobServiceClient, containerName, message, cancellationToken);

                await receiver.CompleteMessageAsync(message, cancellationToken);

                _logger.LogInformation(
                    "Message {MessageId} written to blob '{BlobName}'.",
                    message.MessageId,
                    blobName);

                processed++;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Failed to process message {MessageId}; abandoning.",
                    message.MessageId);

                await receiver.AbandonMessageAsync(message, cancellationToken: cancellationToken);
                failed++;
            }
        }

        _logger.LogInformation(
            "Poll complete: {Processed} processed, {Failed} failed/abandoned.",
            processed, failed);
    }
}

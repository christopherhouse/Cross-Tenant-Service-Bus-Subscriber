namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Centralized definitions for all application-setting / environment-variable names.
/// </summary>
internal static class SettingNames
{
    // ── Cross-tenant Service Bus ──────────────────────────────────────────────

    /// <summary>
    /// Fully-qualified domain name of the Service Bus namespace in Tenant B.
    /// Example: <c>mybus.servicebus.windows.net</c>
    /// </summary>
    public const string CrossTenantServiceBusNamespace = "CROSS_TENANT_SERVICE_BUS_NAMESPACE";

    /// <summary>
    /// Entra tenant ID of Tenant B (the Service Bus tenant).
    /// </summary>
    public const string CrossTenantTenantId = "CROSS_TENANT_TENANT_ID";

    /// <summary>
    /// Client ID of the multi-tenant App Registration in Tenant B that has
    /// the federated credential configured.
    /// </summary>
    public const string CrossTenantAppClientId = "CROSS_TENANT_APP_CLIENT_ID";

    /// <summary>The Service Bus topic name.</summary>
    public const string CrossTenantTopicName = "CROSS_TENANT_TOPIC_NAME";

    /// <summary>The Service Bus topic subscription name.</summary>
    public const string CrossTenantSubscriptionName = "CROSS_TENANT_SUBSCRIPTION_NAME";

    // ── Identity ──────────────────────────────────────────────────────────────

    /// <summary>
    /// Client ID of the User-Assigned Managed Identity (UAMI) in Tenant A.
    /// Used both for the federated assertion and for Blob Storage access.
    /// </summary>
    public const string UserAssignedMiClientId = "USER_ASSIGNED_MI_CLIENT_ID";

    // ── Storage ───────────────────────────────────────────────────────────────

    /// <summary>Storage account name in Tenant A.</summary>
    public const string StorageAccountName = "STORAGE_ACCOUNT_NAME";

    /// <summary>Blob container name for received messages.</summary>
    public const string StorageContainerName = "STORAGE_CONTAINER_NAME";

    // ── Optional ─────────────────────────────────────────────────────────────

    /// <summary>
    /// NCRONTAB timer schedule.  Defaults to every minute:
    /// <c>0 */1 * * * *</c>
    /// </summary>
    public const string TimerSchedule = "TIMER_SCHEDULE";

    /// <summary>
    /// Maximum number of messages to receive per poll.  Default: <c>100</c>.
    /// </summary>
    public const string SbMaxMessageCount = "SB_MAX_MESSAGE_COUNT";

    /// <summary>
    /// Maximum time (seconds) to wait for messages per poll.
    /// Default: <c>5</c>.
    /// </summary>
    public const string SbMaxWaitTimeSeconds = "SB_MAX_WAIT_TIME_SECONDS";
}

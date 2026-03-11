using Azure.Core;
using Azure.Messaging.ServiceBus;
using Azure.Storage.Blobs;

namespace CrossTenantServiceBus.FunctionApp;

/// <summary>
/// Factory for creating <see cref="ServiceBusClient"/> instances.
/// Abstracted to enable unit testing without real Azure connections.
/// </summary>
public interface IServiceBusClientFactory
{
    /// <summary>
    /// Creates a <see cref="ServiceBusClient"/> for the given namespace and credential.
    /// </summary>
    ServiceBusClient CreateClient(string fullyQualifiedNamespace, TokenCredential credential);
}

/// <summary>
/// Factory for creating <see cref="BlobServiceClient"/> instances.
/// Abstracted to enable unit testing without real Azure connections.
/// </summary>
public interface IBlobServiceClientFactory
{
    /// <summary>
    /// Creates a <see cref="BlobServiceClient"/> for the given URI and credential.
    /// </summary>
    BlobServiceClient CreateClient(Uri serviceUri, TokenCredential credential);
}

/// <summary>
/// Default implementation that creates real Azure SDK clients.
/// </summary>
internal sealed class ServiceBusClientFactory : IServiceBusClientFactory
{
    public ServiceBusClient CreateClient(string fullyQualifiedNamespace, TokenCredential credential)
        => new ServiceBusClient(fullyQualifiedNamespace, credential);
}

/// <summary>
/// Default implementation that creates real Azure SDK clients.
/// </summary>
internal sealed class BlobServiceClientFactory : IBlobServiceClientFactory
{
    public BlobServiceClient CreateClient(Uri serviceUri, TokenCredential credential)
        => new BlobServiceClient(serviceUri, credential);
}

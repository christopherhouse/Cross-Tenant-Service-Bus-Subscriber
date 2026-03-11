using CrossTenantServiceBus.FunctionApp;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = FunctionsApplication.CreateBuilder(args);

builder.Services
    .AddApplicationInsightsTelemetryWorkerService()
    .ConfigureFunctionsApplicationInsights()
    .AddSingleton<IEnvironmentConfiguration, EnvironmentConfiguration>()
    .AddSingleton<ICrossTenantCredentialFactory, CrossTenantCredentialFactory>()
    .AddSingleton<IBlobMessageWriter, BlobMessageWriter>()
    .AddSingleton<IServiceBusClientFactory, ServiceBusClientFactory>()
    .AddSingleton<IBlobServiceClientFactory, BlobServiceClientFactory>();

builder.Build().Run();

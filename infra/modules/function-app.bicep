/*
  modules/function-app.bicep
  Provisions the Azure Function App with:
  • Containerised Linux runtime pulled from Azure Container Registry (ACR)
  • User Assigned Managed Identity (used for ACR pull + AzureWebJobsStorage)
  • All application settings required by the function code
  • AzureWebJobsStorage configured to use identity-based auth
  • Cross-tenant Service Bus auth handled entirely by the Python function code
    using ClientAssertionCredential (UAMI → federated credential → App
    Registration in Tenant B).  The runtime no longer manages the Service Bus
    connection; the six SERVICE_BUS_CONNECTION__* settings have been removed.
*/

@description('Name of the Function App.')
param name                          string

@description('Azure region for the Function App.')
param location                      string

@description('Resource ID of the App Service Plan.')
param appServicePlanId              string

@description('Name of the Storage Account used for AzureWebJobsStorage.')
param storageAccountName            string

@description('Resource ID of the Log Analytics workspace.')
param logAnalyticsWorkspaceId       string

@description('Application Insights connection string.')
param appInsightsConnectionString   string

@description('Resource ID of the User Assigned Managed Identity.')
param uamiId                        string

@description('Client ID of the User Assigned Managed Identity.')
param uamiClientId                  string

// Cross-tenant Service Bus settings
@description('FQDN of the Service Bus namespace in Tenant B (e.g. mybus.servicebus.windows.net). Consumed directly by Python code as CROSS_TENANT_SERVICE_BUS_NAMESPACE; not a runtime binding setting.')
param crossTenantServiceBusNamespace string

@description('Service Bus topic name in Tenant B.')
param crossTenantTopicName           string

@description('Service Bus topic subscription name in Tenant B.')
param crossTenantSubscriptionName    string

@description('Entra Tenant ID of Tenant B. Consumed directly by Python code as CROSS_TENANT_TENANT_ID for ClientAssertionCredential; not a runtime binding setting.')
param crossTenantTenantId            string

@description('Client ID of the App Registration in Tenant B with a federated credential trusting the UAMI. Consumed directly by Python code as CROSS_TENANT_APP_CLIENT_ID for ClientAssertionCredential; not a runtime binding setting.')
param crossTenantAppClientId         string

// Storage settings
@description('Name of the Storage Account used to persist received messages.')
param storageAccountNameForMessages  string

@description('Blob container name where received messages are stored.')
param messageContainerName           string

// Container Registry settings
@description('Login server URL of the Azure Container Registry (e.g. crsbsubdev.azurecr.io).')
param acrLoginServer                 string

@description('Container image name to pull from ACR (e.g. func-sbsub).')
param imageName                      string

@description('Container image tag to deploy. Defaults to "latest"; set to a specific SHA or semver tag for reproducible deployments.')
param imageTag                       string = 'latest'

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name:     name
  location: location
  kind:     'functionapp,linux'
  identity: {
    type:                   'UserAssigned'
    userAssignedIdentities: { '${uamiId}': {} }
  }
  properties: {
    serverFarmId: appServicePlanId
    reserved:     true
    siteConfig: {
      linuxFxVersion:              'DOCKER|${acrLoginServer}/${imageName}:${imageTag}'
      acrUseManagedIdentityCreds:  true
      acrUserManagedIdentityID:    uamiClientId
      appSettings: [
        // ── Azure Functions runtime ─────────────────────────────────────────
        {
          name:  'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name:  'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        // ── Docker registry (ACR) ───────────────────────────────────────────
        {
          name:  'DOCKER_REGISTRY_SERVER_URL'
          value: 'https://${acrLoginServer}'
        }
        // ── Identity-based AzureWebJobsStorage ──────────────────────────────
        // Avoids storing a storage connection string in plaintext.
        {
          name:  'AzureWebJobsStorage__accountName'
          value: storageAccountName
        }
        {
          name:  'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name:  'AzureWebJobsStorage__clientId'
          value: uamiClientId
        }
        // ── Diagnostics ─────────────────────────────────────────────────────
        {
          name:  'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        // ── Cross-tenant Service Bus (read directly by Python function code) ────
        // The function uses ClientAssertionCredential with a federated identity
        // assertion issued by the UAMI to authenticate against a Service Bus
        // namespace in a different Entra tenant (Tenant B).  These values are
        // consumed by the application code; the Functions runtime no longer
        // manages the Service Bus connection.
        {
          name:  'CROSS_TENANT_SERVICE_BUS_NAMESPACE'
          value: crossTenantServiceBusNamespace
        }
        {
          name:  'CROSS_TENANT_TENANT_ID'
          value: crossTenantTenantId
        }
        {
          name:  'CROSS_TENANT_APP_CLIENT_ID'
          value: crossTenantAppClientId
        }
        // ── Service Bus topic / subscription (consumed by function code) ──────
        {
          name:  'CROSS_TENANT_TOPIC_NAME'
          value: crossTenantTopicName
        }
        {
          name:  'CROSS_TENANT_SUBSCRIPTION_NAME'
          value: crossTenantSubscriptionName
        }
        // ── UAMI ─────────────────────────────────────────────────────────────
        {
          name:  'USER_ASSIGNED_MI_CLIENT_ID'
          value: uamiClientId
        }
        // ── Message storage ──────────────────────────────────────────────────
        {
          name:  'STORAGE_ACCOUNT_NAME'
          value: storageAccountNameForMessages
        }
        {
          name:  'STORAGE_CONTAINER_NAME'
          value: messageContainerName
        }
      ]
      ftpsState:          'Disabled'
      minTlsVersion:      '1.2'
      http20Enabled:      true
    }
    httpsOnly: true
  }
}

output id   string = functionApp.id
output name string = functionApp.name

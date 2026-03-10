/*
  modules/function-app.bicep
  Provisions the Azure Function App with:
  • Python 3.13 Linux runtime
  • User Assigned Managed Identity
  • All application settings required by the function code
  • AzureWebJobsStorage configured to use identity-based auth
  • SERVICE_BUS_CONNECTION configured for cross-tenant federated identity
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
@description('Fully-qualified Service Bus namespace hostname in Tenant B (e.g. mybus.servicebus.windows.net).')
param crossTenantServiceBusNamespace string

@description('Service Bus topic name in Tenant B.')
param crossTenantTopicName           string

@description('Service Bus topic subscription name in Tenant B.')
param crossTenantSubscriptionName    string

@description('Entra Tenant ID of Tenant B (the Service Bus tenant).')
param crossTenantTenantId            string

@description('Client ID of the App Registration in Tenant B that has a federated credential trusting the UAMI.')
param crossTenantAppClientId         string

// Storage settings
@description('Name of the Storage Account used to persist received messages.')
param storageAccountNameForMessages  string

@description('Blob container name where received messages are stored.')
param messageContainerName           string

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
      linuxFxVersion: 'Python|3.13'
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
        // ── Service Bus trigger identity-based connection (cross-tenant) ─────
        // The trigger binding resolves these via the "SERVICE_BUS_CONNECTION"
        // prefix.  Cross-tenant access uses managedidentityasfederatedidentity:
        //   UAMI (Tenant A) → federated credential → App Registration (Tenant B)
        //   → Service Bus Data Receiver role on the Tenant B namespace.
        // Note: on Consumption/Flex Consumption plans the platform will not
        // auto-scale based on a cross-tenant trigger; the function still fires.
        {
          name:  'SERVICE_BUS_CONNECTION__fullyQualifiedNamespace'
          value: crossTenantServiceBusNamespace
        }
        {
          name:  'SERVICE_BUS_CONNECTION__credential'
          value: 'managedidentityasfederatedidentity'
        }
        {
          name:  'SERVICE_BUS_CONNECTION__azureCloud'
          value: 'public'
        }
        {
          name:  'SERVICE_BUS_CONNECTION__clientId'
          value: crossTenantAppClientId
        }
        {
          name:  'SERVICE_BUS_CONNECTION__tenantId'
          value: crossTenantTenantId
        }
        {
          name:  'SERVICE_BUS_CONNECTION__managedIdentityClientId'
          value: uamiClientId
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

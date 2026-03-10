/*
  modules/function-app.bicep
  Provisions the Azure Function App with:
  • Python 3.13 Linux runtime
  • User Assigned Managed Identity
  • All application settings required by the function code
  • AzureWebJobsStorage configured to use identity-based auth
*/

param name                          string
param location                      string
param appServicePlanId              string
param storageAccountName            string
param logAnalyticsWorkspaceId       string
param appInsightsConnectionString   string
param uamiId                        string
param uamiClientId                  string

// Cross-tenant Service Bus settings
param crossTenantServiceBusNamespace string
param crossTenantTopicName           string
param crossTenantSubscriptionName    string
param crossTenantTenantId            string
param crossTenantAppClientId         string

// Storage / runtime settings
param storageAccountNameForMessages  string
param messageContainerName           string
param timerSchedule                  string
param maxMessageBatchSize            int

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
        // ── Cross-tenant Service Bus ─────────────────────────────────────────
        {
          name:  'CROSS_TENANT_SERVICE_BUS_NAMESPACE'
          value: crossTenantServiceBusNamespace
        }
        {
          name:  'CROSS_TENANT_TOPIC_NAME'
          value: crossTenantTopicName
        }
        {
          name:  'CROSS_TENANT_SUBSCRIPTION_NAME'
          value: crossTenantSubscriptionName
        }
        {
          name:  'CROSS_TENANT_TENANT_ID'
          value: crossTenantTenantId
        }
        {
          name:  'CROSS_TENANT_APP_CLIENT_ID'
          value: crossTenantAppClientId
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
        // ── Runtime tuning ───────────────────────────────────────────────────
        {
          name:  'TIMER_SCHEDULE'
          value: timerSchedule
        }
        {
          name:  'MAX_MESSAGE_BATCH_SIZE'
          value: string(maxMessageBatchSize)
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

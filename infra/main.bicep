/*
  main.bicep – Cross-Tenant Service Bus Subscriber: Tenant A infrastructure

  Deploys all Azure resources required to host the Azure Function that polls a
  Service Bus topic in a remote (Tenant B) Entra tenant and writes message
  payloads to Blob Storage.

  Resources provisioned
  ─────────────────────
  • User Assigned Managed Identity   – used by the Function for both cross-tenant
                                       Service Bus auth and same-tenant Blob/ACR auth
  • Storage Account                  – AzureWebJobsStorage + message blob sink
  • Blob Container                   – target container for received messages
  • Azure Container Registry (ACR)   – hosts the containerised Function image
  • App Service Plan                 – Elastic Premium EP1 (required for containers)
  • Function App                     – containerised Python image from ACR
  • Application Insights workspace   – diagnostics
  • Log Analytics workspace          – backing store for App Insights
*/

targetScope = 'resourceGroup'

// ── Parameters ──────────────────────────────────────────────────────────────

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short environment identifier, e.g. dev / test / prod.')
@allowed(['dev', 'test', 'prod'])
param environmentName string = 'dev'

@description('Optional workload name prefix.  Defaults to "sbsub".')
param workloadName string = 'sbsub'

// ── Cross-tenant Service Bus settings (stored as Function App settings) ──────

@description('Fully-qualified Service Bus namespace hostname in Tenant B.')
param crossTenantServiceBusNamespace string

@description('Service Bus topic name in Tenant B.')
param crossTenantTopicName string

@description('Service Bus topic subscription name in Tenant B.')
param crossTenantSubscriptionName string

@description('Entra Tenant ID of Tenant B (the Service Bus tenant).')
param crossTenantTenantId string

@description('Client ID of the App Registration in Tenant B that has a federated credential trusting the UAMI.')
param crossTenantAppClientId string

// ── Function runtime settings ────────────────────────────────────────────────

@description('Blob container name where received messages are stored.')
param messageContainerName string = 'sb-messages'

// ── Derived names ────────────────────────────────────────────────────────────

var abbr = '${workloadName}-${environmentName}'
var uamiName = 'id-${abbr}'
var storageAccountName = replace('st${workloadName}${environmentName}', '-', '') // storage names: no hyphens, max 24 chars
var acrName = 'cr${workloadName}${environmentName}'                               // ACR names: no hyphens, max 50 chars
var appServicePlanName = 'asp-${abbr}'
var functionAppName = 'func-${abbr}'
var imageName = 'func-${abbr}'
var logAnalyticsName = 'log-${abbr}'
var appInsightsName = 'appi-${abbr}'

// ── Modules ──────────────────────────────────────────────────────────────────

module identity 'modules/user-assigned-identity.bicep' = {
  name: 'deploy-identity'
  params: {
    name: uamiName
    location: location
  }
}

module storage 'modules/storage-account.bicep' = {
  name: 'deploy-storage'
  params: {
    name: storageAccountName
    location: location
    uamiPrincipalId: identity.outputs.principalId
    messageContainerName: messageContainerName
  }
}

module appServicePlan 'modules/app-service-plan.bicep' = {
  name: 'deploy-app-service-plan'
  params: {
    name: appServicePlanName
    location: location
  }
}

module containerRegistry 'modules/container-registry.bicep' = {
  name: 'deploy-container-registry'
  params: {
    name: acrName
    location: location
    uamiPrincipalId: identity.outputs.principalId
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'deploy-function-app'
  params: {
    name: functionAppName
    location: location
    appServicePlanId: appServicePlan.outputs.id
    storageAccountName: storage.outputs.name
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
    appInsightsConnectionString: appInsights.outputs.connectionString
    uamiId: identity.outputs.id
    uamiClientId: identity.outputs.clientId
    crossTenantServiceBusNamespace: crossTenantServiceBusNamespace
    crossTenantTopicName: crossTenantTopicName
    crossTenantSubscriptionName: crossTenantSubscriptionName
    crossTenantTenantId: crossTenantTenantId
    crossTenantAppClientId: crossTenantAppClientId
    storageAccountNameForMessages: storage.outputs.name
    messageContainerName: messageContainerName
    acrLoginServer: containerRegistry.outputs.loginServer
    imageName: imageName
  }
}

module logAnalytics 'modules/log-analytics-workspace.bicep' = {
  name: 'deploy-log-analytics'
  params: {
    name: logAnalyticsName
    location: location
  }
}

module appInsights 'modules/app-insights.bicep' = {
  name: 'deploy-app-insights'
  params: {
    name: appInsightsName
    location: location
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
  }
}

// ── Outputs ──────────────────────────────────────────────────────────────────

@description('Resource ID of the User Assigned Managed Identity.')
output uamiResourceId string = identity.outputs.id

@description('Principal ID (object ID) of the UAMI – assign roles in Tenant B to this value.')
output uamiPrincipalId string = identity.outputs.principalId

@description('Client ID of the UAMI – set as USER_ASSIGNED_MI_CLIENT_ID in the function.')
output uamiClientId string = identity.outputs.clientId

@description('Function App name.')
output functionAppName string = functionApp.outputs.name

@description('Storage Account name.')
output storageAccountName string = storage.outputs.name

@description('Name of the Azure Container Registry.')
output acrName string = containerRegistry.outputs.name

@description('Login server URL of the Azure Container Registry.')
output acrLoginServer string = containerRegistry.outputs.loginServer

/*
  modules/container-registry.bicep
  Provisions an Azure Container Registry (Basic SKU) with admin user disabled
  and grants the UAMI the AcrPull role so the Function App can pull container
  images using its managed identity.
*/

@description('Name of the Azure Container Registry (lowercase alphanumeric, max 50 chars).')
param name string

@description('Azure region for the Container Registry.')
param location string

@description('Principal ID of the User Assigned Managed Identity to grant AcrPull.')
param uamiPrincipalId string

// ── Container Registry ───────────────────────────────────────────────────────

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name:     name
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// ── RBAC: grant UAMI AcrPull ─────────────────────────────────────────────────

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(containerRegistry.id, uamiPrincipalId, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId:      uamiPrincipalId
    principalType:    'ServicePrincipal'
  }
}

// ── Outputs ──────────────────────────────────────────────────────────────────

@description('Resource ID of the Container Registry.')
output id string = containerRegistry.id

@description('Name of the Container Registry.')
output name string = containerRegistry.name

@description('Login server URL of the Container Registry (e.g. crsbsubdev.azurecr.io).')
output loginServer string = containerRegistry.properties.loginServer

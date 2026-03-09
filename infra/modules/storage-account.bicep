/*
  modules/storage-account.bicep
  Provisions a Storage Account for the Function App (AzureWebJobsStorage) and
  message payload storage, and grants the UAMI the required roles.
*/

param name                 string
param location             string
param uamiPrincipalId      string
param messageContainerName string = 'sb-messages'

// ── Storage Account ──────────────────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name:     name
  location: location
  kind:     'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier:             'Hot'
    allowBlobPublicAccess:  false
    minimumTlsVersion:      'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// ── Blob service & container ─────────────────────────────────────────────────

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name:   'default'
}

resource messageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name:   messageContainerName
  properties: {
    publicAccess: 'None'
  }
}

// ── RBAC: grant UAMI Storage Blob Data Contributor ───────────────────────────

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource blobContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(storageAccount.id, uamiPrincipalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId:      uamiPrincipalId
    principalType:    'ServicePrincipal'
  }
}

// ── RBAC: grant UAMI Storage Queue Data Contributor (AzureWebJobsStorage) ────

var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

resource queueContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(storageAccount.id, uamiPrincipalId, storageQueueDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId:      uamiPrincipalId
    principalType:    'ServicePrincipal'
  }
}

// ── RBAC: grant UAMI Storage Table Data Contributor (AzureWebJobsStorage) ────

var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource tableContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(storageAccount.id, uamiPrincipalId, storageTableDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId:      uamiPrincipalId
    principalType:    'ServicePrincipal'
  }
}

output id   string = storageAccount.id
output name string = storageAccount.name

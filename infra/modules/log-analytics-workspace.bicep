/*
  modules/log-analytics-workspace.bicep
  Provisions a Log Analytics workspace used as the backing store for
  Application Insights.
*/

param name     string
param location string

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name:     name
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

output id   string = logAnalyticsWorkspace.id
output name string = logAnalyticsWorkspace.name

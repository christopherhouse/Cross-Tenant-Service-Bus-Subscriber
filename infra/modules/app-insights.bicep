/*
  modules/app-insights.bicep
  Provisions an Application Insights component backed by a Log Analytics
  workspace.
*/

param name                    string
param location                string
param logAnalyticsWorkspaceId string

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name:     name
  location: location
  kind:     'web'
  properties: {
    Application_Type:             'web'
    WorkspaceResourceId:          logAnalyticsWorkspaceId
    IngestionMode:                'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery:     'Enabled'
  }
}

output id                 string = appInsights.id
output connectionString   string = appInsights.properties.ConnectionString
output instrumentationKey string = appInsights.properties.InstrumentationKey

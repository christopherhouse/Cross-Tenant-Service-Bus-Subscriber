/*
  modules/app-service-plan.bicep
  Provisions a Flex Consumption (Y1/Serverless) App Service Plan for the
  Azure Function App.
*/

param name     string
param location string

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name:     name
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true  // required for Linux
  }
}

output id   string = appServicePlan.id
output name string = appServicePlan.name

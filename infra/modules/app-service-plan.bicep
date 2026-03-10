/*
  modules/app-service-plan.bicep
  Provisions an Elastic Premium (EP1) App Service Plan for the Azure Function
  App.  EP1 is required when running containerised Functions pulled from ACR;
  the Consumption (Y1/Dynamic) plan does not support custom Docker containers.
*/

param name     string
param location string

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name:     name
  location: location
  sku: {
    name: 'EP1'
    tier: 'ElasticPremium'
  }
  properties: {
    reserved: true  // required for Linux
  }
}

output id   string = appServicePlan.id
output name string = appServicePlan.name

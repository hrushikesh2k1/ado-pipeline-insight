@description('Azure region for the dashboard web app')
param location string = resourceGroup().location
@description('Globally unique App Service name for the FastAPI + React application')
param dashboardAppName string
@description('App Service plan name')
param dashboardPlanName string = '${dashboardAppName}-plan'
@description('Existing Key Vault name used by the pipeline insight infrastructure')
param keyVaultName string
@description('Key Vault secret containing the Azure SQL connection string')
param sqlConnectionSecretName string = 'sql-connection-string'
@description('Existing Azure SQL server name')
param sqlServerName string
@description('Azure OpenAI endpoint')
param azureOpenAiEndpoint string
@description('Azure OpenAI deployment name')
param azureOpenAiDeployment string
@description('Resource ID of the Azure OpenAI account used by the dashboard')
param azureOpenAiResourceId string

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' existing = {
  name: sqlServerName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: dashboardPlanName
  location: location
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

resource dashboardApp 'Microsoft.Web/sites@2023-12-01' = {
  name: dashboardAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      alwaysOn: true
      appCommandLine: 'uvicorn backend.app.main:app --host 0.0.0.0 --port 8000'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'SQL_CONNECTION_STRING'
          value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/${sqlConnectionSecretName})'
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: azureOpenAiEndpoint
        }
        {
          name: 'AZURE_OPENAI_DEPLOYMENT'
          value: azureOpenAiDeployment
        }
        {
          name: 'AZURE_OPENAI_API_VERSION'
          value: '2024-10-21'
        }
        {
          name: 'CORS_ORIGINS'
          value: 'https://${dashboardAppName}.azurewebsites.net'
        }
        {
          name: 'MIN_HISTORY_RUNS'
          value: '5'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ]
    }
  }
}

resource dashboardSqlFirewallRules 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = [for ip in split(dashboardApp.properties.outboundIpAddresses, ','): {
  name: 'Dashboard-${replace(ip, '.', '-')}'
  parent: sqlServer
  properties: {
    startIpAddress: ip
    endIpAddress: ip
  }
}]

resource keyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, dashboardApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    principalId: dashboardApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource openAiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureOpenAiResourceId, dashboardApp.id, 'Cognitive Services OpenAI User')
  scope: resource(azureOpenAiResourceId, 'Microsoft.CognitiveServices/accounts@2023-05-01')
  properties: {
    principalId: dashboardApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

output dashboardUrl string = 'https://${dashboardApp.properties.defaultHostName}'
output dashboardPrincipalId string = dashboardApp.identity.principalId
output dashboardOutboundIpAddresses string = dashboardApp.properties.outboundIpAddresses

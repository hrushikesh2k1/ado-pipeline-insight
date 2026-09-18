@description('Deployment location')
param location string = resourceGroup().location
@description('Globally unique Function App name')
param functionAppName string
@description('Globally unique Key Vault name')
param keyVaultName string
@description('Globally unique SQL Server name')
param sqlServerName string
param sqlDatabaseName string = 'ado-pipeline-insight'
param sqlAdministratorLogin string
@secure()
param sqlAdministratorPassword string
@description('Existing Azure OpenAI endpoint, e.g. https://name.openai.azure.com/')
param azureOpenAiEndpoint string
param azureOpenAiDeployment string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: toLower(replace(functionAppName, '-', ''))
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
}
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${functionAppName}-insights'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
}
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  kind: 'functionapp'
}
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      cors: { allowedOrigins: [] }
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storage.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'KEY_VAULT_URL', value: keyVault.properties.vaultUri }
        { name: 'ADO_PAT_SECRET_NAME', value: 'ado-pat' }
          { name: 'SQL_CONNECTION_SECRET_NAME', value: sqlConnectionSecretName }
        { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: azureOpenAiDeployment }
      ]
    }
  }
}
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: { tenantId: subscription().tenantId, sku: { name: 'standard', family: 'A' }, enableRbacAuthorization: true, publicNetworkAccess: 'Enabled' }
}
resource secretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: { principalId: functionApp.identity.principalId, roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6'), principalType: 'ServicePrincipal' }
}
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  properties: { administratorLogin: sqlAdministratorLogin, administratorLoginPassword: sqlAdministratorPassword, publicNetworkAccess: 'Enabled', minimalTlsVersion: '1.2' }
}
resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: { name: 'Basic', tier: 'Basic' }
}
resource allowAzureServices 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output functionIdentityPrincipalId string = functionApp.identity.principalId
output keyVaultUri string = keyVault.properties.vaultUri
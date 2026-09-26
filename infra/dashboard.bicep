@description('Azure region for the dashboard web app')
param location string = resourceGroup().location
@description('Globally unique App Service name for the FastAPI + React application')
param dashboardAppName string
@description('App Service plan name')
param dashboardPlanName string = '${dashboardAppName}-plan'
@description('App Service plan SKU name')
param skuName string = 'B1'
@description('App Service plan SKU tier')
param skuTier string = 'Basic'
@description('Existing Key Vault name used by the pipeline insight infrastructure')
param keyVaultName string
@description('Key Vault secret containing the Azure SQL connection string')
param sqlConnectionSecretName string = 'sql-connection-string'
@description('Key Vault secret containing the authenticated ingestion Function URL')
param ingestFunctionSecretName string = 'ingest-function-url'
@description('Existing Azure SQL server name')
#disable-next-line no-unused-params
param sqlServerName string = ''
@description('Azure OpenAI endpoint')
param azureOpenAiEndpoint string
@description('Azure OpenAI deployment name')
param azureOpenAiDeployment string
@description('Key Vault secret containing the Azure OpenAI API key')
param azureOpenAiSecretName string = 'azure-openai-api-key'
@description('Name of the existing Azure OpenAI account')
param azureOpenAiAccountName string = 'openai2k1'
@description('Resource ID of the Azure OpenAI account used by the dashboard (optional if azureOpenAiAccountName is provided)')
param azureOpenAiResourceId string = ''
@description('Key Vault secret name containing Azure DevOps PAT')
param adoPatSecretName string = 'ado-pat-cicd-analysis'
@description('Key Vault secret template for organization-specific PATs')
#disable-next-line secure-secrets-in-params
param adoPatSecretTemplate string = 'ado-pat-{organization}'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

var openAiAccountNameResolved = !empty(azureOpenAiAccountName) ? azureOpenAiAccountName : last(split(azureOpenAiResourceId, '/'))

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openAiAccountNameResolved
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: dashboardPlanName
  location: location
  sku: {
    name: skuName
    tier: skuTier
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
      appCommandLine: 'python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
      healthCheckPath: '/api/v1/health'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'SQL_CONNECTION_STRING'
          value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/${sqlConnectionSecretName}/)'
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
          value: '2025-04-14'
        }
        {
          name: 'AZURE_OPENAI_API_KEY'
          value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/${azureOpenAiSecretName}/)'
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
          name: 'KEY_VAULT_URL'
          value: keyVault.properties.vaultUri
        }
        {
          name: 'ADO_PAT_SECRET_NAME'
          value: adoPatSecretName
        }
        {
          name: 'ADO_PAT_SECRET_TEMPLATE'
          value: adoPatSecretTemplate
        }
        {
          name: 'INGEST_FUNCTION_URL'
          value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/${ingestFunctionSecretName}/)'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ]
    }
  }
}

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
  name: guid(openAiAccount.id, dashboardApp.id, 'Cognitive Services OpenAI User')
  scope: openAiAccount
  properties: {
    principalId: dashboardApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

output dashboardUrl string = 'https://${dashboardApp.properties.defaultHostName}'
output dashboardPrincipalId string = dashboardApp.identity.principalId
output dashboardPlanId string = plan.id

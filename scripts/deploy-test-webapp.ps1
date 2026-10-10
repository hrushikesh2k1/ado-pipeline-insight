param([string]$ZipPath = "$env:USERPROFILE\Downloads\webapp-deploy.zip")
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw "ZIP not found: $ZipPath. Download webapp-deploy.zip first or pass -ZipPath with its actual location."
}
$ZipPath = (Resolve-Path -LiteralPath $ZipPath).Path
$resourceGroup = 'rg-ado-pipeline-insight-test'
$appName = 'app-ado-pipeline-insight-test'
az account show --output none
if ($LASTEXITCODE -ne 0) { throw 'Run az login and select the correct subscription first.' }
$settingsJson = az webapp config appsettings list --resource-group $resourceGroup --name $appName --output json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read web app settings.' }
$settings = $settingsJson | ConvertFrom-Json
$changes = @('SCM_DO_BUILD_DURING_DEPLOYMENT=true')
if (-not ($settings | Where-Object { $_.name -eq 'PLANNING_LINK_SECRET' -and $_.value })) {
    $secretBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($secretBytes) } finally { $rng.Dispose() }
    $changes += "PLANNING_LINK_SECRET=$([Convert]::ToBase64String($secretBytes))"
}
if (-not ($settings | Where-Object { $_.name -in @('REPORT_STORAGE_ACCOUNT_URL', 'REPORT_STORAGE_DIR') -and $_.value })) {
    $changes += 'REPORT_STORAGE_DIR=/home/data/planning-reports'
    $changes += 'WEBSITES_ENABLE_APP_SERVICE_STORAGE=true'
}
az webapp config appsettings set --resource-group $resourceGroup --name $appName --settings @changes --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to configure app settings.' }
az webapp deploy --resource-group $resourceGroup --name $appName --src-path $ZipPath --type zip
if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. Review the Azure deployment output.' }

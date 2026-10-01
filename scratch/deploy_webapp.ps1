$ErrorActionPreference = "Stop"
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls13

$root = "c:\Users\hboora\Repos\ado-pipeline-insight-plug-and-play"
$publishXmlPath = Join-Path $root "publish.xml"
$zipPath = Join-Path $root "webapp-deploy.zip"

if (-not (Test-Path $publishXmlPath)) {
    throw "publish.xml not found at $publishXmlPath"
}

if (-not (Test-Path $zipPath)) {
    throw "webapp-deploy.zip not found at $zipPath"
}

Write-Host "Reading publish profile from publish.xml..."
[xml]$xml = Get-Content -Path $publishXmlPath -Raw
$profile = $xml.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" -or $_.publishMethod -eq "MSDeploy" } | Select-Object -First 1

if (-not $profile) {
    throw "Could not find ZipDeploy or MSDeploy profile in publish.xml"
}

$rawUrl = $profile.publishUrl
$hostOnly = ($rawUrl -split ':')[0]
$deployUrl = "https://${hostOnly}/api/zipdeploy"

$user = $profile.userName
$pass = $profile.userPWD
$authBytes = [System.Text.Encoding]::ASCII.GetBytes("${user}:${pass}")
$base64 = [System.Convert]::ToBase64String($authBytes)

Write-Host "Target: $deployUrl"
Write-Host "Package: $zipPath ($( [math]::Round((Get-Item $zipPath).Length / 1KB, 1) ) KB)"
Write-Host "Initiating Kudu ZipDeploy..."

$headers = @{
    Authorization = "Basic $base64"
}

$response = Invoke-RestMethod -Uri $deployUrl -Method Post -InFile $zipPath -ContentType "application/zip" -Headers $headers -TimeoutSec 300

Write-Host "Deployment completed successfully!"
Write-Host "App URL: $($profile.destinationAppUrl)"

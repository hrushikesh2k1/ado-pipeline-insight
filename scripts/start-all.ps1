$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')

Write-Host 'Start the Azure Function in one terminal: .\scripts\start-function.ps1'
Write-Host 'Start FastAPI in another terminal: .\scripts\start-backend.ps1'
Write-Host 'Start React in a third terminal: .\scripts\start-frontend.ps1'
Write-Host ''
Write-Host 'Before starting, set INGEST_FUNCTION_URL in .env to the Function endpoint.'

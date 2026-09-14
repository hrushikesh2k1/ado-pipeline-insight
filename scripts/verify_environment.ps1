$ErrorActionPreference = 'Stop'

Write-Host 'Checking required local tools...'
python --version
node --version
npm --version

if (-not $env:INGEST_FUNCTION_URL) {
    Write-Warning 'INGEST_FUNCTION_URL is not set. FastAPI /api/v1/ado/ingest will return 503.'
} else {
    Write-Host "INGEST_FUNCTION_URL is configured."
}

Write-Host 'Environment check completed.'

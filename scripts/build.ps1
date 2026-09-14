$ErrorActionPreference = 'Stop'
Set-Location frontend
if (-not (Test-Path 'node_modules')) { npm install }
npm run build
Set-Location ..
python -m compileall -q backend core functions function_app.py
Write-Host 'Build validation completed.'

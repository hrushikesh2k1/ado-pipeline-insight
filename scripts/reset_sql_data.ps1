$ErrorActionPreference = 'Stop'

if (-not $env:SQL_CONNECTION_STRING) {
    throw 'SQL_CONNECTION_STRING is not set. Load your project .env first.'
}

Write-Host 'Open sql/reset_data.sql in Azure SQL Query Editor and execute it.'
Write-Host 'The script deletes application data only. It does not drop the schema.'

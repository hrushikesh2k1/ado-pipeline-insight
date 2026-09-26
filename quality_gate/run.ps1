# One-command runner (Windows). Creates .venv-quality on first use, then runs the gate and opens the report.
#   .\quality_gate\run.ps1            local run
#   .\quality_gate\run.ps1 --no-azure  code-only run (by default the live Azure apps are inspected when `az login` is active)
#   .\quality_gate\run.ps1 --ci       strict mode
# Native commands write to stderr on failure; with Windows PowerShell 5.1 that would abort the script,
# so errors are handled through exit codes instead of $ErrorActionPreference = "Stop".
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv-quality"
$py = Join-Path $venv "Scripts\python.exe"

function Fail($msg) { Write-Host $msg -ForegroundColor Red; exit 1 }

if (-not (Test-Path $py)) {
    Write-Host "First run: creating .venv-quality (Python 3.11)..." -ForegroundColor Cyan
    & py -3.11 -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
        & python -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Fail "Could not create a virtual environment. Install Python 3.11 and retry." }
    }
}

$check = "import bandit, ruff, radon, pytest_cov, pip_audit, vulture, mypy, azure.functions, fastapi, pyodbc, pymssql, httpx"
& $py -c $check *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing tools and app dependencies (one-time, a few minutes)..." -ForegroundColor Cyan
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r (Join-Path $root "requirements.txt") -r (Join-Path $root "functions\requirements.txt") -r (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see messages above). Fix the error, then re-run." }
}

& $py (Join-Path $PSScriptRoot "run_all.py") --open @args
exit $LASTEXITCODE

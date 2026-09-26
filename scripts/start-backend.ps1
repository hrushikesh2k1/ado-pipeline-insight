$ErrorActionPreference = 'Stop'
if (-not (Test-Path '.venv\Scripts\python.exe')) {
  python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

#!/usr/bin/env bash
# One-command runner (Linux/macOS/CI). Usage: ./quality_gate/run.sh [--azure] [--ci]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-quality"
PY="$VENV/bin/python"
[ -x "$PY" ] || python3.11 -m venv "$VENV" || python3 -m venv "$VENV"
if ! "$PY" -c "import bandit, ruff, radon, pytest_cov, pip_audit, azure.functions, fastapi" 2>/dev/null; then
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$ROOT/requirements.txt" -r "$ROOT/functions/requirements.txt" -r "$ROOT/quality_gate/requirements.txt"
fi
exec "$PY" "$ROOT/quality_gate/run_all.py" "$@"

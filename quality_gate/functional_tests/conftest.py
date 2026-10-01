"""Fixtures for the live-data functional tests.

These tests are READ-ONLY. They call GET endpoints of the deployed API and, when credentials are available, run SELECT
statements against the database to prove the numbers the dashboard shows are the numbers in the data.

Configuration (all optional):
  QG_BASE_URL              deployed site (default: [functional].base_url in quality_gate.toml)
  QG_BEARER_TOKEN          bearer token when the site sits behind App Service Authentication
  QG_SQL_CONNECTION_STRING direct database access for the reconciliation tests (else SQL_CONNECTION_STRING, else Key Vault
                           via QG_KEY_VAULT_URL / KEY_VAULT_URL and your `az login`); tests skip when none is available
"""
from __future__ import annotations

import math
import os
import sys
import tomllib
from pathlib import Path

import pytest
import requests

GATE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GATE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CFG = tomllib.loads((GATE_DIR / "quality_gate.toml").read_text(encoding="utf-8"))
BASE_URL = (os.environ.get("QG_BASE_URL") or CFG["functional"]["base_url"]).rstrip("/")
WINDOW_DAYS = int(CFG["functional"].get("window_days", 90))
ALLOWED_RESULTS = {"succeeded", "partiallySucceeded", "failed", "canceled", "abandoned", None}


def pytest_configure(config):
    config.addinivalue_line("markers", "func(severity, area, title, fix): metadata shown in the HTML functional report")


@pytest.fixture(autouse=True)
def _record_metadata(request, record_property):
    marker = request.node.get_closest_marker("func")
    if marker:
        for key, value in marker.kwargs.items():
            record_property(key, value)


class Api:
    def __init__(self):
        self.session = requests.Session()
        token = os.environ.get("QG_BEARER_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def raw(self, path: str, **kw):
        return self.session.get(f"{BASE_URL}{path}", timeout=60, allow_redirects=False, **kw)

    def get(self, path: str, **params):
        r = self.raw(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


@pytest.fixture(scope="session")
def api() -> Api:
    client = Api()
    try:
        probe = client.raw("/api/v1/health")
    except requests.RequestException as exc:
        pytest.skip(f"cannot reach {BASE_URL}: {type(exc).__name__}")
    if probe.status_code in (301, 302, 303, 307, 308, 401, 403):
        pytest.skip(f"{BASE_URL} requires sign-in (HTTP {probe.status_code}); set QG_BEARER_TOKEN to test it")
    return client


def _snapshot(api: Api, days: int) -> dict:
    runs, page = [], 1
    while True:
        chunk = api.get("/api/v1/runs", days=days, page=page, page_size=1000)
        runs.extend(chunk["items"])
        if page >= chunk["total_pages"]:
            break
        page += 1
    return {"days": days, "runs": runs, "total_count": chunk["total_count"], "summary": api.get("/api/v1/summary", days=days),
            "trends": api.get("/api/v1/trends", days=days), "options": api.get("/api/v1/options")}


@pytest.fixture(scope="session")
def data(api) -> dict:
    """A consistent snapshot of every list endpoint for one window (retried if a pipeline run lands mid-fetch)."""
    for _ in range(3):
        snap = _snapshot(api, WINDOW_DAYS)
        if api.get("/api/v1/runs", days=WINDOW_DAYS, page=1, page_size=1)["total_count"] == snap["total_count"]:
            break
    if snap["total_count"] == 0:
        pytest.skip(f"no runs in the last {WINDOW_DAYS} days; nothing to verify")
    if snap["total_count"] > 20000:
        pytest.skip("more than 20,000 runs in the window; narrow window_days in quality_gate.toml")
    return snap


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (pos - low), 2)


def finished(runs):
    return [r for r in runs if r["start_time"] and r["finish_time"]]


def pages(total, size):
    return max(1, math.ceil(total / size))


def _connection_string() -> str | None:
    direct = os.environ.get("QG_SQL_CONNECTION_STRING") or os.environ.get("SQL_CONNECTION_STRING")
    if direct and not direct.startswith("@Microsoft.KeyVault("):
        return direct
    vault = os.environ.get("QG_KEY_VAULT_URL") or os.environ.get("KEY_VAULT_URL") or CFG["functional"].get("key_vault_url")
    if not vault:
        return None
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    name = os.environ.get("SQL_CONNECTION_SECRET_NAME", "sql-connection-string")
    return SecretClient(vault_url=vault, credential=DefaultAzureCredential()).get_secret(name).value


class ReadOnlyDb:
    def __init__(self, connection):
        self.connection = connection

    def query(self, sql: str, *params):
        assert sql.lstrip().upper().startswith("SELECT"), "functional tests may only run SELECT statements"
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def scalar(self, sql: str, *params):
        return next(iter(self.query(sql, *params)[0].values()))


@pytest.fixture(scope="session")
def db():
    try:
        connection_string = _connection_string()
    except Exception as exc:
        pytest.skip(f"database credentials unavailable ({type(exc).__name__}); set QG_SQL_CONNECTION_STRING to run reconciliation")
    if not connection_string:
        pytest.skip("no database credentials (set QG_SQL_CONNECTION_STRING or QG_KEY_VAULT_URL) - reconciliation against the database was NOT run")
    from core.db import AlertRepository

    try:
        connection = AlertRepository(connection_string)._connect()
    except Exception as exc:
        pytest.skip(f"cannot connect to the database ({type(exc).__name__}); check the SQL firewall for your IP")
    yield ReadOnlyDb(connection)
    connection.close()

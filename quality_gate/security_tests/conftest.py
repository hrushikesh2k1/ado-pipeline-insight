"""Shared fixtures for the attack-simulation tests.

Safety rules enforced here so the suite can never touch real infrastructure:
  * dummy environment values override anything in a local .env file
  * every outbound socket connection is blocked
  * the SQL connection factory raises if a test forgets to mock the database
"""
from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOOD_ORIGIN = "https://good.example.test"
EVIL_ORIGIN = "https://evil.example.test"

for _key, _value in {
    "SQL_CONNECTION_STRING": "",
    "AZURE_OPENAI_API_KEY": "",
    "AZURE_OPENAI_ENDPOINT": "",
    "AZURE_OPENAI_DEPLOYMENT": "",
    "KEY_VAULT_URL": "",
    "ADO_PAT": "server-side-pat-that-must-never-be-used",
    "INGEST_FUNCTION_URL": "",
    "CORS_ORIGINS": GOOD_ORIGIN,
}.items():
    os.environ[_key] = _value
for _key in ("REQUIRE_EASY_AUTH", "ENABLE_API_DOCS", "ALLOWED_ADO_ORGS"):
    os.environ.pop(_key, None)


def pytest_configure(config):
    config.addinivalue_line("markers", "sec(severity, area, title, fix): metadata shown in the HTML security report")


@pytest.fixture(autouse=True)
def _record_security_metadata(request, record_property):
    marker = request.node.get_closest_marker("sec")
    if marker:
        for key, value in marker.kwargs.items():
            record_property(key, value)


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    loopback = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}  # asyncio's socketpair on Windows connects over loopback

    def _host(address):
        return address[0] if isinstance(address, tuple) else address

    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def _connect(self, address, *a, **k):
        if _host(address) not in loopback:
            raise AssertionError(f"network access to {address!r} attempted during a security test")
        return real_connect(self, address, *a, **k)

    def _connect_ex(self, address, *a, **k):
        if _host(address) not in loopback:
            raise AssertionError(f"network access to {address!r} attempted during a security test")
        return real_connect_ex(self, address, *a, **k)

    def _getaddrinfo(host, *a, **k):
        if host not in loopback and host not in (None, ""):
            raise AssertionError(f"DNS lookup for {host!r} attempted during a security test")
        return real_getaddrinfo(host, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    import app.api.routes as routes
    import app.core.db as app_db

    monkeypatch.setattr(routes, "_get_state_file_path", lambda: tmp_path / "ado_ingestion_state.json")
    monkeypatch.setattr(routes, "_ingestion_jobs", {})

    def _no_db(*_a, **_k):
        raise RuntimeError("database access attempted without a mock")

    monkeypatch.setattr(app_db, "get_connection", _no_db)


@pytest.fixture
def make_app(monkeypatch):
    """Build the FastAPI app with specific environment variables (falls back to the module-level app on old code)."""

    def _make(**env):
        for key in ("REQUIRE_EASY_AUTH", "ENABLE_API_DOCS", "ALLOWED_ADO_ORGS"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("CORS_ORIGINS", env.pop("CORS_ORIGINS", GOOD_ORIGIN))
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        import app.core.config as cfg

        cfg.get_settings.cache_clear()
        main = importlib.import_module("app.main")
        factory = getattr(main, "create_app", None)
        return factory() if factory else main.app

    yield _make
    import app.core.config as cfg

    cfg.get_settings.cache_clear()


@pytest.fixture
def client(make_app):
    from fastapi.testclient import TestClient

    return TestClient(make_app(), raise_server_exceptions=False)


@pytest.fixture
def sql_log(monkeypatch):
    """Capture every SQL statement + bound parameters issued by the repository layer."""
    calls: list[tuple[str, tuple]] = []

    def _fetch_all(query, params=()):
        calls.append((query, tuple(params)))
        return []

    def _fetch_one(query, params=()):
        calls.append((query, tuple(params)))
        return {"total": 0, "ok": 1}

    import app.api.routes as routes
    import app.repositories.pipeline_repository as repo

    monkeypatch.setattr(repo, "fetch_all", _fetch_all)
    monkeypatch.setattr(repo, "fetch_one", _fetch_one)
    monkeypatch.setattr(routes, "fetch_one", _fetch_one)
    return calls

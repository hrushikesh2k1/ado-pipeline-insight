"""Information disclosure, security headers, CORS, API docs exposure, authentication and secret handling."""
from __future__ import annotations

import logging

import pytest

from conftest import EVIL_ORIGIN, GOOD_ORIGIN

SECRET_MARKER = "Sup3rS3cretPassw0rd"
LEAKY_ERROR = f"Login failed for user 'sqladmin'. Server=prod-sql.database.usgovcloudapi.net;Password={SECRET_MARKER}"

GET_ENDPOINTS = [
    "/api/v1/health", "/api/v1/options", "/api/v1/summary", "/api/v1/trends", "/api/v1/runs",
    "/api/v1/runs/1/timeline", "/api/v1/runs/1/logs", "/api/v1/pipelines/1/recommendations", "/api/v1/pools",
]


@pytest.fixture
def exploding_db(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError(LEAKY_ERROR)

    import app.api.routes as routes
    import app.repositories.pipeline_repository as repo

    for mod in (repo, routes):
        for name in ("fetch_all", "fetch_one"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, boom)


@pytest.mark.sec(severity="high", area="Information disclosure", title="Database errors never expose connection details to the client",
                 fix="Log the exception server-side and return a generic message (e.g. 'Service temporarily unavailable').")
@pytest.mark.parametrize("url", GET_ENDPOINTS)
def test_internal_errors_are_not_leaked(client, exploding_db, url):
    r = client.get(url)
    assert SECRET_MARKER not in r.text and "usgovcloudapi" not in r.text and "sqladmin" not in r.text, f"leaked: {r.text[:200]}"


@pytest.mark.sec(severity="high", area="Information disclosure", title="AI-analysis and ingestion errors are not leaked",
                 fix="Return generic error text from analyze/connect/ingest handlers.")
def test_write_endpoint_errors_are_not_leaked(client, monkeypatch):
    import app.api.routes as routes

    def boom(*_a, **_k):
        raise RuntimeError(LEAKY_ERROR)

    monkeypatch.setattr(routes.ai_service, "analyze", boom)
    monkeypatch.setattr(routes, "AzureDevOpsClient", boom)
    for r in (client.post("/api/v1/pipelines/1/analyze", json={"months": 3}),
              client.post("/api/v1/ado/connect", json={"organization": "myorg", "pat": "abcdef1234567890"})):
        assert SECRET_MARKER not in r.text and "sqladmin" not in r.text, f"leaked: {r.text[:200]}"


@pytest.mark.sec(severity="high", area="Secret handling", title="A submitted PAT is never logged or echoed back",
                 fix="Never include request bodies or PATs in log messages or error responses.")
def test_pat_is_not_logged_or_echoed(client, monkeypatch, caplog):
    import app.api.routes as routes

    pat = "PATVALUE0123456789abcdefghijklmnop"

    class Failing:
        def __init__(self, org, token, *a, **k):
            raise RuntimeError(f"cannot connect with {token}")

    monkeypatch.setattr(routes, "AzureDevOpsClient", Failing)
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/v1/ado/connect", json={"organization": "myorg", "pat": pat})
    assert pat not in r.text
    assert pat not in caplog.text


@pytest.mark.sec(severity="medium", area="Security headers", title="Responses carry hardening headers",
                 fix="Add a middleware that sets X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Strict-Transport-Security.")
@pytest.mark.parametrize("url", ["/", "/api/v1/health"])
def test_security_headers_present(client, sql_log, url):
    h = {k.lower(): v for k, v in client.get(url).headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options", "").upper() in ("DENY", "SAMEORIGIN")
    assert "referrer-policy" in h
    assert "max-age" in h.get("strict-transport-security", "")


@pytest.mark.sec(severity="medium", area="Caching", title="API responses are marked non-cacheable",
                 fix="Set Cache-Control: no-store on /api/ responses so proxies and browsers never keep pipeline data.")
def test_api_responses_not_cacheable(client, sql_log):
    assert "no-store" in client.get("/api/v1/summary").headers.get("cache-control", "")


@pytest.mark.sec(severity="medium", area="Attack surface", title="Interactive API docs and OpenAPI schema are off by default",
                 fix="Create FastAPI with docs_url=None/redoc_url=None/openapi_url=None unless ENABLE_API_DOCS=true.")
@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_hidden_by_default(client, url):
    assert client.get(url).status_code == 404


@pytest.mark.sec(severity="low", area="Attack surface", title="API docs can be re-enabled explicitly for development",
                 fix="Honour ENABLE_API_DOCS=true.")
def test_api_docs_can_be_enabled(make_app):
    from fastapi.testclient import TestClient

    assert TestClient(make_app(ENABLE_API_DOCS="true")).get("/docs").status_code == 200


def _preflight(client, origin, method="GET"):
    return client.options("/api/v1/summary", headers={"Origin": origin, "Access-Control-Request-Method": method})


@pytest.mark.sec(severity="high", area="CORS", title="Untrusted origins receive no CORS approval",
                 fix="Restrict CORS_ORIGINS to explicit trusted origins.")
def test_cors_blocks_unknown_origin(client):
    assert "access-control-allow-origin" not in {k.lower() for k in _preflight(client, EVIL_ORIGIN).headers}


@pytest.mark.sec(severity="high", area="CORS", title="A wildcard CORS_ORIGINS setting is ignored",
                 fix="Drop '*' from the origin list when building the middleware.")
def test_cors_wildcard_config_is_ignored(make_app):
    from fastapi.testclient import TestClient

    c = TestClient(make_app(CORS_ORIGINS="*"))
    assert "access-control-allow-origin" not in {k.lower() for k in _preflight(c, EVIL_ORIGIN).headers}


@pytest.mark.sec(severity="medium", area="CORS", title="Only the HTTP methods the UI needs are allowed cross-origin",
                 fix="Set allow_methods=['GET','POST','OPTIONS'] instead of '*'.")
@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_cors_limits_methods(client, method):
    r = _preflight(client, GOOD_ORIGIN, method)
    allowed = r.headers.get("access-control-allow-methods", "")
    assert r.status_code >= 400 or method not in allowed


@pytest.mark.sec(severity="medium", area="CORS", title="Cross-origin credentials are not allowed",
                 fix="Set allow_credentials=False; the API uses no cookies.")
def test_cors_credentials_disabled(client):
    assert _preflight(client, GOOD_ORIGIN).headers.get("access-control-allow-credentials", "").lower() != "true"


PROTECTED = [("post", "/api/v1/ado/ingest", {"organization": "myorg", "project": "p", "pipeline_id": 1, "pat": "abcdef1234567890"}),
             ("post", "/api/v1/ado/connect", {"organization": "myorg", "pat": "abcdef1234567890"}),
             ("post", "/api/v1/pipelines/1/analyze", {"months": 3}),
             ("get", "/api/v1/options", None), ("get", "/api/v1/runs", None), ("get", "/api/v1/ado/ingest/status", None)]


@pytest.mark.sec(severity="critical", area="Authentication", title="With REQUIRE_EASY_AUTH=true, anonymous requests are rejected",
                 fix="Add middleware that returns 401 for /api/ requests lacking the App Service Easy Auth principal header.")
@pytest.mark.parametrize("method,url,body", PROTECTED)
def test_anonymous_requests_rejected_when_auth_required(make_app, sql_log, monkeypatch, method, url, body):
    from fastapi.testclient import TestClient

    import app.api.routes as routes

    class Stub:
        def __init__(self, *a, **k):
            pass

        def list_projects(self):
            return []

        def list_pipelines(self, _project):
            return []

    monkeypatch.setattr(routes, "AzureDevOpsClient", Stub)
    monkeypatch.setattr(routes, "_run_historical_ingestion", lambda *a, **k: None)
    monkeypatch.setattr(routes, "get_ado_pat", lambda org=None: "server-pat")
    c = TestClient(make_app(REQUIRE_EASY_AUTH="true"), raise_server_exceptions=False)
    r = getattr(c, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401, f"{method.upper()} {url} answered {r.status_code} to an anonymous caller"


@pytest.mark.sec(severity="medium", area="Authentication", title="Authenticated callers and the health probe are still served when auth is required",
                 fix="Exempt /api/v1/health (App Service probe) and accept requests carrying X-MS-CLIENT-PRINCIPAL-ID.")
def test_authenticated_and_health_requests_pass_auth_gate(make_app, sql_log):
    from fastapi.testclient import TestClient

    c = TestClient(make_app(REQUIRE_EASY_AUTH="true"), raise_server_exceptions=False)
    assert c.get("/api/v1/health").status_code != 401
    assert c.get("/api/v1/options", headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-1"}).status_code != 401


@pytest.mark.sec(severity="high", area="Authorization", title="The server-side Azure DevOps PAT cannot be used for organizations outside the allow-list",
                 fix="With ALLOWED_ADO_ORGS set, refuse requests (403) that omit a PAT for organizations not on the list.")
def test_server_pat_not_used_for_unlisted_org(make_app, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.routes as routes

    used = []
    monkeypatch.setattr(routes, "get_ado_pat", lambda org=None: used.append(org) or "server-pat")

    class Spy:
        def __init__(self, *a, **k):
            used.append("client")

        def list_projects(self):
            return []

    monkeypatch.setattr(routes, "AzureDevOpsClient", Spy)
    c = TestClient(make_app(ALLOWED_ADO_ORGS="trusted-org"), raise_server_exceptions=False)
    r = c.post("/api/v1/ado/connect", json={"organization": "victim-org"})
    assert r.status_code == 403 and not used, f"status={r.status_code}; server PAT used for: {used}"

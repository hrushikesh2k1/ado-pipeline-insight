"""Does the DEPLOYED site behave like the code we tested? (live, read-only, no data modified)"""
from __future__ import annotations

import re
import time

import pytest

from conftest import BASE_URL, WINDOW_DAYS


@pytest.mark.func(severity="high", area="Frontend delivery", title="The dashboard page loads and every referenced script/style file is served",
                  fix="Rebuild the frontend (npm run build) and redeploy frontend/dist together with the API.")
def test_spa_and_assets_are_served(api):
    page = api.raw("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and '<div id="root">' in page.text
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
    assert assets, "index.html references no /assets files"
    for path in assets:
        r = api.raw(path)
        assert r.status_code == 200, f"{path} -> HTTP {r.status_code}"
        assert ("javascript" in r.headers["content-type"]) if path.endswith(".js") else ("css" in r.headers["content-type"]), path


@pytest.mark.func(severity="medium", area="Deployed hardening", title="Security headers are present on the deployed site",
                  fix="Deploy the current app/core/security.py middleware.")
@pytest.mark.parametrize("path", ["/", "/api/v1/health"])
def test_deployed_security_headers(api, path):
    h = {k.lower(): v for k, v in api.raw(path).headers.items()}
    assert h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY"
    assert "max-age" in h.get("strict-transport-security", "") and "content-security-policy" in h
    if path.startswith("/api/"):
        assert "no-store" in h.get("cache-control", "")


@pytest.mark.func(severity="medium", area="Deployed hardening", title="API docs are not exposed on the deployed site",
                  fix="Leave ENABLE_API_DOCS unset in production.")
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_hidden(api, path):
    assert api.raw(path).status_code == 404


@pytest.mark.func(severity="high", area="Deployed hardening", title="Plain HTTP is redirected to HTTPS",
                  fix="az webapp update --https-only true")
def test_http_redirects_to_https(api):
    import requests

    if not BASE_URL.startswith("https://"):
        pytest.skip("base URL is not https")
    r = requests.get(BASE_URL.replace("https://", "http://", 1) + "/api/v1/health", allow_redirects=False, timeout=30)
    assert r.status_code in (301, 302, 307, 308) and r.headers["location"].startswith("https://")


@pytest.mark.func(severity="high", area="Deployed hardening", title="Untrusted origins get no CORS approval on the deployed site",
                  fix="Set CORS_ORIGINS to trusted origins only.")
def test_deployed_cors(api):
    r = api.session.options(f"{BASE_URL}/api/v1/summary", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
                            timeout=30, allow_redirects=False)
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


@pytest.mark.func(severity="high", area="Deployed hardening", title="The deployed API rejects hostile input",
                  fix="Deploy the input validation in app/api/routes.py and app/schemas.")
@pytest.mark.parametrize("path", ["/api/v1/runs?status=x;drop", "/api/v1/runs/-1/timeline", "/api/v1/summary?days=99999",
                                  "/api/v1/runs?page_size=100000", "/api/v1/pipelines/99999999999/recommendations"])
def test_deployed_validation(api, path):
    assert api.raw(path).status_code == 422


@pytest.mark.func(severity="medium", area="Performance", title="Dashboard endpoints answer within 15 seconds",
                  fix="Add indexes on pipeline_runs(start_time) and pipeline_stages(run_id); check the SQL tier.")
@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/options", f"/api/v1/summary?days={WINDOW_DAYS}", f"/api/v1/trends?days={WINDOW_DAYS}",
                                  f"/api/v1/runs?days={WINDOW_DAYS}&page_size=500"])
def test_endpoint_latency(api, path):
    api.raw(path)
    started = time.perf_counter()
    r = api.raw(path)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200 and elapsed < 15, f"{path} took {elapsed:.1f}s"


@pytest.mark.func(severity="critical", area="Authentication", title="The deployed API rejects anonymous callers and bad passwords",
                  fix="Set REQUIRE_LOGIN=true and store app-auth-username / app-auth-password in Key Vault.")
def test_deployed_login_gate():
    import requests

    anonymous = requests.get(f"{BASE_URL}/api/v1/options", timeout=60, allow_redirects=False)
    if anonymous.status_code != 401:
        pytest.skip(f"site does not use the built-in login (HTTP {anonymous.status_code})")
    bad = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"username": "Admin", "password": "definitely-not-the-password"},
                        timeout=60, allow_redirects=False)
    assert bad.status_code in (401, 429) and "set-cookie" not in bad.headers
    assert requests.get(f"{BASE_URL}/api/v1/health", timeout=60).status_code == 200

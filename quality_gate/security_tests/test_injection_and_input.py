"""SQL injection, path/URL injection and input-validation attacks."""
from __future__ import annotations

from urllib.parse import quote

import pytest

SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE dbo.pipeline_runs;--",
    "1; WAITFOR DELAY '0:0:10'--",
    "\" UNION SELECT name,password FROM sys.sql_logins--",
    "%27%20OR%201%3D1--",
    "\x00' OR 1=1",
]

READ_ENDPOINTS = [
    "/api/v1/summary?pipeline_id=1&days={p}",
    "/api/v1/trends?pipeline_id=1&days={p}",
    "/api/v1/runs?status={p}",
    "/api/v1/runs?status={p}&pipeline_id={p}&days={p}&page={p}&page_size={p}",
    "/api/v1/pools?days={p}",
    "/api/v1/pipelines/{p}/recommendations",
    "/api/v1/runs/{p}/timeline",
    "/api/v1/runs/{p}/analysis",
    "/api/v1/runs/{p}/logs",
]


@pytest.mark.sec(severity="critical", area="SQL injection", title="SQL injection payloads never reach the SQL text",
                 fix="Bind every user value with ? placeholders; never format user input into SQL.")
@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
@pytest.mark.parametrize("template", READ_ENDPOINTS)
def test_user_input_is_never_concatenated_into_sql(client, sql_log, template, payload):
    client.get(template.format(p=quote(payload, safe="")))
    for query, _params in sql_log:
        assert payload not in query, f"payload appeared inside the SQL text: {query[:120]}"


@pytest.mark.sec(severity="high", area="Input validation", title="Free-text 'status' filter is length/charset restricted",
                 fix="Constrain 'status' to a short alphanumeric pattern (Query(max_length=..., pattern=...)).")
@pytest.mark.parametrize("value", ["x" * 500, "a b; c", "<script>alert(1)</script>", "'; --"])
def test_status_filter_rejects_junk(client, sql_log, value):
    assert client.get("/api/v1/runs", params={"status": value}).status_code == 422


@pytest.mark.sec(severity="medium", area="Input validation", title="Numeric ids and paging are range-checked",
                 fix="Use Query/Path(ge=..., le=...) on every numeric parameter so oversized values return 422, not a 5xx.")
@pytest.mark.parametrize("url", [
    "/api/v1/runs?page=99999999999999",
    "/api/v1/runs?page_size=0",
    "/api/v1/runs?days=999999999",
    "/api/v1/runs?days=0",
    "/api/v1/runs?pipeline_id=-5",
    "/api/v1/runs?pipeline_id=99999999999999",
    "/api/v1/summary?pipeline_id=99999999999999",
    "/api/v1/runs/-1/timeline",
    "/api/v1/runs/99999999999999999999/timeline",
    "/api/v1/pipelines/99999999999999/recommendations",
])
def test_out_of_range_numbers_are_rejected(client, sql_log, url):
    assert client.get(url).status_code == 422, "out-of-range value was accepted and would reach the database"


BAD_ORGS = ["../../etc/passwd", "a/b", "a b", "evil.com/#", "org?x=1", "org#frag", "org\r\nX-Injected: 1", "org%2F..%2Fadmin", "a" * 300, "", "-leading-dash-"]
BAD_PROJECTS = ["../secret", "proj/../../other", "a?b", "a#b", "p\r\nHeader: x", "%2e%2e/x", "x" * 300]


@pytest.fixture
def ado_spy(monkeypatch):
    """Fail loudly if the API tries to talk to Azure DevOps with unvalidated input."""
    import app.api.routes as routes

    created = []

    class Spy:
        def __init__(self, organization, pat, *a, **k):
            created.append((organization, pat))
            raise AssertionError(f"AzureDevOpsClient was built with unvalidated organization={organization!r}")

    monkeypatch.setattr(routes, "AzureDevOpsClient", Spy)
    monkeypatch.setattr(routes, "get_ado_pat", lambda org=None: "server-pat")
    return created


@pytest.mark.sec(severity="high", area="URL/path injection", title="Organization name cannot inject into the Azure DevOps URL",
                 fix="Validate organization with a strict pattern in the request schema and URL-encode path segments in AzureDevOpsClient.")
@pytest.mark.parametrize("org", BAD_ORGS)
def test_connect_rejects_malicious_organization(client, ado_spy, org):
    r = client.post("/api/v1/ado/connect", json={"organization": org, "pat": "abcdef1234567890"})
    assert r.status_code == 422, f"organization {org!r} was accepted"


@pytest.mark.sec(severity="high", area="URL/path injection", title="Ingest rejects malicious organization/project names",
                 fix="Validate organization and project in AdoIngestRequest.")
@pytest.mark.parametrize("org,project", [(o, "proj") for o in BAD_ORGS[:6]] + [("myorg", p) for p in BAD_PROJECTS])
def test_ingest_rejects_malicious_names(client, ado_spy, org, project):
    r = client.post("/api/v1/ado/ingest", json={"organization": org, "project": project, "pipeline_id": 1, "pat": "abcdef1234567890"})
    assert r.status_code == 422, f"organization={org!r} project={project!r} was accepted"


@pytest.mark.sec(severity="medium", area="Header injection", title="PAT field rejects control characters and whitespace",
                 fix="Constrain 'pat' to printable, non-space ASCII.")
@pytest.mark.parametrize("pat", ["abc\r\nX-Evil: 1", "has space inside", "tab\there", "\x00nul"])
def test_pat_rejects_control_characters(client, ado_spy, pat):
    assert client.post("/api/v1/ado/connect", json={"organization": "myorg", "pat": pat}).status_code == 422


@pytest.mark.sec(severity="medium", area="Denial of service", title="Oversized request bodies are refused",
                 fix="Add a request-size limit middleware (e.g. 64 KB) so a client cannot post megabytes of JSON.")
def test_large_body_is_rejected(client, ado_spy):
    body = '{"organization":"myorg","pat":"abcdef1234567890","note":"' + "A" * 300_000 + '"}'
    r = client.post("/api/v1/ado/connect", content=body, headers={"content-type": "application/json"})
    assert r.status_code in (413, 422)


@pytest.mark.sec(severity="low", area="Input validation", title="Malformed JSON and wrong types return 4xx, never 5xx",
                 fix="Let pydantic validate all bodies.")
@pytest.mark.parametrize("body", ['{"organization": ', "[]", '{"organization": 5}', '{"organization":"x","pipeline_id":"abc","project":"p"}'])
def test_malformed_bodies_do_not_crash(client, ado_spy, body):
    r = client.post("/api/v1/ado/ingest", content=body, headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500


@pytest.mark.sec(severity="low", area="HTTP semantics", title="Unsafe HTTP methods are refused on read-only endpoints",
                 fix="Only declare the HTTP methods each route needs.")
@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_read_endpoints_reject_write_methods(client, sql_log, method):
    assert client.request(method, "/api/v1/summary").status_code == 405


@pytest.mark.sec(severity="high", area="URL/path injection", title="Azure DevOps client URL-encodes path segments and validates organization",
                 fix="Build URLs with urllib.parse.quote(segment, safe='') and reject bad organization names in __init__.")
def test_ado_client_encodes_url_segments():
    from core.ado_client import AzureDevOpsClient

    client = AzureDevOpsClient("myorg", "token")
    url = client._url("proj/../../other?x=1#frag", "_apis/build/builds")
    assert url.startswith("https://dev.azure.com/myorg/")
    tail = url[len("https://dev.azure.com/myorg/"):]
    assert "/../" not in tail and "?" not in tail and "#" not in tail, f"unencoded URL: {url}"
    with pytest.raises(ValueError):
        AzureDevOpsClient("evil.com/../x", "token")

"""Attack simulation against the Azure Functions entry points (webhook + ingestion)."""
from __future__ import annotations

import json

import pytest

func = pytest.importorskip("azure.functions")


def _request(body: dict | str, route: str = "ingest_run") -> "func.HttpRequest":
    raw = body if isinstance(body, str) else json.dumps(body)
    return func.HttpRequest(method="POST", url=f"/api/{route}", body=raw.encode(), headers={"content-type": "application/json"})


@pytest.fixture
def fa(monkeypatch):
    import function_app

    class Spy:
        built = []

        def __init__(self, organization, pat, *a, **k):
            Spy.built.append(organization)
            raise AssertionError(f"Azure DevOps client built for unvalidated organization {organization!r}")

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Spy)
    monkeypatch.setattr(function_app, "get_ado_pat", lambda org=None: "server-pat")
    return function_app


@pytest.mark.sec(severity="high", area="Function auth", title="Every function endpoint requires a function key",
                 fix="Create the app with http_auth_level=FUNCTION (never ANONYMOUS).")
def test_function_endpoints_require_key():
    import function_app

    try:
        levels = {str(f.get_trigger().auth_level) for f in function_app.app.get_functions()}
    except AttributeError:
        pytest.skip("this azure-functions version does not expose trigger auth levels")
    assert levels and all("FUNCTION" in lv or "ADMIN" in lv for lv in levels), levels


@pytest.mark.sec(severity="high", area="URL/path injection", title="Webhook payload cannot smuggle a malicious organization/project",
                 fix="Validate organization and project (core.validation) before building any Azure DevOps request.")
@pytest.mark.parametrize("org", ["../../evil", "a/b?x=1", "org\r\nX: 1", "x" * 300])
def test_webhook_rejects_malicious_organization(fa, org):
    r = fa.ingest_run(_request({"organization": org, "resource": {"id": 1, "project": {"name": "p"}}}))
    assert r.status_code == 400


@pytest.mark.sec(severity="high", area="URL/path injection", title="Historical ingestion rejects malicious organization/project",
                 fix="Validate organization and project in ingest_pipeline.")
@pytest.mark.parametrize("org,project", [("../../evil", "p"), ("myorg", "../x"), ("myorg", "a?b#c"), ("myorg", "p\r\nX: 1")])
def test_ingest_pipeline_rejects_malicious_names(fa, org, project):
    r = fa.ingest_pipeline(_request({"organization": org, "project": project, "pipeline_id": 1, "pat": "abcdef1234567890"}, "ingest_pipeline"))
    assert r.status_code == 400


@pytest.mark.sec(severity="medium", area="Denial of service", title="Ingestion bounds (days, max_runs) are enforced",
                 fix="Reject days outside 1..730 and clamp max_runs to a sane upper bound.")
@pytest.mark.parametrize("extra", [{"days": 10**9}, {"days": 0}, {"max_runs": 10**9}, {"max_runs": -1}])
def test_ingest_pipeline_bounds(fa, extra):
    body = {"organization": "myorg", "project": "p", "pipeline_id": 1, "pat": "abcdef1234567890", **extra}
    assert fa.ingest_pipeline(_request(body, "ingest_pipeline")).status_code == 400


@pytest.mark.sec(severity="low", area="Information disclosure", title="Malformed input produces generic errors without stack traces",
                 fix="Return short validation messages only.")
@pytest.mark.parametrize("body", ["not json", "[]", '{"organization": null}', "{}"])
def test_bad_payloads_are_handled(fa, body):
    for route, fn in (("ingest_run", fa.ingest_run), ("ingest_pipeline", fa.ingest_pipeline)):
        r = fn(_request(body, route))
        assert 400 <= r.status_code < 500
        assert "Traceback" not in r.get_body().decode()

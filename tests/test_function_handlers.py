import json
import pathlib
from types import SimpleNamespace

import azure.functions as func
import pytest
import requests

import function_app
from core.models import TimelineMetric

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _post(body, route="ingest_run"):
    return func.HttpRequest("POST", f"http://localhost/api/{route}", body=json.dumps(body).encode())


def _metrics(build_id=12, failed=False):
    return [TimelineMetric(run_id=build_id, pipeline_id=3, pipeline_name="CI", level="task", stage_name="Build", job_name="Job",
                           task_name="npm", result="failed" if failed else "succeeded", log_id=7 if failed else None)]


class Repo:
    saved: list = []

    def __init__(self, _cs):
        pass

    def upsert_metrics(self, metrics):
        Repo.saved = list(metrics)


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    Repo.saved = []
    monkeypatch.setattr(function_app, "get_settings", lambda: SimpleNamespace(sql_connection_string="x", min_history_runs=5))
    monkeypatch.setattr(function_app, "get_ado_pat", lambda org=None: "server-pat")
    monkeypatch.setattr(function_app, "AlertRepository", Repo)


WEBHOOK = {"organization": "myorg", "resource": {"id": 12, "project": {"name": "Proj"}, "definition": {"id": 3, "name": "CI"}, "result": "failed"}}


def test_webhook_ingests_timeline_and_failure_log(monkeypatch):
    class Client:
        def __init__(self, org, pat):
            pass

        def get_build(self, project, build_id):
            return {"id": build_id}

        def get_timeline(self, project, build_id):
            return {}

        def flatten_timeline(self, build, timeline):
            return _metrics(failed=True)

        def get_log_tail(self, project, build_id, log_id):
            return "tail of log"

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Client)
    response = function_app.ingest_run(_post(WEBHOOK))
    assert response.status_code == 200 and json.loads(response.get_body())["records_upserted"] == 1
    assert Repo.saved[0].failure_log_excerpt == "tail of log" and Repo.saved[0].project_name == "Proj"


@pytest.mark.parametrize("status", [401, 404, 429, 503])
def test_webhook_degrades_to_fallback_metric_when_azure_devops_errors(monkeypatch, status):
    class Client:
        def __init__(self, org, pat):
            pass

        def get_build(self, project, build_id):
            response = requests.Response()
            response.status_code = status
            raise requests.HTTPError(response=response)

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Client)
    response = function_app.ingest_run(_post(WEBHOOK))
    assert response.status_code == 200
    assert Repo.saved[0].is_degraded is True and Repo.saved[0].record_id == "fallback-12"


def test_webhook_degrades_on_network_errors(monkeypatch):
    class Client:
        def __init__(self, org, pat):
            raise requests.ConnectionError("down")

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Client)
    assert function_app.ingest_run(_post(WEBHOOK)).status_code == 200 and Repo.saved[0].is_degraded


def test_webhook_rejects_incomplete_payload_and_hides_crashes(monkeypatch):
    assert function_app.ingest_run(_post({"organization": "myorg"})).status_code == 400

    class Client:
        def __init__(self, org, pat):
            raise RuntimeError("password=hunter2")

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Client)
    response = function_app.ingest_run(_post(WEBHOOK))
    assert response.status_code == 500 and b"hunter2" not in response.get_body()


def test_organization_is_derived_from_resource_urls():
    extract = function_app._extract_organization
    assert extract({}, {"url": "https://dev.azure.com/acme/proj/_apis/build/builds/1"}) == "acme"
    assert extract({}, {"url": "https://acme.visualstudio.com/proj/_apis/build/builds/1"}) == "acme"
    assert extract({"resourceContainers": {"account": {"name": "fallback"}}}, {}) == "fallback"
    assert extract({"organization": "explicit"}, {"url": "https://dev.azure.com/acme"}) == "explicit"


def test_get_recommendations_returns_model_findings(monkeypatch):
    from core.models import Finding, RecommendationResponse

    class RichRepo(Repo):
        def count_runs(self, pid):
            return 9

        def get_pipeline_metrics(self, pid):
            return []

        def upsert_recommendations(self, pid, findings):
            RichRepo.stored = findings

    class Client:
        def __init__(self, *args):
            pass

        def recommend(self, summary):
            return RecommendationResponse([Finding("bottleneck", "low", "Build", None, "r", "e")])

    monkeypatch.setattr(function_app, "AlertRepository", RichRepo)
    monkeypatch.setattr(function_app, "PipelineRecommendationClient", Client)
    monkeypatch.setattr(function_app, "get_settings", lambda: SimpleNamespace(sql_connection_string="x", min_history_runs=5,
                        azure_openai_endpoint="e", azure_openai_deployment="d", azure_openai_api_version="v"))
    response = function_app.get_recommendations(_post({"pipeline_id": 3}, "get_recommendations"))
    assert response.status_code == 200 and json.loads(response.get_body())["findings"][0]["category"] == "bottleneck"
    assert function_app.get_recommendations(_post({"nope": 1}, "get_recommendations")).status_code == 400


def test_ingest_pipeline_reports_azure_devops_auth_failure(monkeypatch):
    class Client:
        def __init__(self, org, pat):
            pass

        def list_builds(self, *a, **k):
            response = requests.Response()
            response.status_code = 401
            raise requests.HTTPError(response=response)

    monkeypatch.setattr(function_app, "AzureDevOpsClient", Client)
    response = function_app.ingest_pipeline(_post({"organization": "myorg", "project": "Proj", "pipeline_id": 3, "pat": "abcdef1234567890"}, "ingest_pipeline"))
    assert response.status_code == 401


def test_functions_directory_copy_is_identical():
    """functions/function_app.py must stay byte-identical to the root module that the tests and deployment exercise."""
    assert (ROOT / "function_app.py").read_bytes() == (ROOT / "functions" / "function_app.py").read_bytes()

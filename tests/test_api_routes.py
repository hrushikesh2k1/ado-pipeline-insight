from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

import app.api.routes as routes
import app.repositories.pipeline_repository as repo_module
from app.main import create_app

NOW = datetime.now(timezone.utc)
RUN = {
    "run_id": 5, "pipeline_id": 3, "pipeline_name": "CI", "organization_name": "org", "project_name": "proj",
    "source_branch": "main", "source_version": "abc", "requested_by": "dev", "queue_time": NOW - timedelta(seconds=30),
    "start_time": NOW - timedelta(seconds=20), "finish_time": NOW, "result": "succeeded", "data_quality": "complete",
    "build_number": "1", "duration_seconds": 20, "is_degraded": 0,
}


@pytest.fixture
def api(monkeypatch, tmp_path):
    state = {"run": RUN, "fail": None}

    def fake_all(query, params=()):
        if state["fail"]:
            raise state["fail"]
        q = query.lower()
        if "from dbo.pipelines" in q and "join" not in q:
            return [{"pipeline_id": 3, "pipeline_name": "CI", "organization_name": "org", "project_name": "proj"}]
        if "from dbo.pipeline_runs r where" in q:
            return [RUN, {**RUN, "run_id": 6, "result": "failed"}]
        if "group by s.stage_name" in q:
            return [{"stage_name": "Build", "avg_duration_seconds": 10, "samples": 2, "failed_count": 1}]
        if "from dbo.pipeline_tasks where run_id" in q:
            return [{"task_name": "npm", "failure_log_excerpt": "boom", "result": "failed"}]
        return []

    def fake_one(query, params=()):
        if state["fail"]:
            raise state["fail"]
        if "wherer.run_id=?" in query.lower().replace(" ", ""):
            return state["run"]
        return {"total": 2, "ok": 1}

    monkeypatch.setattr(repo_module, "fetch_all", fake_all)
    monkeypatch.setattr(repo_module, "fetch_one", fake_one)
    monkeypatch.setattr(routes, "fetch_one", fake_one)
    monkeypatch.setattr(routes, "_get_state_file_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(routes, "_ingestion_jobs", {})
    return TestClient(create_app(), raise_server_exceptions=False), state


@pytest.mark.parametrize("url", [
    "/api/v1/options", "/api/v1/summary?pipeline_id=3&days=30", "/api/v1/summary", "/api/v1/trends?pipeline_id=3",
    "/api/v1/runs?pipeline_id=3&status=failed&days=7", "/api/v1/runs", "/api/v1/runs/5/timeline", "/api/v1/runs/5/analysis",
    "/api/v1/runs/5/logs", "/api/v1/pipelines/3/recommendations", "/api/v1/pools?days=7",
])
def test_read_endpoints_return_200(api, url):
    client, _ = api
    assert client.get(url).status_code == 200


def test_health_reports_database_state(api):
    client, state = api
    assert client.get("/api/v1/health").json() == {"status": "ok", "database": "ok"}
    state["fail"] = RuntimeError("secret connection detail")
    response = client.get("/api/v1/health")
    assert response.status_code == 503 and "secret" not in response.text


def test_summary_calculates_rates(api):
    body = api[0].get("/api/v1/summary?pipeline_id=3").json()
    assert body["total_runs"] == 2 and body["success_rate_pct"] == 50.0 and body["failure_rate_pct"] == 50.0


def test_logs_joins_failure_excerpts(api):
    assert api[0].get("/api/v1/runs/5/logs").json()["log"] == "boom"


def test_unknown_run_analysis_is_404(api):
    client, state = api
    state["run"] = None
    assert client.get("/api/v1/runs/5/analysis").status_code == 404


def test_run_analysis_returns_metrics(api):
    body = api[0].get("/api/v1/runs/5/analysis").json()
    assert body["metrics"]["run_duration_seconds"] == 20.0 and body["metrics"]["queue_seconds"] == 10.0


def test_analyze_delegates_to_service_and_hides_internal_errors(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(routes.ai_service, "analyze", lambda pipeline_id, days: {"pipeline_id": pipeline_id, "days": days})
    assert client.post("/api/v1/pipelines/3/analyze", json={"months": 2}).json() == {"pipeline_id": 3, "days": 62}

    def boom(*_a):
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(routes.ai_service, "analyze", boom)
    response = client.post("/api/v1/pipelines/3/analyze", json={"months": 2})
    assert response.status_code == 503 and "hunter2" not in response.text


class FakeAdo:
    def __init__(self, organization, pat):
        self.organization = organization

    def list_projects(self):
        return [{"id": "p1", "name": "Proj"}]

    def list_pipelines(self, project):
        return [{"id": 3, "name": "CI"}]


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def test_connect_lists_projects_and_pipelines(api, monkeypatch):
    monkeypatch.setattr(routes, "AzureDevOpsClient", FakeAdo)
    body = api[0].post("/api/v1/ado/connect", json={"organization": "myorg", "pat": "abcdef1234567890"}).json()
    assert body["projects"][0]["name"] == "Proj" and body["pipelines"][0]["project_name"] == "Proj"


@pytest.mark.parametrize("status,expected", [(401, 401), (403, 401), (500, 502)])
def test_connect_maps_azure_devops_errors(api, monkeypatch, status, expected):
    class Failing(FakeAdo):
        def list_projects(self):
            raise _http_error(status)

    monkeypatch.setattr(routes, "AzureDevOpsClient", Failing)
    assert api[0].post("/api/v1/ado/connect", json={"organization": "myorg", "pat": "abcdef1234567890"}).status_code == expected


def test_connect_without_any_pat_is_unauthorized(api, monkeypatch):
    def no_pat(_org=None):
        raise KeyError("ADO_PAT")

    monkeypatch.setattr(routes, "get_ado_pat", no_pat)
    assert api[0].post("/api/v1/ado/connect", json={"organization": "myorg"}).status_code == 401


def test_ingest_lifecycle(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(routes, "_run_historical_ingestion", lambda *a, **k: None)
    payload = {"organization": "myorg", "project": "Proj", "pipeline_id": 3, "pat": "abcdef1234567890", "days": 30}
    assert client.post("/api/v1/ado/ingest", json=payload).json()["status"] == "running"
    assert client.post("/api/v1/ado/ingest", json=payload).json()["status"] == "running"
    assert client.get("/api/v1/ado/ingest/status?organization=myorg&pipeline_id=3").json()["status"] == "running"
    assert client.get("/api/v1/ado/ingest/status").json()["status"] == "running"
    assert client.get("/api/v1/ado/ingest/status?organization=other&pipeline_id=9").json()["status"] == "idle"


def test_status_is_idle_when_nothing_ran(api):
    assert api[0].get("/api/v1/ado/ingest/status").json()["status"] == "idle"


def test_background_ingestion_stores_only_missing_builds(monkeypatch, tmp_path):
    from core.models import TimelineMetric

    stored = []

    class Client:
        def __init__(self, org, pat):
            pass

        def list_builds(self, project, **kwargs):
            return [{"id": i, "status": "completed", "finishTime": "2026-01-01T00:00:00Z"} for i in (1, 2, 3)]

        def get_timeline(self, project, build_id):
            return {}

        def flatten_timeline(self, build, timeline):
            return [TimelineMetric(run_id=build["id"], pipeline_id=3, pipeline_name="CI", level="task", stage_name="S", job_name="J",
                                   task_name="T", result="failed", log_id=1)]

        def get_log_tail(self, project, build_id, log_id):
            return "tail"

    class Repo:
        def __init__(self, _cs):
            pass

        def get_existing_run_ids(self, _pid):
            return {1}

        def upsert_metrics(self, metrics):
            stored.extend(metrics)

    monkeypatch.setattr(routes, "AzureDevOpsClient", Client)
    monkeypatch.setattr(routes, "AlertRepository", Repo)
    monkeypatch.setattr(routes, "_get_state_file_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(routes, "_ingestion_jobs", {"k": {"status": "running"}})
    routes._run_historical_ingestion("myorg", "pat", "Proj", 3, 30, "k")
    assert sorted(m.run_id for m in stored) == [2, 3]
    assert stored[0].failure_log_excerpt == "tail"
    assert routes._ingestion_jobs["k"]["status"] == "completed" and routes._ingestion_jobs["k"]["processed_runs"] == 3


def test_background_ingestion_failure_is_recorded_without_details(monkeypatch, tmp_path):
    class Boom:
        def __init__(self, org, pat):
            raise RuntimeError("password=hunter2")

    monkeypatch.setattr(routes, "AzureDevOpsClient", Boom)
    monkeypatch.setattr(routes, "_get_state_file_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(routes, "_ingestion_jobs", {"k": {"status": "running"}})
    routes._run_historical_ingestion("myorg", "pat", "Proj", 3, 30, "k")
    job = routes._ingestion_jobs["k"]
    assert job["status"] == "failed" and "hunter2" not in job["error"]

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


def test_auth_me_anonymous(api):
    client, _ = api
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data["authenticated"] is False
    assert data["userId"] is None
    assert data["email"] is None


def test_auth_me_authenticated(api):
    client, _ = api
    import base64
    import json
    claims = json.dumps({"claims": [{"typ": "name", "val": "Hrushikesh Boora"}]})
    encoded = base64.b64encode(claims.encode("utf-8")).decode("utf-8")
    headers = {
        "x-ms-client-principal-id": "usr-12345",
        "x-ms-client-principal-name": "hrushikesh.boora@octave.com",
        "x-ms-client-principal": encoded,
    }
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["authenticated"] is True
    assert data["userId"] == "usr-12345"
    assert data["email"] == "hrushikesh.boora@octave.com"
    assert data["name"] == "Hrushikesh Boora"
    assert data["provider"] == "Microsoft Entra ID"


def test_ado_repositories(api, monkeypatch):
    client, _ = api
    class MockClient:
        def __init__(self, org, pat):
            pass
        def list_repositories(self, project):
            return [
                {"id": "repo-1", "name": "cldops-customer", "defaultBranch": "refs/heads/main", "webUrl": "https://dev.azure.com/org/p/_git/cldops-customer"}
            ]

    monkeypatch.setattr(routes, "AzureDevOpsClient", MockClient)
    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat: "test-pat")
    r = client.get("/api/v1/ado/repositories?organization=myorg&project=myproj")
    assert r.status_code == 200
    repos = r.json()
    assert len(repos) == 1
    assert repos[0]["name"] == "cldops-customer"
    assert repos[0]["default_branch"] == "main"


def test_ado_pull_requests(api, monkeypatch):
    client, _ = api
    class MockClient:
        def __init__(self, org, pat):
            pass
        def list_pull_requests(self, project, repository_id, status="active", top=100):
            return [
                {
                    "pullRequestId": 101,
                    "title": "Add health check monitoring",
                    "description": "Implements automated ping",
                    "status": "active",
                    "creationDate": "2026-09-30T10:00:00Z",
                    "sourceRefName": "refs/heads/feature/health",
                    "targetRefName": "refs/heads/main",
                    "isDraft": False,
                    "mergeStatus": "succeeded",
                    "createdBy": {"displayName": "Alice Smith", "imageUrl": "https://img.test/alice"},
                    "reviewers": [
                        {"id": "rev-1", "displayName": "Bob Jones", "vote": 10, "isRequired": True}
                    ],
                    "repository": {"id": "repo-1", "name": "cldops-customer"},
                    "_links": {"web": {"href": "https://dev.azure.com/org/p/_git/cldops-customer/pullrequest/101"}}
                }
            ]

    monkeypatch.setattr(routes, "AzureDevOpsClient", MockClient)
    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat: "test-pat")
    r = client.get("/api/v1/ado/pullrequests?organization=myorg&project=myproj&repository_id=repo-1")
    assert r.status_code == 200
    prs = r.json()
    assert len(prs) == 1
    assert prs[0]["id"] == 101
    assert prs[0]["title"] == "Add health check monitoring"
    assert prs[0]["source_branch"] == "feature/health"
    assert prs[0]["target_branch"] == "main"
    assert prs[0]["created_by_name"] == "Alice Smith"
    assert len(prs[0]["reviewers"]) == 1
    assert prs[0]["reviewers"][0]["vote"] == 10


def test_ado_pull_request_review(api, monkeypatch):
    client, _ = api
    class MockClient:
        def __init__(self, organization, pat):
            pass
        def get_pull_request(self, project, repository_id, pull_request_id):
            return {
                "pullRequestId": pull_request_id,
                "title": "Fix memory leak in subscriber",
                "description": "Patches unclosed client connection",
                "sourceRefName": "refs/heads/fix/leak",
                "targetRefName": "refs/heads/main",
                "createdBy": {"displayName": "Dev User"},
                "mergeStatus": "succeeded",
            }
        def get_pull_request_commits(self, project, repository_id, pull_request_id):
            return [{"commitId": "abc1234", "comment": "Close socket on termination"}]
        def get_pull_request_iterations(self, project, repository_id, pull_request_id):
            return [{"id": 1}]
        def get_pull_request_iteration_changes(self, project, repository_id, pull_request_id, iteration_id):
            return [
                {"item": {"path": "/app/subscriber.py"}, "changeType": "edit"},
                {"item": {"path": "/tests/test_subscriber.py"}, "changeType": "add"},
            ]

    monkeypatch.setattr(routes, "AzureDevOpsClient", MockClient)
    monkeypatch.setattr(routes, "get_ado_pat", lambda org: "test-pat")

    payload = {
        "organization": "myorg",
        "project": "myproj",
        "repository_id": "repo-1",
        "pull_request_id": 101,
        "pat": "fake-pat",
    }
    r = client.post("/api/v1/ado/pullrequests/review", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["pull_request_id"] == 101
    assert data["posted_to_ado"] is False
    assert "verdict" in data
    assert "summary" in data
    assert "scorecard" in data
    assert "clarifications" in data
    assert isinstance(data["comments"], list)


def test_ado_teams(api):
    client, _ = api
    r = client.get("/api/v1/ado/teams?organization=myorg&project=myproj")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert any("Team" in t["name"] or "Engineering" in t["name"] for t in data)


def test_version_metadata(api):
    client, _ = api
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert "git_commit" in data
    assert data["service"] == "ADO Pipeline Insight"


def test_ado_sprints(api):
    client, _ = api
    r = client.get("/api/v1/ado/sprints?organization=myorg&project=myproj&team=CloudOps-Monitoring")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert any("Work" in s["name"] for s in data)


def test_ado_sprint_board(api):
    client, _ = api
    r = client.get("/api/v1/ado/sprints/board?organization=myorg&project=myproj&team=CloudOps-Monitoring")
    assert r.status_code == 200
    data = r.json()
    assert "team" in data
    assert "iteration" in data
    assert "work_items" in data
    assert "checks_summary" in data
    assert len(data["work_items"]) > 0

    # Verify Check 1 and Check 2 are evaluated
    summary = data["checks_summary"]
    assert summary["tasks_closed_without_hours_count"] >= 1
    assert summary["stories_in_review_stale_count"] >= 1
    assert len(summary["flagged_item_ids"]) >= 2

    # Verify Milestone summary is populated
    assert "milestone" in data
    assert data["milestone"] is not None
    assert "total_stories" in data["milestone"]
    assert "closed_stories_count" in data["milestone"]


def test_ado_sprint_board_sprint_selection(api):
    client, _ = api
    # Query specific sprint (iter-prev)
    r = client.get("/api/v1/ado/sprints/board?organization=myorg&project=myproj&team=CloudOps-Monitoring&iteration_id=iter-prev")
    assert r.status_code == 200
    data = r.json()
    assert data["iteration"]["id"] == "iter-prev"
    # Should contain items 8001, 8002, 8003
    item_ids = [w["id"] for w in data["work_items"]]
    assert 8001 in item_ids
    assert 8002 in item_ids
    assert 8003 in item_ids
    assert 9001 not in item_ids


def test_milestone_ai_summary(api):
    client, _ = api
    payload = {
        "sprint_name": "Sprint 26-09",
        "team_name": "CloudOps Team",
        "achieved_items": [
            {
                "id": 9001,
                "title": "Data Ingestion Optimization",
                "work_item_type": "User Story",
                "assigned_to_name": "DevOps Engineer",
                "category": "Technical & Infrastructure",
            }
        ],
        "total_stories": 5,
        "closed_stories_count": 3,
        "total_delivered_hours": 32.5,
    }
    r = client.post("/api/v1/sprint-board/milestone-ai-summary", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert "highlights" in data
    assert len(data["highlights"]) >= 2
    assert "9001" in data["summary"] or "Data Ingestion" in data["summary"] or "CloudOps" in data["summary"]


def test_milestone_ai_summary_uses_openai_when_configured(api, monkeypatch):
    """Regression: the AI path referenced an undefined client class and always fell back silently."""
    import types
    from app.api import routes as routes_module

    class FakeClient:
        deployment = "fake"

        def __init__(self, **kwargs):
            create = lambda **kw: types.SimpleNamespace(  # noqa: E731
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="AI BRIEFING #9001"))]
            )
            self.client = types.SimpleNamespace(
                chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
            )

    real_settings = routes_module.get_settings()
    fake_settings = types.SimpleNamespace(**{**vars(real_settings), "azure_openai_endpoint": "https://example.test"}) \
        if hasattr(real_settings, "__dict__") else real_settings.model_copy(update={"azure_openai_endpoint": "https://example.test"})
    monkeypatch.setattr(routes_module, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(routes_module, "PipelineRecommendationClient", FakeClient)

    client, _ = api
    payload = {
        "sprint_name": "S1",
        "team_name": "T",
        "achieved_items": [{"id": 9001, "title": "X", "work_item_type": "User Story", "category": "Feature & Business Value"}],
        "total_stories": 1,
        "closed_stories_count": 1,
        "total_delivered_hours": 4,
    }
    r = client.post("/api/v1/sprint-board/milestone-ai-summary", json=payload)
    assert r.status_code == 200
    assert "AI BRIEFING #9001" in r.json()["summary"]





def test_sprint_board_shows_only_the_selected_teams_items(api, monkeypatch):
    """A sprint is shared by every team; only items in the selected team's area paths may appear."""
    def wi(i, wtype, area, parent=None):
        f = {"System.Id": i, "System.Title": f"item {i}", "System.WorkItemType": wtype, "System.State": "Active",
             "System.IterationPath": r"proj\Sprint 1", "System.AreaPath": area}
        if parent:
            f["System.Parent"] = parent
        return {"id": i, "fields": f, "relations": []}

    items = [wi(1, "User Story", r"proj\CloudOps-Monitoring"), wi(2, "Task", r"proj\CloudOps-Monitoring", parent=1),
             wi(3, "User Story", r"proj\Identity"), wi(4, "Task", r"proj\Identity", parent=3),
             wi(5, "Bug", r"proj\CloudOps-Monitoring\Alerts")]

    class FakeAdo:
        def __init__(self, *a, **k):
            pass

        def list_team_iterations(self, project, team, timeframe=None):
            return [{"id": "it-1", "name": "Sprint 1", "path": r"proj\Sprint 1", "attributes": {"timeFrame": "current"}}]

        def get_team_iteration(self, project, team, iteration_id):
            return {"id": "it-1", "name": "Sprint 1", "path": r"proj\Sprint 1"}

        def get_iteration_work_items(self, project, team, iteration_id):
            return []

        def query_wiql(self, project, wiql):
            return [i["id"] for i in items]  # the sprint query returns every team's items

        def get_work_items_batch(self, project, ids, fields=None):
            return [i for i in items if i["id"] in ids]

        def get_team_field_values(self, project, team):
            return {"defaultValue": r"proj\CloudOps-Monitoring", "values": [{"value": r"proj\CloudOps-Monitoring", "includeChildren": True}]}

    monkeypatch.setattr(routes, "AzureDevOpsClient", FakeAdo)
    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat=None: "token")
    client, _ = api
    r = client.get("/api/v1/ado/sprints/board?organization=myorg&project=proj&team=CloudOps-Monitoring&iteration_id=it-1")
    assert r.status_code == 200
    ids = sorted(w["id"] for w in r.json()["work_items"])
    assert ids == [1, 2, 5], f"expected only the Monitoring team's items, got {ids}"


def _dated_board_client(monkeypatch, *, team_iteration, node):
    """Fake Azure DevOps where the team's sprint LIST carries no dates (as seen on a real Oct sprint)."""
    class FakeAdo:
        def __init__(self, *a, **k):
            pass

        def list_team_iterations(self, project, team, timeframe=None):
            return [{"id": "oct", "name": "26-10", "path": r"proj\26-10", "attributes": {"timeFrame": "current"}}]

        def get_team_iteration(self, project, team, iteration_id):
            if team_iteration is None:
                raise RuntimeError("team iteration lookup failed")
            return {"id": "oct", "name": "26-10", "path": r"proj\26-10", "attributes": team_iteration}

        def get_iteration_node(self, project, relative_path):
            assert relative_path == "26-10"
            return {"name": "26-10", "attributes": node}

        def get_iteration_work_items(self, project, team, iteration_id):
            return []

        def query_wiql(self, project, wiql):
            return []

        def get_work_items_batch(self, project, ids, fields=None):
            return []

        def get_team_field_values(self, project, team):
            return {}

    monkeypatch.setattr(routes, "AzureDevOpsClient", FakeAdo)
    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat=None: "token")


def test_sprint_board_dates_come_from_the_team_iteration_when_the_list_has_none(api, monkeypatch):
    _dated_board_client(monkeypatch, team_iteration={"startDate": "2026-10-01T00:00:00Z", "finishDate": "2026-10-31T00:00:00Z"}, node=None)
    client, _ = api
    r = client.get("/api/v1/ado/sprints/board?organization=myorg&project=proj&team=T&iteration_id=oct")
    assert r.status_code == 200
    body = r.json()
    assert body["iteration"]["start_date"] == "2026-10-01T00:00:00Z"
    assert body["iteration"]["finish_date"] == "2026-10-31T00:00:00Z"
    assert body["working_days_remaining"] is not None


def test_sprint_board_dates_fall_back_to_the_project_iteration_node(api, monkeypatch):
    _dated_board_client(monkeypatch, team_iteration=None, node={"startDate": "2026-10-01T00:00:00Z", "finishDate": "2026-10-31T00:00:00Z"})
    client, _ = api
    r = client.get("/api/v1/ado/sprints/board?organization=myorg&project=proj&team=T&iteration_id=oct")
    assert r.status_code == 200
    body = r.json()
    assert (body["iteration"]["start_date"], body["iteration"]["finish_date"]) == ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert body["working_days_remaining"] is not None


def test_sprint_board_current_sprint_keeps_its_dates(api, monkeypatch):
    class FakeAdo:
        def __init__(self, *a, **k):
            pass

        def list_team_iterations(self, project, team, timeframe=None):
            return [{"id": "oct", "name": "26-10", "path": r"proj\26-10",
                     "attributes": {"startDate": "2026-10-01T00:00:00Z", "finishDate": "2026-10-31T00:00:00Z", "timeFrame": "current"}}]

        def get_team_iteration(self, project, team, iteration_id):
            return {}

        def get_iteration_node(self, project, relative_path):
            return {}

        def get_iteration_work_items(self, project, team, iteration_id):
            return []

        def query_wiql(self, project, wiql):
            return []

        def get_work_items_batch(self, project, ids, fields=None):
            return []

        def get_team_field_values(self, project, team):
            return {}

    monkeypatch.setattr(routes, "AzureDevOpsClient", FakeAdo)
    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat=None: "token")
    client, _ = api
    body = client.get("/api/v1/ado/sprints/board?organization=myorg&project=proj&team=T").json()  # no iteration chosen: current
    assert (body["iteration"]["start_date"], body["iteration"]["finish_date"]) == ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import azure.functions as func

import function_app


def test_get_recommendations_skips_llm_for_insufficient_history(monkeypatch):
    class FakeRepository:
        def __init__(self, _connection_string):
            pass

        def count_runs(self, _pipeline_id):
            return 2

    monkeypatch.setattr(function_app, "get_settings", lambda: SimpleNamespace(sql_connection_string="test", min_history_runs=5))
    monkeypatch.setattr(function_app, "AlertRepository", FakeRepository)
    response = function_app.get_recommendations(func.HttpRequest("POST", "http://localhost/api/get_recommendations", body=b'{"pipeline_id": 7}'))
    assert response.status_code == 200
    assert "Not enough run history" in json.loads(response.get_body())["message"]


def test_build_fallback_metric_uses_resource_timestamps():
    resource = {
        "id": 123,
        "definition": {"id": 7, "name": "project-1"},
        "queueTime": "2026-08-30T12:00:00Z",
        "startTime": "2026-08-30T12:00:10Z",
        "finishTime": "2026-08-30T12:00:25Z",
        "result": "succeeded",
    }
    metric = function_app._build_fallback_metric(resource, 123, None, None)
    assert metric.is_degraded is True
    assert metric.data_quality == "degraded"
    assert metric.start_time == datetime(2026, 8, 30, 12, 0, 10, tzinfo=timezone.utc)
    assert metric.finish_time == datetime(2026, 8, 30, 12, 0, 25, tzinfo=timezone.utc)
    assert metric.duration_seconds == 15.0


def test_ingest_pipeline_applies_max_runs_limit(monkeypatch):
    class FakeClient:
        def __init__(self, org, pat):
            pass

        def list_builds(self, project, pipeline_id, min_time, top, max_builds):
            # Return 10 completed builds
            return [
                {"id": i, "status": "completed", "finishTime": "2026-08-30T12:00:25Z"}
                for i in range(1, 11)
            ]

        def get_timeline(self, project, build_id):
            return {"records": []}

        def flatten_timeline(self, build, timeline):
            from core.models import TimelineMetric
            return [
                TimelineMetric(
                    run_id=build["id"],
                    pipeline_id=1,
                    pipeline_name="p1",
                    organization_name="org",
                    project_name="proj",
                    level="stage",
                    stage_name="stage1",
                    job_name=None,
                    task_name=None,
                    agent_name=None,
                    queue_time=datetime.now(timezone.utc),
                    start_time=datetime.now(timezone.utc),
                    finish_time=datetime.now(timezone.utc),
                    duration_seconds=10.0,
                    result="succeeded",
                    retry_count=0,
                    source_branch=None,
                    source_version=None,
                    requested_by=None,
                    is_degraded=False,
                    data_quality="good",
                    failure_log_excerpt=None,
                    log_id=None,
                    record_id=f"r-{build['id']}",
                    parent_id=None,
                    build_number="1",
                )
            ]

    upserted = []

    class FakeRepo:
        def __init__(self, cs):
            pass

        def upsert_metrics(self, metrics):
            upserted.extend(metrics)

    monkeypatch.setattr(function_app, "AzureDevOpsClient", FakeClient)
    monkeypatch.setattr(function_app, "AlertRepository", FakeRepo)
    monkeypatch.setattr(function_app, "get_settings", lambda: SimpleNamespace(sql_connection_string="test"))

    body = json.dumps({
        "organization": "test-org",
        "project": "test-proj",
        "pipeline_id": 1,
        "days": 30,
        "pat": "fake-pat",
        "max_runs": 3,
    }).encode("utf-8")

    req = func.HttpRequest("POST", "http://localhost/api/ingest_pipeline", body=body)
    resp = function_app.ingest_pipeline(req)
    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data["completed_runs_found"] == 10
    assert data["runs_ingested"] == 3
    assert data["limit_applied"] == 3
    assert len(upserted) == 3
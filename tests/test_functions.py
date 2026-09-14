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
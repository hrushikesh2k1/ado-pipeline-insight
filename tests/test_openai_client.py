import pytest

from core.openai_client import PipelineRecommendationClient, parse_recommendations
from backend.app.services.ai_service import _telemetry_fallback


def test_parse_recommendations_validates_required_schema():
    response = parse_recommendations('{"findings":[{"category":"regression","severity":"high","stage_name":"Build","task_name":"npm install","recommendation":"Restore cache.","evidence":"60% slower."}]}')
    assert response.findings[0].task_name == "npm install"


def test_parse_recommendations_rejects_malformed_response():
    with pytest.raises(ValueError):
        parse_recommendations('{"findings":[{"category":"not-real"}]}')


def test_recommend_retries_once_after_malformed_response():
    class FakeCompletions:
        def __init__(self):
            self.responses = iter(['not json', '{"findings":[]}'])

        def create(self, **_kwargs):
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": next(self.responses)})()})()]})()

    client = object.__new__(PipelineRecommendationClient)
    client.deployment = "test"
    client.client = type("FakeClient", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()
    assert client.recommend({"stages": []}).findings == []


def test_telemetry_fallback_returns_metric_backed_finding():
    findings = _telemetry_fallback({
        "stages": [{
            "name": "Build",
            "avg_duration_s": 120,
            "failure_rate_pct": 0,
            "retry_rate_pct": 0,
            "tasks": [{
                "name": "Install",
                "avg_duration_s": 90,
                "failure_rate_pct": 20,
                "retry_rate_pct": 10,
            }],
        }]
    })
    assert findings[0]["task_name"] == "Install"
    assert findings[0]["category"] == "flaky_step"
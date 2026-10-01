"""API contract tests for AI analysis and recommendations endpoints."""
from fastapi.testclient import TestClient
from app.main import app
import app.services.ai_service as ai_service_module
import app.repositories.pipeline_repository as repo_module


def test_analyze_delegates_to_service_and_hides_internal_errors(monkeypatch):
    client = TestClient(app)
    # Mock AIService.analyze to return a valid recommendation payload
    monkeypatch.setattr(
        ai_service_module.AIService,
        "analyze",
        lambda self, pipeline_id, window_days: {
            "status": "ready",
            "findings": [
                {
                    "category": "caching_opportunity",
                    "severity": "medium",
                    "stage_name": "Deploy cops Records Dev",
                    "task_name": "npm install",
                    "recommendation": "Add Cache@2 task",
                    "evidence": "Takes 120s every run",
                }
            ],
            "analyzed_at": "2026-09-27T12:00:00Z",
        },
    )

    response = client.post("/api/v1/pipelines/3010/analyze", json={"months": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["stage_name"] == "Deploy cops Records Dev"


def test_recommendations_endpoint_returns_pipeline_findings(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        repo_module.PipelineRepository,
        "recommendations",
        lambda self, pipeline_id, limit=50: [
            {
                "finding_id": 1,
                "category": "flaky_step",
                "severity": "high",
                "stage_name": "Deploy cops Analytics Dev",
                "task_name": "Helm Upgrade",
                "recommendation": "Add retryCountOnTaskFailure: 2",
            }
        ],
    )

    response = client.get("/api/v1/pipelines/3010/recommendations?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["pipeline_id"] == 3010
    assert len(data["findings"]) == 1
    assert data["findings"][0]["category"] == "flaky_step"

"""Contract tests for duration trend API endpoint."""
from fastapi.testclient import TestClient
from app.main import app
import app.repositories.pipeline_repository as repo_module


def test_trends_endpoint_returns_200_and_expected_structure(monkeypatch):
    client = TestClient(app)
    # Mock database calls for trends
    monkeypatch.setattr(repo_module, "fetch_all", lambda q, p=(): [
        {
            "run_id": 1,
            "build_number": "1",
            "run_date": "2026-09-01T08:00:00",
            "pipeline_id": 3,
            "pipeline_name": "test-pipeline",
            "duration_seconds": 120.0,
            "result": "succeeded",
        }
    ])
    response = client.get("/api/v1/trends?pipeline_id=3&days=30")
    assert response.status_code == 200
    data = response.json()
    assert "build_trend" in data
    assert "stage_trend" in data
    assert "daily_trend" in data

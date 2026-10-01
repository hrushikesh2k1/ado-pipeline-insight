from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories import release_repository
from app.schemas.connection import ReleaseDefinitionCreate


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_release_branch_candidates_endpoint(client, monkeypatch):
    """Ensure branch-candidates returns distinct observed branches without heuristics."""
    resp = client.get("/api/v1/releases/branch-candidates?organization=org&project=proj&pipeline_id=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "branch" in data[0]


def test_release_crud_and_scorecard_lifecycle(client):
    """Test full lifecycle: create release, list releases, compute scorecard on read, delete."""
    payload = {
        "name": "Release v2.4.0",
        "organization_name": "FabrikamFiber",
        "project_name": "WebServices",
        "pipeline_id": 42,
        "target_branch": "refs/heads/release/2.4",
        "scope_feature_title": "Checkout Redesign",
        "target_ship_date": "2026-10-20",
    }

    # 1. Create Release
    create_resp = client.post("/api/v1/releases", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["name"] == "Release v2.4.0"
    assert created["target_branch"] == "refs/heads/release/2.4"
    assert "release_id" in created
    rel_id = created["release_id"]

    # 2. List Releases
    list_resp = client.get("/api/v1/releases?organization=FabrikamFiber&project=WebServices")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert any(r["release_id"] == rel_id for r in listed)

    # 3. Read Scorecard (computed on read)
    scorecard_resp = client.get(f"/api/v1/releases/{rel_id}")
    assert scorecard_resp.status_code == 200
    card = scorecard_resp.json()
    assert card["release"]["release_id"] == rel_id
    assert card["overall_status"] in ("green", "yellow", "red")
    assert "delivery_completion" in card["dimensions"]
    assert "defect_burden" in card["dimensions"]
    assert "pipeline_health" in card["dimensions"]
    assert "review_backlog" in card["dimensions"]
    assert len(card["ai_narrative"]) > 0

    # 4. Check history
    hist_resp = client.get(f"/api/v1/releases/{rel_id}/history")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert len(hist) >= 1
    assert hist[0]["release_id"] == rel_id

    # 5. Delete Release
    del_resp = client.delete(f"/api/v1/releases/{rel_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # 6. Verify 404 after delete
    get_del = client.get(f"/api/v1/releases/{rel_id}")
    assert get_del.status_code == 404

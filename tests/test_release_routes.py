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
    """Ensure branch-candidates returns a valid list (may be empty if no real data)."""
    resp = client.get("/api/v1/releases/branch-candidates?organization=org&project=proj&repository_id=repo-1&pipeline_id=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # If branches exist, they should have the expected shape
    if len(data) > 0:
        assert "branch" in data[0]


def test_release_crud_and_scorecard_lifecycle(client):
    """Test full lifecycle: create release, list releases, compute scorecard on read, delete."""
    payload = {
        "name": "Release v2.4.0",
        "organization_name": "FabrikamFiber",
        "project_name": "WebServices",
        "repository_id": "repo-checkout",
        "repository_name": "CheckoutRepo",
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
    assert created["repository_name"] == "CheckoutRepo"
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


def test_branch_candidates_returns_empty_when_no_data(client, monkeypatch):
    """REGRESSION: get_branch_candidates must return an empty list when no real data is found.
    TRUST PRINCIPLE: Nothing in this product fabricates data that looks real.
    Previously, the fallback returned fake refs/heads/main and refs/heads/dev entries with
    fabricated timestamps and run_count=1 — this test ensures that never happens again.
    """
    from app.repositories import release_repository as rr_module

    # Mock both DB queries to return empty results (simulating a repo with no observed branches)
    monkeypatch.setattr(rr_module, "fetch_all", lambda *a, **kw: [])

    # Also prevent the ADO client from being instantiated (no PAT available)
    resp = client.get(
        "/api/v1/releases/branch-candidates?organization=TestOrg&project=TestProj&repository_id=repo-abc"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0, (
        "Branch candidates must return empty list when no real branches are found, "
        "not fabricated main/dev entries."
    )

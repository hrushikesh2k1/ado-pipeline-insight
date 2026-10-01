"""Read-only functional test verifying Release Readiness branch candidates and release definitions endpoints.
"""
from __future__ import annotations

import pytest

from quality_gate.functional_tests.conftest import Api, BASE_URL


@pytest.mark.func(
    severity="high",
    area="ReleaseReadiness",
    title="Release branch candidates endpoint returns valid observed branches without keyword assumptions",
    fix="Endpoint /api/v1/releases/branch-candidates must return distinct observed pipeline branches ordered by last_built desc.",
)
def test_release_branch_candidates_live():
    api = Api()
    # Fetch options first to get a real pipeline_id, organization, and project
    resp = api.session.get(f"{BASE_URL}/api/v1/options", timeout=30)
    if resp.status_code != 200:
        pytest.skip(f"/api/v1/options returned {resp.status_code}")

    options = resp.json()
    pipelines = options.get("pipelines", [])
    if not pipelines:
        pytest.skip("No pipelines configured to test branch candidates.")

    p = pipelines[0]
    org = p.get("organization_name") or (options.get("organizations") or ["default"])[0]
    proj = p.get("project_name") or (options.get("projects") or ["default"])[0]
    pipe_id = p["pipeline_id"]

    url = f"{BASE_URL}/api/v1/releases/branch-candidates?organization={org}&project={proj}&pipeline_id={pipe_id}"
    bc_resp = api.session.get(url, timeout=30)
    assert bc_resp.status_code == 200, f"Expected 200 from branch-candidates, got {bc_resp.status_code}: {bc_resp.text}"

    candidates = bc_resp.json()
    assert isinstance(candidates, list)
    for c in candidates:
        assert "branch" in c
        assert "run_count" in c


@pytest.mark.func(
    severity="medium",
    area="ReleaseReadiness",
    title="List releases endpoint returns valid definitions list",
    fix="Endpoint /api/v1/releases must return 200 with list of release definitions.",
)
def test_list_releases_live():
    api = Api()
    resp = api.session.get(f"{BASE_URL}/api/v1/options", timeout=30)
    if resp.status_code != 200:
        pytest.skip(f"/api/v1/options returned {resp.status_code}")

    options = resp.json()
    org = (options.get("organizations") or ["FabrikamFiber"])[0]
    proj = (options.get("projects") or ["WebServices"])[0]

    url = f"{BASE_URL}/api/v1/releases?organization={org}&project={proj}"
    r_resp = api.session.get(url, timeout=30)
    assert r_resp.status_code == 200, f"Expected 200 from list releases, got {r_resp.status_code}: {r_resp.text}"
    assert isinstance(r_resp.json(), list)

from datetime import datetime, timezone, timedelta
from app.schemas.connection import (
    ReleaseDefinition,
    ReleaseDimension,
    ReleaseDimensionEvidenceItem,
)
from app.services.release_service import (
    evaluate_delivery_completion,
    evaluate_defect_burden,
    evaluate_pipeline_health,
    evaluate_review_backlog,
    compute_overall_status,
    normalize_branch,
    is_high_or_blocker_severity,
    generate_deterministic_fallback_narrative,
)


def _make_dummy_dim(key: str, status: str) -> ReleaseDimension:
    return ReleaseDimension(
        key=key,
        name=key.replace("_", " ").title(),
        status=status,
        score_text="Test",
        summary="Test summary",
        evidence_items=[],
        metrics={},
    )


def test_worst_dimension_wins_rule():
    """PRODUCT RULE: Overall verdict is strictly the worst dimension. Never averaged.
    Three Green dimensions + One Red dimension MUST yield overall RED.
    """
    dims_with_one_red = {
        "delivery_completion": _make_dummy_dim("delivery_completion", "green"),
        "defect_burden": _make_dummy_dim("defect_burden", "red"),  # 1 blocker bug
        "pipeline_health": _make_dummy_dim("pipeline_health", "green"),
        "review_backlog": _make_dummy_dim("review_backlog", "green"),
    }
    assert compute_overall_status(dims_with_one_red) == "red"

    # Three Green + One Yellow must yield overall Yellow
    dims_with_one_yellow = {
        "delivery_completion": _make_dummy_dim("delivery_completion", "green"),
        "defect_burden": _make_dummy_dim("defect_burden", "yellow"),
        "pipeline_health": _make_dummy_dim("pipeline_health", "green"),
        "review_backlog": _make_dummy_dim("review_backlog", "green"),
    }
    assert compute_overall_status(dims_with_one_yellow) == "yellow"

    # All Green yields Green
    dims_all_green = {
        "delivery_completion": _make_dummy_dim("delivery_completion", "green"),
        "defect_burden": _make_dummy_dim("defect_burden", "green"),
        "pipeline_health": _make_dummy_dim("pipeline_health", "green"),
        "review_backlog": _make_dummy_dim("review_backlog", "green"),
    }
    assert compute_overall_status(dims_all_green) == "green"


def test_branch_name_neutrality():
    """Branch candidates and matching must be completely agnostic to branch names.
    'dev' and 'release/2.3' must be treated identically without any pattern heuristics.
    """
    now = datetime.now(timezone.utc)

    # Test 'dev' as release branch
    runs_dev = [
        {"run_id": 101, "source_branch": "refs/heads/dev", "result": "succeeded", "start_time": now},
        {"run_id": 100, "source_branch": "refs/heads/dev", "result": "succeeded", "start_time": now - timedelta(hours=1)},
    ]
    dim_dev = evaluate_pipeline_health(runs_dev, target_branch="dev")
    assert dim_dev.status == "green"
    assert dim_dev.metrics["latest_run_id"] == 101

    # Test GitFlow-style 'release/2.3' as release branch
    runs_release = [
        {"run_id": 201, "source_branch": "refs/heads/release/2.3", "result": "succeeded", "start_time": now},
        {"run_id": 200, "source_branch": "release/2.3", "result": "succeeded", "start_time": now - timedelta(hours=1)},
    ]
    dim_release = evaluate_pipeline_health(runs_release, target_branch="refs/heads/release/2.3")
    assert dim_release.status == "green"
    assert dim_release.metrics["latest_run_id"] == 201

    # Test failed run on both branch types produces red identically
    runs_dev_fail = [{"run_id": 301, "source_branch": "dev", "result": "failed", "start_time": now}]
    assert evaluate_pipeline_health(runs_dev_fail, target_branch="refs/heads/dev").status == "red"

    runs_rel_fail = [{"run_id": 302, "source_branch": "release/2.3", "result": "failed", "start_time": now}]
    assert evaluate_pipeline_health(runs_rel_fail, target_branch="release/2.3").status == "red"


def test_pipeline_health_never_pools_pipelines():
    """Two pipelines building the same branch must not be merged into one pass rate."""
    now = datetime.now(timezone.utc)
    runs = [
        {"run_id": 3, "pipeline_id": 1, "pipeline_name": "API", "source_branch": "refs/heads/dev",
         "result": "succeeded", "start_time": now},
        {"run_id": 2, "pipeline_id": 2, "pipeline_name": "Web", "source_branch": "refs/heads/dev",
         "result": "failed", "start_time": now - timedelta(minutes=5)},
        {"run_id": 1, "pipeline_id": 1, "pipeline_name": "API", "source_branch": "refs/heads/dev",
         "result": "succeeded", "start_time": now - timedelta(minutes=10)},
    ]
    dim = evaluate_pipeline_health(runs, target_branch="dev")
    assert dim.status == "red"
    assert dim.metrics["latest_run_id"] == 2
    assert dim.metrics["pipelines_evaluated"] == 2
    assert "Web" in dim.summary


def test_defect_burden_severity_logic():
    """Check Microsoft.VSTS.Common.Severity handling.
    Blocker / high severity produces red. Medium/low produces yellow. None produces green.
    """
    items_blocker = [
        {"id": 10, "work_item_type": "Bug", "state": "Active", "severity": "1 - Critical", "priority": 1},
        {"id": 11, "work_item_type": "Bug", "state": "Resolved", "severity": "1 - Critical"},  # closed, ignored
    ]
    dim_blocker = evaluate_defect_burden(items_blocker)
    assert dim_blocker.status == "red"
    assert dim_blocker.metrics["blocker_bugs_count"] == 1
    assert "#10" in dim_blocker.summary

    items_medium = [
        {"id": 20, "work_item_type": "Bug", "state": "Active", "severity": "3 - Medium", "priority": 3},
    ]
    dim_medium = evaluate_defect_burden(items_medium)
    assert dim_medium.status == "yellow"
    assert dim_medium.metrics["normal_bugs_count"] == 1

    items_clear = [
        {"id": 30, "work_item_type": "User Story", "state": "Active"},
        {"id": 31, "work_item_type": "Bug", "state": "Closed", "severity": "1 - Critical"},
    ]
    dim_clear = evaluate_defect_burden(items_clear)
    assert dim_clear.status == "green"
    assert dim_clear.metrics["total_open_bugs"] == 0


def test_delivery_completion_thresholds():
    """Completion rate >= 90% is green, 70-89% is yellow, < 70% is red."""
    # 9 of 10 closed = 90% -> green
    items_green = [
        {"id": i, "title": f"Story {i}", "work_item_type": "User Story", "state": "Done" if i < 9 else "Active", "completed_work": 4.0}
        for i in range(10)
    ]
    dim_green = evaluate_delivery_completion(items_green)
    assert dim_green.status == "green"
    assert dim_green.metrics["completion_rate_pct"] == 90.0

    # 7 of 10 closed = 70% -> yellow
    items_yellow = [
        {"id": i, "title": f"Story {i}", "work_item_type": "User Story", "state": "Done" if i < 7 else "Active", "completed_work": 4.0}
        for i in range(10)
    ]
    dim_yellow = evaluate_delivery_completion(items_yellow)
    assert dim_yellow.status == "yellow"
    assert dim_yellow.metrics["completion_rate_pct"] == 70.0

    # 5 of 10 closed = 50% -> red
    items_red = [
        {"id": i, "title": f"Story {i}", "work_item_type": "User Story", "state": "Done" if i < 5 else "Active", "completed_work": 4.0}
        for i in range(10)
    ]
    dim_red = evaluate_delivery_completion(items_red)
    assert dim_red.status == "red"
    assert dim_red.metrics["completion_rate_pct"] == 50.0


def test_review_backlog_stale_and_ship_date():
    """PR open > 3 business days with close ship date is red.
    PR open within 3 days is yellow. Zero PRs is green.
    """
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=7)).isoformat()  # > 3 business days
    fresh_date = (now - timedelta(hours=6)).isoformat()

    # Zero PRs -> green
    assert evaluate_review_backlog([], target_branch="main").status == "green"

    # Fresh PR -> yellow
    prs_fresh = [
        {"id": 401, "title": "New feature", "status": "active", "target_branch": "refs/heads/main", "creation_date": fresh_date}
    ]
    assert evaluate_review_backlog(prs_fresh, target_branch="main").status == "yellow"

    # Stale PR with close target ship date (tomorrow) -> red
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    prs_stale = [
        {"id": 402, "title": "Stale PR", "status": "active", "target_branch": "refs/heads/dev", "creation_date": old_date}
    ]
    dim_stale = evaluate_review_backlog(prs_stale, target_branch="dev", target_ship_date=tomorrow_str)
    assert dim_stale.status == "red"
    assert dim_stale.metrics["stale_prs_count"] >= 1


def test_deterministic_fallback_narrative_citations():
    """Fallback narrative must cite exact IDs and blockers without inventing facts."""
    release = ReleaseDefinition(
        release_id="rel-123",
        name="Sprint 42 Release",
        organization_name="MyOrg",
        project_name="MyProj",
        pipeline_id=1,
        target_branch="dev",
        target_ship_date="2026-10-15",
        created_at="2026-10-01T00:00:00Z",
    )
    dim_defect = _make_dummy_dim("defect_burden", "red")
    dim_defect.metrics["blocker_bugs_count"] = 2
    dim_pipe = _make_dummy_dim("pipeline_health", "red")
    dim_pipe.metrics["latest_run_id"] = 9988

    dimensions = {
        "delivery_completion": _make_dummy_dim("delivery_completion", "green"),
        "defect_burden": dim_defect,
        "pipeline_health": dim_pipe,
        "review_backlog": _make_dummy_dim("review_backlog", "green"),
    }
    narrative = generate_deterministic_fallback_narrative(release, dimensions, overall_status="red")
    assert "Sprint 42 Release" in narrative
    assert "dev" in narrative
    assert "NOT READY to ship" in narrative
    assert "9988" in narrative
    assert "2026-10-15" in narrative


def test_severity_matching_precision():
    """REGRESSION: Severity matching must use exact-prefix matching.
    The old substring search on '1' would false-positive on values like '31 - Custom'.
    """
    # Should be high severity
    assert is_high_or_blocker_severity("1 - Critical") is True
    assert is_high_or_blocker_severity("2 - High") is True
    assert is_high_or_blocker_severity("critical") is True
    assert is_high_or_blocker_severity("blocker") is True
    assert is_high_or_blocker_severity("high") is True
    assert is_high_or_blocker_severity(None, priority=1) is True

    # Should NOT be high severity
    assert is_high_or_blocker_severity("3 - Medium") is False
    assert is_high_or_blocker_severity("4 - Low") is False
    assert is_high_or_blocker_severity(None, priority=3) is False
    assert is_high_or_blocker_severity(None) is False


def test_compute_scorecard_iteration_work_item_extraction(monkeypatch):
    """REGRESSION: get_iteration_work_items returns list[dict].
    compute_scorecard must extract work item IDs from this list and match iteration by target_ship_date.
    """
    from app.services.release_service import ReleaseService

    class DummyADOClient:
        def __init__(self, *args, **kwargs):
            pass

        def list_teams(self, project, top=10):
            return [{"id": "team-alpha", "name": "Team Alpha"}]

        def list_team_iterations(self, project, team_id):
            return [
                {
                    "id": "iter-aug",
                    "name": "Sprint Aug",
                    "attributes": {
                        "startDate": "2026-08-01T00:00:00Z",
                        "finishDate": "2026-08-31T00:00:00Z",
                        "timeFrame": "past",
                    },
                },
                {
                    "id": "iter-sep",
                    "name": "Sprint Sep",
                    "attributes": {
                        "startDate": "2026-09-01T00:00:00Z",
                        "finishDate": "2026-09-30T00:00:00Z",
                        "timeFrame": "past",
                    },
                },
                {
                    "id": "iter-oct",
                    "name": "Sprint Oct",
                    "attributes": {
                        "startDate": "2026-10-01T00:00:00Z",
                        "finishDate": "2026-10-31T00:00:00Z",
                        "timeFrame": "current",
                    },
                },
            ]

        def get_iteration_work_items(self, project, team_id, iter_id):
            assert iter_id == "iter-sep", f"Expected iter-sep for target_ship_date 2026-09-15, got {iter_id}"
            # Returns list of relation dicts as ADO does
            return [
                {"rel": None, "source": None, "target": {"id": 101, "url": "http://example/101"}},
                {"rel": None, "source": None, "target": {"id": 102, "url": "http://example/102"}},
            ]

        def get_work_items_batch(self, project, ids, fields=None):
            return [
                {
                    "id": 101,
                    "fields": {
                        "System.Id": 101,
                        "System.Title": "Feature Auth",
                        "System.WorkItemType": "User Story",
                        "System.State": "Done",
                        "Microsoft.VSTS.Scheduling.CompletedWork": 5.0,
                    },
                },
                {
                    "id": 102,
                    "fields": {
                        "System.Id": 102,
                        "System.Title": "Feature Billing",
                        "System.WorkItemType": "User Story",
                        "System.State": "Done",
                        "Microsoft.VSTS.Scheduling.CompletedWork": 3.0,
                    },
                },
            ]

        def list_pull_requests(self, project, repo_id=None, status="active"):
            return []

    monkeypatch.setattr("app.services.release_service.AzureDevOpsClient", DummyADOClient)
    monkeypatch.setattr("app.services.release_service.fetch_all", lambda *args, **kwargs: [])

    release = ReleaseDefinition(
        release_id="rel-sep",
        name="September Release",
        organization_name="MyOrg",
        project_name="MyProj",
        repository_id="repo-1",
        repository_name="MyRepo",
        target_branch="refs/heads/main",
        target_ship_date="2026-09-15",
        created_at="2026-09-01T00:00:00Z",
    )

    service = ReleaseService()
    card = service.compute_scorecard(release, pat="dummy-pat")
    delivery = card.dimensions["delivery_completion"]
    assert delivery.metrics["total_stories"] == 2
    assert delivery.metrics["closed_stories"] == 2
    assert delivery.metrics["completion_rate_pct"] == 100.0
    assert delivery.status == "green"


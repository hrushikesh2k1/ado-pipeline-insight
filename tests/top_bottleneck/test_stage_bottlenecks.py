"""Tests for stage-level bottlenecks and longest duration rankings."""
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder


def test_stage_bottlenecks_computed_in_summary(monkeypatch):
    stage_rows = [
        {"stage_name": "Deploy copsoie OIE Dev", "avg_duration_seconds": 1200.0, "total_runs": 10, "failed_runs": 1},
        {"stage_name": "Deploy copsrecords Records Dev", "avg_duration_seconds": 450.0, "total_runs": 10, "failed_runs": 0},
        {"stage_name": "Deploy copsanalytics Analytics Dev", "avg_duration_seconds": 890.0, "total_runs": 10, "failed_runs": 2},
    ]

    Recorder(
        monkeypatch,
        all_rows=lambda q: stage_rows if "pipeline_stages" in q.lower() else [],
        one_row={"total": 10, "ok": 1}
    )

    s = PipelineRepository().summary(3010, 30)
    stages = s.get("stages", [])
    assert len(stages) == 3
    # Verify stages can be ranked by bottleneck duration
    sorted_by_duration = sorted(stages, key=lambda x: x["avg_duration_seconds"], reverse=True)
    assert sorted_by_duration[0]["stage_name"] == "Deploy copsoie OIE Dev"
    assert sorted_by_duration[0]["avg_duration_seconds"] == 1200.0

from datetime import datetime, timedelta, timezone

from core.db import build_analysis_summary


def test_summary_filters_small_normal_tasks_and_calculates_deltas():
    now = datetime.now(timezone.utc)
    rows = []
    for days, duration in [(3, 240), (10, 150)]:
        rows.append({"pipeline_name": "backend-ci", "stage_name": "Build", "task_name": "npm install", "duration_seconds": duration, "result": "succeeded", "retry_count": 0, "start_time": now - timedelta(days=days)})
        rows.append({"pipeline_name": "backend-ci", "stage_name": "Build", "task_name": "checkout", "duration_seconds": 3, "result": "succeeded", "retry_count": 0, "start_time": now - timedelta(days=days)})
    summary = build_analysis_summary(rows)
    task = summary["stages"][0]["tasks"][0]
    assert task["name"] == "npm install"
    assert task["delta_vs_prior_week_pct"] == 60.0
"""Tests for pipeline, status, and date range filters on recent runs and summary metrics."""
from datetime import datetime, timedelta, timezone
import pytest
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder, run_row


def test_runs_filters_are_bound_in_order(monkeypatch):
    rec = Recorder(monkeypatch)
    PipelineRepository().runs(3, 1, 10, "failed", 7)
    count_query, count_params = rec.calls[0]
    assert count_params[0] == 3 and count_params[1] == "failed" and isinstance(count_params[2], datetime)
    assert "r.pipeline_id=?" in count_query and "r.result=?" in count_query and "r.start_time >= ?" in count_query
    items_params = rec.calls[1][1]
    assert items_params[:3] == count_params and items_params[3:] == (0, 10)


def test_summary_recomputes_every_metric_from_rows(monkeypatch):
    rows = [
        run_row(1, "succeeded", 100, 10),
        run_row(2, "partiallySucceeded", 200, 20),
        run_row(3, "failed", 300, 30),
        run_row(4, "canceled", 400, 40),
        run_row(5, "failed", 1000, 50, degraded=1),
    ]
    Recorder(monkeypatch, all_rows=lambda q: rows if "from dbo.pipeline_runs r where" in q.lower() else [])
    s = PipelineRepository().summary(None, 90)
    assert s["total_runs"] == 5
    assert s["successful_runs"] == 2 and s["failed_runs"] == 2
    assert s["success_rate_pct"] == 40.0 and s["failure_rate_pct"] == 40.0
    assert s["degraded_runs"] == 1
    assert s["average_duration_seconds"] == 400.0
    assert s["p90_duration_seconds"] == 760.0
    assert s["average_queue_seconds"] == 30.0


def test_summary_pipeline_filter_is_bound_as_a_parameter(monkeypatch):
    rec = Recorder(monkeypatch)
    PipelineRepository().summary(7, 30)
    for query, params in rec.calls:
        assert 7 in params and "r.pipeline_id = ?" in query
    rec.calls.clear()
    PipelineRepository().summary(None, 30)
    assert all("pipeline_id = ?" not in q and len(p) == 1 for q, p in rec.calls)


@pytest.mark.parametrize("days", [1, 30, 90, 730])
def test_window_start_matches_requested_days(monkeypatch, days):
    rec = Recorder(monkeypatch)
    PipelineRepository().summary(None, days)
    start = rec.calls[0][1][0]
    expected = datetime.now(timezone.utc) - timedelta(days=days)
    assert abs((start - expected).total_seconds()) < 5

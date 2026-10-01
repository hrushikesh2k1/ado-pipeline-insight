"""Tests for daily build duration average, P90 percentiles, and trend aggregations."""
from datetime import datetime, timedelta, timezone
import pytest
from app.repositories.pipeline_repository import PipelineRepository, daily_build_trend
from tests.conftest import Recorder, build


def test_daily_trend_is_the_average_build_duration_per_day_and_pipeline():
    rows = [
        build(1, 1, 1, 100),
        build(2, 1, 1, 300, hour=17),
        build(3, 1, 2, 50),
        build(4, 2, 1, 60),
        build(5, 2, 1, None),
        {**build(6, 2, 1, 999), "run_date": None},
    ]
    assert daily_build_trend(rows) == [
        {"run_date": "2026-09-01", "pipeline_id": 1, "pipeline_name": "pipe-1", "avg_duration_seconds": 200.0, "p90_duration_seconds": 280.0},
        {"run_date": "2026-09-01", "pipeline_id": 2, "pipeline_name": "pipe-2", "avg_duration_seconds": 50.0, "p90_duration_seconds": 50.0},
        {"run_date": "2026-09-02", "pipeline_id": 1, "pipeline_name": "pipe-1", "avg_duration_seconds": 60.0, "p90_duration_seconds": 60.0},
    ]


def test_daily_trend_is_not_an_average_of_stage_averages():
    """Regression: the old view-based query averaged per-stage averages, so a day with two builds of 1960s and 5329s
    showed ~1703s (a mean stage duration) instead of the mean build duration."""
    rows = [build(1, 30, 3010, 1960), build(2, 30, 3010, 5329)]
    day = daily_build_trend(rows)[0]
    assert day["avg_duration_seconds"] == 3644.5
    assert day["p90_duration_seconds"] == 4992.1


def test_daily_trend_reconciles_with_the_overall_average():
    rows = [build(i, 1 + i % 5, 1 + i % 2, 100 + i * 7) for i in range(40)]
    daily = daily_build_trend(rows)
    counts = {}
    for r in rows:
        counts[(r["run_date"].date().isoformat(), r["pipeline_id"])] = counts.get((r["run_date"].date().isoformat(), r["pipeline_id"]), 0) + 1
    weighted = sum(d["avg_duration_seconds"] * counts[(d["run_date"], d["pipeline_id"])] for d in daily) / len(rows)
    overall = sum(r["duration_seconds"] for r in rows) / len(rows)
    assert weighted == pytest.approx(overall, abs=0.05)


def test_daily_trend_of_nothing_is_empty():
    assert daily_build_trend([]) == []
    assert daily_build_trend([build(1, 1, 1, None)]) == []


def test_trends_wires_build_rows_into_the_daily_trend(monkeypatch):
    Recorder(monkeypatch, all_rows=lambda q: [build(1, 1, 1, 100)] if "DATEDIFF" in q else [])
    result = PipelineRepository().trends(None, 30)
    assert len(result["build_trend"]) == 1 and result["daily_trend"][0]["avg_duration_seconds"] == 100.0 and result["stage_trend"] == []


def test_trends_bind_the_pipeline_filter_only_when_given(monkeypatch):
    rec = Recorder(monkeypatch)
    PipelineRepository().trends(9, 30)
    assert all(9 in p and len(p) == 2 for _, p in rec.calls)
    rec.calls.clear()
    PipelineRepository().trends(None, 30)
    assert all(len(p) == 1 for _, p in rec.calls)


def test_stage_trend_ignores_degraded_placeholder_runs(monkeypatch):
    rec = Recorder(monkeypatch)
    PipelineRepository().trends(None, 30)
    stage_query = next(q for q, _ in rec.calls if "pipeline_stages" in q)
    assert "r.is_degraded=0" in stage_query.replace(" ", "")

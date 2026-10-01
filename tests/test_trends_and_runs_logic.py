"""Data-correctness tests for the summary, recent-runs and trend calculations (no database needed).

A recording fake replaces the SQL layer, so these tests pin down (a) the arithmetic the API performs on rows and
(b) the exact parameters bound to each query. SQL semantics itself is verified against the real database by
quality_gate/functional_tests.
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.repositories.pipeline_repository as repo_module
from app.repositories.pipeline_repository import PipelineRepository, daily_build_trend, percentile

T0 = datetime(2026, 9, 1, 8, 0, 0)


def run_row(run_id, result, duration, queue_wait=10, degraded=0, start=T0):
    return {"run_id": run_id, "pipeline_id": 1, "queue_time": start - timedelta(seconds=queue_wait), "start_time": start,
            "finish_time": start + timedelta(seconds=duration), "result": result, "is_degraded": degraded, "data_quality": "complete",
            "duration_seconds": duration}


class Recorder:
    def __init__(self, monkeypatch, all_rows=None, one_row=None):
        self.calls = []
        self.all_rows = all_rows if all_rows is not None else []
        self.one_row = one_row if one_row is not None else {"total": 0, "ok": 1}
        monkeypatch.setattr(repo_module, "fetch_all", self._all)
        monkeypatch.setattr(repo_module, "fetch_one", self._one)

    def _all(self, query, params=()):
        self.calls.append((query, tuple(params)))
        return self.all_rows(query) if callable(self.all_rows) else self.all_rows

    def _one(self, query, params=()):
        self.calls.append((query, tuple(params)))
        return self.one_row


# ---------------------------------------------------------------- summary


def test_summary_recomputes_every_metric_from_rows(monkeypatch):
    rows = [run_row(1, "succeeded", 100, 10), run_row(2, "partiallySucceeded", 200, 20), run_row(3, "failed", 300, 30),
            run_row(4, "canceled", 400, 40), run_row(5, "failed", 1000, 50, degraded=1)]
    Recorder(monkeypatch, all_rows=lambda q: rows if "from dbo.pipeline_runs r where" in q.lower() else [])
    s = PipelineRepository().summary(None, 90)
    assert s["total_runs"] == 5
    assert s["successful_runs"] == 2 and s["failed_runs"] == 2
    assert s["success_rate_pct"] == 40.0 and s["failure_rate_pct"] == 40.0
    assert s["degraded_runs"] == 1
    assert s["average_duration_seconds"] == 400.0
    assert s["p90_duration_seconds"] == 760.0
    assert s["average_queue_seconds"] == 30.0


def test_summary_of_an_empty_window_is_zeroes_not_errors(monkeypatch):
    Recorder(monkeypatch)
    s = PipelineRepository().summary(None, 30)
    assert s["total_runs"] == 0 and s["success_rate_pct"] == 0 and s["failure_rate_pct"] == 0
    assert s["average_duration_seconds"] is None and s["p90_duration_seconds"] is None and s["stages"] == []


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


# ---------------------------------------------------------------- recent runs


def test_runs_paging_math(monkeypatch):
    rec = Recorder(monkeypatch, one_row={"total": 130})
    result = PipelineRepository().runs(None, 3, 25, None)
    assert result["total_count"] == 130 and result["total_pages"] == 6 and result["page"] == 3 and result["page_size"] == 25
    items_query, items_params = rec.calls[-1]
    assert items_params[-2:] == (50, 25), "OFFSET must be (page-1)*page_size and FETCH must be page_size"
    assert "ORDER BY r.start_time DESC" in items_query


def test_runs_filters_are_bound_in_order(monkeypatch):
    rec = Recorder(monkeypatch)
    PipelineRepository().runs(3, 1, 10, "failed", 7)
    count_query, count_params = rec.calls[0]
    assert count_params[0] == 3 and count_params[1] == "failed" and isinstance(count_params[2], datetime)
    assert "r.pipeline_id=?" in count_query and "r.result=?" in count_query and "r.start_time >= ?" in count_query
    items_params = rec.calls[1][1]
    assert items_params[:3] == count_params and items_params[3:] == (0, 10)


@pytest.mark.parametrize("page,size,expected_page,expected_size", [(0, 10, 1, 10), (-4, 10, 1, 10), (1, 0, 1, 1), (1, 5000, 1, 1000)])
def test_runs_clamps_paging_inputs(monkeypatch, page, size, expected_page, expected_size):
    rec = Recorder(monkeypatch)
    result = PipelineRepository().runs(None, page, size, None)
    assert result["page"] == expected_page and result["page_size"] == expected_size
    assert rec.calls[-1][1][-2:] == ((expected_page - 1) * expected_size, expected_size)


def test_runs_with_no_rows_still_reports_one_page(monkeypatch):
    Recorder(monkeypatch, one_row={"total": 0})
    assert PipelineRepository().runs(None, 1, 100, None)["total_pages"] == 1


def test_runs_last_page_is_counted(monkeypatch):
    Recorder(monkeypatch, one_row={"total": 101})
    assert PipelineRepository().runs(None, 1, 100, None)["total_pages"] == 2


# ---------------------------------------------------------------- trends


def build(run_id, day, pipeline, duration, hour=9):
    return {"run_id": run_id, "build_number": str(run_id), "run_date": datetime(2026, 9, day, hour, 0), "pipeline_id": pipeline,
            "pipeline_name": f"pipe-{pipeline}", "duration_seconds": duration, "result": "succeeded"}


def test_daily_trend_is_the_average_build_duration_per_day_and_pipeline():
    rows = [build(1, 1, 1, 100), build(2, 1, 1, 300, hour=17), build(3, 1, 2, 50), build(4, 2, 1, 60), build(5, 2, 1, None),
            {**build(6, 2, 1, 999), "run_date": None}]
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


# ---------------------------------------------------------------- run detail and helpers


def test_run_analysis_finds_the_longest_records_and_counts_failures(monkeypatch):
    run = {**run_row(5, "failed", 40, 10), "pipeline_name": "CI", "organization_name": "o", "project_name": "p", "source_branch": "main",
           "source_version": "abc", "requested_by": "dev", "build_number": "1"}
    hierarchy = {"stages": [{"duration_seconds": 30, "result": "failed"}, {"duration_seconds": 10, "result": "succeeded"}],
                 "jobs": [{"duration_seconds": 5.5, "result": "succeeded"}, {"duration_seconds": 25, "result": "Failed"}],
                 "tasks": [{"duration_seconds": None, "result": None}, {"duration_seconds": 2.25, "result": "succeeded"}]}
    Recorder(monkeypatch, one_row=run)
    repo = PipelineRepository()
    monkeypatch.setattr(repo, "timeline", lambda run_id: {"run_id": run_id, **hierarchy})
    m = repo.run_analysis(5)["metrics"]
    assert m["run_duration_seconds"] == 40.0 and m["queue_seconds"] == 10.0
    assert m["longest_stage"]["duration_seconds"] == 30 and m["longest_job"]["duration_seconds"] == 25
    assert m["failed_records"] == 2
    assert m["stage_duration_total_seconds"] == 40.0 and m["job_duration_total_seconds"] == 30.5 and m["task_duration_total_seconds"] == 2.25
    assert (m["stage_count"], m["job_count"], m["task_count"]) == (2, 2, 2)


def test_logs_join_failure_excerpts_or_explain_their_absence(monkeypatch):
    Recorder(monkeypatch, all_rows=[{"task_name": "a", "failure_log_excerpt": "one", "result": "failed"},
                                    {"task_name": "b", "failure_log_excerpt": None, "result": "failed"},
                                    {"task_name": "c", "failure_log_excerpt": "two", "result": "failed"}])
    assert PipelineRepository().logs(5)["log"] == "one\n\ntwo"
    Recorder(monkeypatch, all_rows=[])
    assert "No detailed failure log" in PipelineRepository().logs(5)["log"]


def test_percentile_edges():
    assert percentile([], 0.9) is None
    assert percentile([7], 0.9) == 7
    assert percentile([1, 2, 3, 4], 0) == 1 and percentile([1, 2, 3, 4], 1) == 4
    assert percentile([4, 1, 3, 2], 0.5) == 2.5


def test_every_query_binds_exactly_as_many_values_as_it_has_placeholders(monkeypatch):
    run = {**run_row(5, "succeeded", 40), "pipeline_name": "CI", "organization_name": "o", "project_name": "p", "source_branch": "m",
           "source_version": "v", "requested_by": "d", "build_number": "1", "total": 3}
    rec = Recorder(monkeypatch, one_row=run)
    repo = PipelineRepository()
    for call in (lambda: repo.list_options(), lambda: repo.summary(None, 30), lambda: repo.summary(3, 30),
                 lambda: repo.runs(None, 1, 10, None), lambda: repo.runs(3, 2, 10, "failed", 7), lambda: repo.trends(None, 30),
                 lambda: repo.trends(3, 30), lambda: repo.recommendations(3, 50), lambda: repo.timeline(5),
                 lambda: repo.run_analysis(5), lambda: repo.logs(5), lambda: repo.pools(30)):
        call()
    assert len(rec.calls) >= 20
    for query, params in rec.calls:
        assert query.count("?") == len(params), f"{query[:90]!r} has {query.count('?')} placeholders but {len(params)} bound values"

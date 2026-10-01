"""Do the dashboard numbers agree with each other and with the runs behind them? (live API, read-only)

Every test recomputes a number from the raw run list and compares it to what the summary / trend / detail endpoints report.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import ALLOWED_RESULTS, WINDOW_DAYS, finished, pages, percentile

SUCCESS = {"succeeded", "partiallySucceeded"}


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def secs(run: dict) -> float:
    return (ts(run["finish_time"]) - ts(run["start_time"])).total_seconds()


# ------------------------------------------------------------------ summary cards


@pytest.mark.func(severity="high", area="Summary", title="Summary run counts equal the runs behind them",
                  fix="total_runs / successful_runs / failed_runs must be recomputable from /runs (finished runs only).")
def test_summary_counts_match_runs(data):
    runs, s = finished(data["runs"]), data["summary"]
    assert s["total_runs"] == len(runs), f"summary says {s['total_runs']} runs, the run list has {len(runs)}"
    assert s["successful_runs"] == sum(r["result"] in SUCCESS for r in runs)
    assert s["failed_runs"] == sum(r["result"] == "failed" for r in runs)
    assert s["degraded_runs"] == sum(bool(r["is_degraded"]) for r in runs)


@pytest.mark.func(severity="high", area="Summary", title="Success and failure rates are correct percentages",
                  fix="Rates must equal count*100/total rounded to 2 decimals.")
def test_summary_rates(data):
    s = data["summary"]
    total = s["total_runs"]
    assert s["success_rate_pct"] == round(s["successful_runs"] * 100 / total, 2)
    assert s["failure_rate_pct"] == round(s["failed_runs"] * 100 / total, 2)
    assert s["success_rate_pct"] + s["failure_rate_pct"] <= 100.0 + 0.01


@pytest.mark.func(severity="high", area="Summary", title="Average and p90 build duration match the run durations",
                  fix="Durations must be finish-start of finished runs; p90 uses linear interpolation.")
def test_summary_durations(data):
    durations = [r["duration_seconds"] for r in finished(data["runs"]) if r["duration_seconds"] is not None]
    s = data["summary"]
    assert s["average_duration_seconds"] == pytest.approx(sum(durations) / len(durations), abs=0.01)
    assert s["p90_duration_seconds"] == pytest.approx(percentile(durations, 0.9), abs=0.01)
    assert s["p90_duration_seconds"] >= s["average_duration_seconds"] * 0.5


@pytest.mark.func(severity="high", area="Summary", title="Average queue time matches queue_time to start_time",
                  fix="Queue seconds are start_time minus queue_time for runs that have both.")
def test_summary_queue_time(data):
    waits = [(ts(r["start_time"]) - ts(r["queue_time"])).total_seconds() for r in finished(data["runs"]) if r["queue_time"]]
    if not waits:
        pytest.skip("no run has a queue_time")
    assert data["summary"]["average_queue_seconds"] == pytest.approx(sum(waits) / len(waits), abs=0.01)
    assert all(w >= 0 for w in waits), "a run started before it was queued"


@pytest.mark.func(severity="medium", area="Summary", title="Stage statistics are internally consistent",
                  fix="failed_count cannot exceed samples; durations cannot be negative.")
def test_summary_stage_rows(data):
    for stage in data["summary"]["stages"]:
        assert stage["stage_name"]
        assert 1 <= stage["samples"] and 0 <= stage["failed_count"] <= stage["samples"]
        assert stage["avg_duration_seconds"] is None or stage["avg_duration_seconds"] >= 0


@pytest.mark.func(severity="high", area="Summary", title="Per-pipeline summaries add up to the overall summary",
                  fix="Every pipeline with runs must be selectable; totals per pipeline must sum to the overall total.")
def test_pipeline_summaries_sum_to_overall(api, data):
    pipeline_ids = sorted({r["pipeline_id"] for r in data["runs"]})
    listed = {p["pipeline_id"] for p in data["options"]["pipelines"]}
    assert set(pipeline_ids) <= listed, f"pipelines with runs but missing from the selector: {sorted(set(pipeline_ids) - listed)}"
    per = {pid: api.get("/api/v1/summary", days=WINDOW_DAYS, pipeline_id=pid) for pid in pipeline_ids}
    assert sum(s["total_runs"] for s in per.values()) == data["summary"]["total_runs"]
    assert sum(s["failed_runs"] for s in per.values()) == data["summary"]["failed_runs"]
    for pid, s in per.items():
        mine = finished([r for r in data["runs"] if r["pipeline_id"] == pid])
        assert s["total_runs"] == len(mine), f"pipeline {pid}: summary {s['total_runs']} vs runs {len(mine)}"


# ------------------------------------------------------------------ recent runs


@pytest.mark.func(severity="high", area="Recent runs", title="Recent runs are newest first with unique ids",
                  fix="ORDER BY start_time DESC and a primary key on run_id.")
def test_runs_are_newest_first_and_unique(data):
    runs = data["runs"]
    ids = [r["run_id"] for r in runs]
    assert len(ids) == len(set(ids)), "duplicate run ids in the list"
    starts = [r["start_time"] or "" for r in runs]
    assert starts == sorted(starts, reverse=True), "runs are not sorted newest-first"
    assert len(runs) == data["total_count"]


@pytest.mark.func(severity="high", area="Recent runs", title="Every run's duration equals finish minus start",
                  fix="duration_seconds must be DATEDIFF(second, start_time, finish_time); finish cannot precede start.")
def test_run_durations_are_consistent(data):
    for r in finished(data["runs"]):
        assert secs(r) >= 0, f"run {r['run_id']} finished before it started"
        assert r["duration_seconds"] is not None and abs(secs(r) - r["duration_seconds"]) <= 1.0, f"run {r['run_id']} duration mismatch"


@pytest.mark.func(severity="medium", area="Recent runs", title="Run rows carry valid results and identifiers",
                  fix="result must be a known Azure DevOps result; every run needs a pipeline and a build number or id.")
def test_run_fields_are_valid(data):
    for r in data["runs"]:
        assert r["result"] in ALLOWED_RESULTS, f"run {r['run_id']} has unknown result {r['result']!r}"
        assert r["pipeline_name"] and r["pipeline_id"] and (r["build_number"] or r["run_id"])
        assert r["start_time"] is None or r["queue_time"] is None or ts(r["queue_time"]) <= ts(r["start_time"])


@pytest.mark.func(severity="high", area="Recent runs", title="Paging returns disjoint pages that add up to the total",
                  fix="OFFSET/FETCH must be (page-1)*size and total_pages must be ceil(total/size).")
def test_paging_is_consistent(api, data):
    size = 25
    p1 = api.get("/api/v1/runs", days=WINDOW_DAYS, page=1, page_size=size)
    assert p1["total_count"] == data["total_count"] and p1["total_pages"] == pages(data["total_count"], size)
    assert [r["run_id"] for r in p1["items"]] == [r["run_id"] for r in data["runs"][:size]]
    if p1["total_pages"] > 1:
        p2 = api.get("/api/v1/runs", days=WINDOW_DAYS, page=2, page_size=size)
        assert [r["run_id"] for r in p2["items"]] == [r["run_id"] for r in data["runs"][size:size * 2]]
        assert not {r["run_id"] for r in p1["items"]} & {r["run_id"] for r in p2["items"]}
    last = api.get("/api/v1/runs", days=WINDOW_DAYS, page=p1["total_pages"], page_size=size)
    assert len(last["items"]) == data["total_count"] - (p1["total_pages"] - 1) * size
    assert api.get("/api/v1/runs", days=WINDOW_DAYS, page=p1["total_pages"] + 1, page_size=size)["items"] == []


@pytest.mark.func(severity="high", area="Recent runs", title="Run filters (pipeline, status, days) return exactly the matching runs",
                  fix="Each filter must be applied in SQL and reflected in total_count.")
def test_run_filters(api, data):
    runs = data["runs"]
    failed = api.get("/api/v1/runs", days=WINDOW_DAYS, status="failed", page_size=1000)
    assert failed["total_count"] == sum(r["result"] == "failed" for r in runs) == data["summary"]["failed_runs"]
    assert all(r["result"] == "failed" for r in failed["items"])
    pid = runs[0]["pipeline_id"]
    mine = api.get("/api/v1/runs", days=WINDOW_DAYS, pipeline_id=pid, page_size=1000)
    assert mine["total_count"] == sum(r["pipeline_id"] == pid for r in runs)
    assert {r["pipeline_id"] for r in mine["items"]} == {pid}
    week = api.get("/api/v1/runs", days=7, page_size=1000)
    cutoff = datetime.utcnow() - timedelta(days=7, minutes=5)
    assert all(ts(r["start_time"]) >= cutoff for r in week["items"] if r["start_time"])
    assert week["total_count"] <= data["total_count"]


# ------------------------------------------------------------------ build duration trend


@pytest.mark.func(severity="high", area="Build duration trend", title="Every run appears once in the per-run trend with the same result and duration",
                  fix="build_trend must be the same runs as /runs, ordered oldest to newest.")
def test_build_trend_matches_runs(data):
    build, runs = data["trends"]["build_trend"], {r["run_id"]: r for r in data["runs"]}
    assert len(build) == data["total_count"], f"trend has {len(build)} runs, run list has {data['total_count']}"
    assert {b["run_id"] for b in build} == set(runs)
    for b in build:
        r = runs[b["run_id"]]
        assert b["result"] == r["result"] and b["pipeline_id"] == r["pipeline_id"] and b["duration_seconds"] == r["duration_seconds"], b["run_id"]
    dates = [b["run_date"] for b in build]
    assert dates == sorted(dates), "per-run trend is not in chronological order"


@pytest.mark.func(severity="high", area="Build duration trend", title="Daily average equals the mean build duration of that day's runs",
                  fix="Compute the daily trend from run durations (per day and pipeline), not from per-stage view rows.")
def test_daily_trend_is_mean_build_duration(data):
    groups: dict[tuple[str, int], list[float]] = {}
    for b in data["trends"]["build_trend"]:
        if b["duration_seconds"] is not None and b["run_date"]:
            groups.setdefault((b["run_date"][:10], b["pipeline_id"]), []).append(b["duration_seconds"])
    daily = {(str(d["run_date"])[:10], d["pipeline_id"]): d for d in data["trends"]["daily_trend"]}
    assert set(daily) == set(groups), f"days/pipelines differ: missing {sorted(set(groups) - set(daily))[:3]}, extra {sorted(set(daily) - set(groups))[:3]}"
    for key, values in groups.items():
        assert daily[key]["avg_duration_seconds"] == pytest.approx(sum(values) / len(values), abs=0.01), \
            f"{key}: daily average {daily[key]['avg_duration_seconds']} but mean build duration is {sum(values) / len(values):.2f}"
        assert daily[key]["p90_duration_seconds"] == pytest.approx(percentile(values, 0.9), abs=0.01), f"{key}: p90 differs"


@pytest.mark.func(severity="high", area="Build duration trend", title="Daily trend reconciles with the summary average",
                  fix="The count-weighted mean of the daily averages must equal the summary's average duration.")
def test_daily_trend_reconciles_with_summary(data):
    counts: dict[tuple[str, int], int] = {}
    for b in data["trends"]["build_trend"]:
        if b["duration_seconds"] is not None and b["run_date"]:
            key = (b["run_date"][:10], b["pipeline_id"])
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    weighted = sum(d["avg_duration_seconds"] * counts[(str(d["run_date"])[:10], d["pipeline_id"])] for d in data["trends"]["daily_trend"]) / total
    assert weighted == pytest.approx(data["summary"]["average_duration_seconds"], abs=0.5)


@pytest.mark.func(severity="medium", area="Build duration trend", title="Stage trend only contains real stages on days that had runs",
                  fix="stage_trend rows must fall on run days and exclude degraded placeholder stages.")
def test_stage_trend_is_sane(data):
    run_days = {b["run_date"][:10] for b in data["trends"]["build_trend"] if b["run_date"]}
    for row in data["trends"]["stage_trend"]:
        assert str(row["run_date"])[:10] in run_days, f"stage trend has a day with no runs: {row['run_date']}"
        assert row["stage_name"] and row["avg_duration_seconds"] >= 0
        if not data["summary"]["degraded_runs"]:
            assert row["stage_name"] != "summary", "fallback placeholder stage leaked into the trend"


# ------------------------------------------------------------------ selectors, run detail, recommendations, health


@pytest.mark.func(severity="medium", area="Selectors", title="Organization, project and pipeline selectors are consistent",
                  fix="options.organizations/projects must be the distinct values of options.pipelines.")
def test_options_are_consistent(data):
    o = data["options"]
    assert o["organizations"] == sorted({p["organization_name"] for p in o["pipelines"] if p["organization_name"]})
    assert o["projects"] == sorted({p["project_name"] for p in o["pipelines"] if p["project_name"]})
    assert len({p["pipeline_id"] for p in o["pipelines"]}) == len(o["pipelines"]), "duplicate pipeline ids in selector"


@pytest.mark.func(severity="high", area="Run detail", title="Run detail agrees with the run list and its own hierarchy",
                  fix="analysis.run and metrics must be derived from the same run row and stage/job/task records.")
def test_run_detail_matches_list(api, data):
    for listed in data["runs"][:2]:
        a = api.get(f"/api/v1/runs/{listed['run_id']}/analysis")
        t = api.get(f"/api/v1/runs/{listed['run_id']}/timeline")
        assert a["run"]["run_id"] == listed["run_id"] and a["run"]["result"] == listed["result"]
        assert a["run"]["duration_seconds"] == listed["duration_seconds"]
        m = a["metrics"]
        assert (m["stage_count"], m["job_count"], m["task_count"]) == (len(a["stages"]), len(a["jobs"]), len(a["tasks"]))
        assert (len(t["stages"]), len(t["jobs"]), len(t["tasks"])) == (m["stage_count"], m["job_count"], m["task_count"])
        failed = [x for level in ("stages", "jobs", "tasks") for x in a[level] if str(x.get("result") or "").lower() == "failed"]
        assert m["failed_records"] == len(failed)
        if a["stages"]:
            longest = max((s.get("duration_seconds") or 0) for s in a["stages"])
            assert m["longest_stage"]["duration_seconds"] == longest
        for level in ("stages", "jobs", "tasks"):
            assert all((x.get("duration_seconds") or 0) >= 0 for x in a[level]), f"negative {level} duration in run {listed['run_id']}"
        assert isinstance(api.get(f"/api/v1/runs/{listed['run_id']}/logs")["log"], str)


@pytest.mark.func(severity="low", area="Run detail", title="An unknown run returns 404, not a server error",
                  fix="run_analysis must raise ValueError for a missing run.")
def test_unknown_run_is_404(api):
    r = api.raw("/api/v1/runs/2000000000/analysis")
    assert r.status_code == 404


@pytest.mark.func(severity="medium", area="Recommendations", title="Stored recommendations have valid shape",
                  fix="category and severity must be from the allowed sets; text fields must be non-empty.")
def test_recommendations_shape(api, data):
    for p in data["options"]["pipelines"][:5]:
        body = api.get(f"/api/v1/pipelines/{p['pipeline_id']}/recommendations")
        assert body["pipeline_id"] == p["pipeline_id"] and isinstance(body["findings"], list)
        for f in body["findings"]:
            assert f["severity"] in {"low", "medium", "high"}
            assert f["category"] in {"queue_capacity", "flaky_step", "regression", "bottleneck", "parallelization_opportunity",
                                     "caching_opportunity", "other"}
            assert f["recommendation"] and f["evidence"] and f["stage_name"]


@pytest.mark.func(severity="high", area="Health", title="Health endpoint reports the database as reachable",
                  fix="Check SQL connectivity and the SQL_CONNECTION_STRING app setting.")
def test_health(api):
    body = api.get("/api/v1/health")
    assert body == {"status": "ok", "database": "ok"}

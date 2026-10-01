"""Reconcile the dashboard with the database itself, using independent SELECT queries (read-only).

Skipped unless database credentials are available (see conftest.py). This is the layer that proves the SQL in the API,
including the views, returns what the tables actually contain.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import WINDOW_DAYS

SUCCESS_SQL = "('succeeded','partiallySucceeded')"


def cutoffs(minutes: int = 5):
    now = datetime.utcnow()
    edge = now - timedelta(days=WINDOW_DAYS)
    return edge - timedelta(minutes=minutes), edge + timedelta(minutes=minutes)


def bounded(db, sql: str):
    """Row count for the window, as (upper, lower) around the window edge to tolerate clock drift between calls."""
    early, late = cutoffs()
    return db.scalar(sql, early), db.scalar(sql, late)


@pytest.mark.func(severity="high", area="DB reconciliation", title="Summary run counts equal the database counts",
                  fix="Compare the API queries in app/repositories/pipeline_repository.py with the table contents.")
def test_summary_counts_equal_database(db, data):
    s = data["summary"]
    for label, extra, api_value in [("finished runs", "", s["total_runs"]),
                                    ("succeeded runs", f" AND result IN {SUCCESS_SQL}", s["successful_runs"]),
                                    ("failed runs", " AND result = 'failed'", s["failed_runs"])]:
        upper, lower = bounded(db, f"SELECT COUNT(*) FROM dbo.pipeline_runs WHERE start_time >= %s AND finish_time IS NOT NULL{extra}")
        assert lower <= api_value <= upper or upper <= api_value <= lower, f"{label}: API {api_value}, database {lower}..{upper}"


@pytest.mark.func(severity="high", area="DB reconciliation", title="Average build duration equals the database average",
                  fix="duration_seconds must be DATEDIFF(second, start_time, finish_time) over finished runs.")
def test_average_duration_equals_database(db, data):
    early, late = cutoffs()
    sql = "SELECT AVG(CAST(DATEDIFF(second, start_time, finish_time) AS float)) FROM dbo.pipeline_runs WHERE start_time >= %s AND finish_time IS NOT NULL"
    a, b = db.scalar(sql, early), db.scalar(sql, late)
    api_value = data["summary"]["average_duration_seconds"]
    assert min(a, b) - 1 <= api_value <= max(a, b) + 1, f"API {api_value}, database {a:.2f}..{b:.2f}"


@pytest.mark.func(severity="high", area="DB reconciliation", title="The newest runs shown are the newest runs stored",
                  fix="Recent runs must be ordered by start_time descending across all pipelines.")
def test_recent_runs_are_the_latest_in_database(db, data):
    rows = db.query("SELECT TOP 10 run_id, start_time FROM dbo.pipeline_runs ORDER BY start_time DESC, run_id DESC")
    api_top = data["runs"][:10]
    assert [r["start_time"][:19] for r in api_top] == [str(x["start_time"]).replace(" ", "T")[:19] for x in rows]


@pytest.mark.func(severity="high", area="DB reconciliation", title="Daily trend equals the per-day average in the database",
                  fix="Group finished runs by CAST(start_time AS date) and pipeline; average DATEDIFF(second, start, finish).")
def test_daily_trend_equals_database(db, data):
    first_full_day = (datetime.utcnow() - timedelta(days=WINDOW_DAYS - 1)).date()
    rows = db.query("SELECT CAST(start_time AS date) d, pipeline_id, AVG(CAST(DATEDIFF(second, start_time, finish_time) AS float)) a "
                    "FROM dbo.pipeline_runs WHERE start_time >= %s AND finish_time IS NOT NULL GROUP BY CAST(start_time AS date), pipeline_id",
                    datetime.combine(first_full_day, datetime.min.time()))
    expected = {(str(r["d"]), r["pipeline_id"]): r["a"] for r in rows}
    daily = {(str(d["run_date"])[:10], d["pipeline_id"]): d["avg_duration_seconds"]
             for d in data["trends"]["daily_trend"] if str(d["run_date"])[:10] >= str(first_full_day)}
    assert set(daily) == set(expected), f"days differ: only in API {sorted(set(daily) - set(expected))[:3]}, only in DB {sorted(set(expected) - set(daily))[:3]}"
    for key, value in expected.items():
        assert daily[key] == pytest.approx(value, abs=0.02), f"{key}: API {daily[key]}, database {value:.2f}"


@pytest.mark.func(severity="high", area="DB integrity", title="No run finished before it started, and no duration is negative",
                  fix="Fix ingestion timestamps; re-ingest affected runs.")
def test_no_negative_times(db):
    assert db.scalar("SELECT COUNT(*) FROM dbo.pipeline_runs WHERE finish_time < start_time") == 0
    for table in ("pipeline_stages", "pipeline_jobs", "pipeline_tasks"):
        assert db.scalar(f"SELECT COUNT(*) FROM dbo.{table} WHERE duration_seconds < 0") == 0, table  # nosec B608 - fixed table names


@pytest.mark.func(severity="high", area="DB integrity", title="No orphaned stage/job/task rows and no runs without a pipeline",
                  fix="Restore foreign keys; delete orphaned child rows.")
def test_no_orphans(db):
    for table in ("pipeline_stages", "pipeline_jobs", "pipeline_tasks"):
        n = db.scalar(f"SELECT COUNT(*) FROM dbo.{table} t WHERE NOT EXISTS (SELECT 1 FROM dbo.pipeline_runs r WHERE r.run_id = t.run_id)")  # nosec B608 - fixed table names
        assert n == 0, f"{n} orphaned rows in {table}"
    assert db.scalar("SELECT COUNT(*) FROM dbo.pipeline_runs r WHERE NOT EXISTS (SELECT 1 FROM dbo.pipelines p WHERE p.pipeline_id = r.pipeline_id)") == 0


@pytest.mark.func(severity="medium", area="DB integrity", title="Degraded flag and data_quality agree, and stage keys are unique",
                  fix="is_degraded=1 must pair with data_quality='degraded'; upsert on (run_id, record_id).")
def test_flags_and_keys(db):
    assert db.scalar("SELECT COUNT(*) FROM dbo.pipeline_runs WHERE (is_degraded = 1 AND data_quality <> 'degraded') "
                     "OR (is_degraded = 0 AND data_quality = 'degraded')") == 0
    assert db.scalar("SELECT COUNT(*) FROM (SELECT run_id, record_id FROM dbo.pipeline_stages GROUP BY run_id, record_id HAVING COUNT(*) > 1) x") == 0


@pytest.mark.func(severity="medium", area="DB integrity", title="Complete runs have stage telemetry",
                  fix="Re-ingest runs that were stored without a timeline (Ingest History).")
def test_complete_runs_have_stages(db):
    n = db.scalar("SELECT COUNT(*) FROM dbo.pipeline_runs r WHERE r.is_degraded = 0 AND r.finish_time IS NOT NULL "
                  "AND NOT EXISTS (SELECT 1 FROM dbo.pipeline_stages s WHERE s.run_id = r.run_id)")
    assert n == 0, f"{n} finished, non-degraded runs have no stage rows"


@pytest.mark.func(severity="medium", area="DB integrity", title="Stage durations match their timestamps and fit inside the run",
                  fix="Re-ingest with a real Azure DevOps timeline; stale 0-5 second placeholder durations must not survive.")
def test_stage_durations_are_credible(db):
    mismatched = db.scalar("SELECT COUNT(*) FROM dbo.pipeline_stages WHERE is_degraded = 0 AND start_time IS NOT NULL AND finish_time IS NOT NULL "
                           "AND duration_seconds IS NOT NULL AND ABS(duration_seconds - DATEDIFF(second, start_time, finish_time)) > 1")
    assert mismatched == 0, f"{mismatched} stage rows whose duration_seconds differs from finish-start"
    too_long = db.scalar("SELECT COUNT(*) FROM dbo.pipeline_stages s JOIN dbo.pipeline_runs r ON r.run_id = s.run_id "
                         "WHERE s.is_degraded = 0 AND r.finish_time IS NOT NULL AND s.duration_seconds > DATEDIFF(second, r.start_time, r.finish_time) + 60")
    assert too_long == 0, f"{too_long} stages last longer than the run that contains them"

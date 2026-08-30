from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from core.models import TimelineMetric


class AlertRepository:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    def _connect(self):
        try:
            import pyodbc
        except ImportError as error:
            raise RuntimeError("pyodbc is not available in the function runtime. Ensure dependency install succeeded.") from error
        return pyodbc.connect(self.connection_string)

    def upsert_metrics(self, metrics: Iterable[TimelineMetric]) -> None:
        metrics = list(metrics)
        if not metrics:
            return
        with self._connect() as connection:
            cursor = connection.cursor()
            first = metrics[0]
            cursor.execute("EXEC dbo.UpsertPipeline @pipeline_id=?, @pipeline_name=?", first.pipeline_id, first.pipeline_name)
            cursor.execute(
                """MERGE dbo.pipeline_runs AS target USING (SELECT ? AS run_id) AS source ON target.run_id = source.run_id
                   WHEN NOT MATCHED THEN INSERT (run_id, pipeline_id, queue_time, start_time, finish_time, result)
                   VALUES (?, ?, ?, ?, ?, ?);""",
                first.run_id, first.run_id, first.pipeline_id, first.queue_time, first.start_time, first.finish_time, first.result,
            )
            for metric in metrics:
                table = {"stage": "pipeline_stages", "job": "pipeline_jobs", "task": "pipeline_tasks"}[metric.level]
                names = {
                    "stage": ("stage_name", [metric.stage_name]),
                    "job": ("stage_name, job_name", [metric.stage_name, metric.job_name]),
                    "task": ("stage_name, job_name, task_name", [metric.stage_name, metric.job_name, metric.task_name]),
                }[metric.level]
                cursor.execute(
                    f"""MERGE dbo.{table} AS target USING (SELECT ? AS run_id, ? AS record_id) AS source
                        ON target.run_id = source.run_id AND target.record_id = source.record_id
                        WHEN NOT MATCHED THEN INSERT (run_id, record_id, {names[0]}, agent_name, start_time, finish_time, duration_seconds, result, retry_count, failure_log_excerpt)
                        VALUES (?, ?, {', '.join('?' for _ in names[1])}, ?, ?, ?, ?, ?, ?, ?);""",
                    metric.run_id, metric.record_id, metric.run_id, metric.record_id, *names[1], metric.agent_name,
                    metric.start_time, metric.finish_time, metric.duration_seconds, metric.result,
                    metric.retry_count, metric.failure_log_excerpt,
                )
            connection.commit()

    def get_pipeline_metrics(self, pipeline_id: int, days: int = 30) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT r.pipeline_id, p.pipeline_name, s.stage_name, j.job_name, t.task_name,
                   COALESCE(t.duration_seconds, j.duration_seconds, s.duration_seconds) AS duration_seconds,
                   COALESCE(t.result, j.result, s.result) AS result,
                   COALESCE(t.retry_count, j.retry_count, s.retry_count, 0) AS retry_count,
                   r.queue_time, COALESCE(t.start_time, j.start_time, s.start_time) AS start_time,
                   t.failure_log_excerpt
            FROM pipeline_runs r
            JOIN pipelines p ON p.pipeline_id = r.pipeline_id
            LEFT JOIN pipeline_stages s ON s.run_id = r.run_id
            LEFT JOIN pipeline_jobs j ON j.run_id = r.run_id AND j.stage_name = s.stage_name
            LEFT JOIN pipeline_tasks t ON t.run_id = r.run_id AND t.job_name = j.job_name
            WHERE r.pipeline_id = ? AND r.start_time >= ?
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            columns = [column[0] for column in cursor.execute(query, pipeline_id, start).description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def count_runs(self, pipeline_id: int, days: int = 30) -> int:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_id=? AND start_time>=?", pipeline_id, start).fetchval()

    def upsert_recommendations(self, pipeline_id: int, findings: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM ai_recommendations WHERE pipeline_id=?", pipeline_id)
            for finding in findings:
                cursor.execute(
                    """INSERT INTO ai_recommendations (pipeline_id, category, severity, stage_name, task_name, recommendation, evidence, generated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())""",
                    pipeline_id, finding["category"], finding["severity"], finding["stage_name"], finding.get("task_name"),
                    finding["recommendation"], finding["evidence"],
                )
            connection.commit()


def build_analysis_summary(rows: list[dict[str, Any]], window_days: int = 30) -> dict[str, Any]:
    """Aggregate rows into the deliberately small payload sent to Azure OpenAI."""
    if not rows:
        return {"pipeline": None, "window_days": window_days, "stages": []}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("stage_name"):
            grouped[row["stage_name"]].append(row)
    stages = []
    for stage_name, stage_rows in grouped.items():
        stage_durations = _durations(stage_rows)
        stage_average = _average(stage_durations)
        task_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in stage_rows:
            if row.get("task_name"):
                task_groups[row["task_name"]].append(row)
        tasks = []
        for task_name, task_rows in task_groups.items():
            stats = _stats(task_rows)
            stats["name"] = task_name
            stats["pct_of_parent_duration"] = round(100 * stats["avg_duration_s"] / stage_average, 1) if stage_average else 0
            if stats["pct_of_parent_duration"] >= 5 or stats["failure_rate_pct"] > 0 or stats["retry_rate_pct"] > 0:
                tasks.append(stats)
        stage_stats = _stats(stage_rows)
        stage_stats.update({"name": stage_name, "tasks": sorted(tasks, key=lambda item: item["avg_duration_s"], reverse=True)})
        stages.append(stage_stats)
    return {"pipeline": rows[0].get("pipeline_name"), "window_days": window_days, "stages": stages}


def _stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    durations = _durations(rows)
    latest = [row for row in rows if row.get("start_time") and row["start_time"] >= datetime.now(timezone.utc) - timedelta(days=7)]
    previous = [row for row in rows if row.get("start_time") and datetime.now(timezone.utc) - timedelta(days=14) <= row["start_time"] < datetime.now(timezone.utc) - timedelta(days=7)]
    current_average, previous_average = _average(_durations(latest)), _average(_durations(previous))
    delta = round((current_average - previous_average) / previous_average * 100, 1) if previous_average else 0
    return {
        "avg_duration_s": round(_average(durations), 1), "p90_duration_s": round(_percentile(durations, 0.9), 1),
        "delta_vs_prior_week_pct": delta,
        "failure_rate_pct": round(100 * sum(row.get("result") == "failed" for row in rows) / len(rows), 1),
        "retry_rate_pct": round(100 * sum((row.get("retry_count") or 0) > 0 for row in rows) / len(rows), 1),
        "avg_queue_time_s": 0,
    }


def _durations(rows: list[dict[str, Any]]) -> list[float]:
    return [float(row["duration_seconds"]) for row in rows if row.get("duration_seconds") is not None]


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * percentile))]
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
            raise RuntimeError(
                "pyodbc is not available in the function runtime. "
                "Ensure dependency install succeeded."
            ) from error

        # Normalize common SQL Server connection-string aliases.
        connection_string = self.connection_string
        connection_string = connection_string.replace("User ID=", "UID=")
        connection_string = connection_string.replace("Username=", "UID=")
        connection_string = connection_string.replace("Password=", "PWD=")

        try:
            return pyodbc.connect(connection_string, timeout=30)
        except Exception as error:
            raise RuntimeError(
                f"Unable to connect to SQL with configured ODBC settings. {error}"
            ) from error

    def upsert_metrics(self, metrics: Iterable[TimelineMetric]) -> None:
        metrics = list(metrics)

        if not metrics:
            return

        with self._connect() as connection:
            self._ensure_quality_columns(connection)
            self._ensure_pipeline_context_columns(connection)

            cursor = connection.cursor()
            first = metrics[0]

            # ---------------------------------------------------------
            # Determine whether this is real Azure DevOps telemetry
            # or degraded/fallback telemetry.
            # ---------------------------------------------------------

            run_is_degraded = any(
                metric.is_degraded
                for metric in metrics
            )

            # ---------------------------------------------------------
            # Make sure the pipeline exists
            # ---------------------------------------------------------

            cursor.execute(
                """
                EXEC dbo.UpsertPipeline
                    @pipeline_id=?,
                    @pipeline_name=?,
                    @organization_name=?,
                    @project_name=?
                """,
                first.pipeline_id,
                first.pipeline_name,
                first.organization_name,
                first.project_name,
            )

            cursor.execute(
                """
                UPDATE dbo.pipelines
                SET
                    pipeline_name = ?,
                    organization_name = COALESCE(
                        ?,
                        organization_name
                    ),
                    project_name = COALESCE(
                        ?,
                        project_name
                    )
                WHERE pipeline_id = ?
                """,
                first.pipeline_name,
                first.organization_name,
                first.project_name,
                first.pipeline_id,
            )

            # ---------------------------------------------------------
            # IMPORTANT:
            #
            # Azure DevOps build.startTime and build.finishTime are
            # the source of truth for the pipeline run timestamps.
            #
            # Do NOT preserve an older SQL timestamp.
            # ---------------------------------------------------------

            run_start_time = (
                first.run_start_time
                if first.run_start_time is not None
                else first.start_time
            )

            run_finish_time = (
                first.run_finish_time
                if first.run_finish_time is not None
                else first.finish_time
            )

            # ---------------------------------------------------------
            # Upsert pipeline_runs
            # ---------------------------------------------------------

            cursor.execute(
                """
                MERGE dbo.pipeline_runs AS target

                USING (
                    SELECT ? AS run_id
                ) AS source

                ON target.run_id = source.run_id

                WHEN MATCHED THEN
                    UPDATE SET
                        pipeline_id = ?,
                        source_branch = COALESCE(
                            ?,
                            target.source_branch
                        ),
                        source_version = COALESCE(
                            ?,
                            target.source_version
                        ),
                        requested_by = COALESCE(
                            ?,
                            target.requested_by
                        ),

                        -- Queue time can remain from the original
                        -- record if the new value is unavailable.
                        queue_time = COALESCE(
                            ?,
                            target.queue_time
                        ),

                        -- IMPORTANT:
                        -- Always replace old timestamps when the
                        -- ADO timeline supplies them.
                        start_time = ?,
                        finish_time = ?,

                        result = COALESCE(
                            ?,
                            target.result
                        ),

                        is_degraded = ?,
                        data_quality = ?

                WHEN NOT MATCHED THEN
                    INSERT (
                        run_id,
                        pipeline_id,
                        source_branch,
                        source_version,
                        requested_by,
                        queue_time,
                        start_time,
                        finish_time,
                        result,
                        is_degraded,
                        data_quality
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    );
                """,

                # USING
                first.run_id,

                # UPDATE
                first.pipeline_id,
                first.source_branch,
                first.source_version,
                first.requested_by,
                first.queue_time,
                run_start_time,
                run_finish_time,
                first.run_result or first.result,
                1 if run_is_degraded else 0,
                "degraded" if run_is_degraded else "complete",

                # INSERT
                first.run_id,
                first.pipeline_id,
                first.source_branch,
                first.source_version,
                first.requested_by,
                first.queue_time,
                run_start_time,
                run_finish_time,
                first.run_result or first.result,
                1 if run_is_degraded else 0,
                "degraded" if run_is_degraded else "complete",
            )

            # ---------------------------------------------------------
            # REAL ADO TIMELINE = SOURCE OF TRUTH
            #
            # Remove everything previously stored for this run.
            #
            # This is what removes things such as:
            #
            #     fallback-36
            #
            # before inserting the authoritative ADO timeline.
            # ---------------------------------------------------------

            if not run_is_degraded:

                cursor.execute(
                    """
                    DELETE FROM dbo.pipeline_tasks
                    WHERE run_id = ?
                    """,
                    first.run_id,
                )

                cursor.execute(
                    """
                    DELETE FROM dbo.pipeline_jobs
                    WHERE run_id = ?
                    """,
                    first.run_id,
                )

                cursor.execute(
                    """
                    DELETE FROM dbo.pipeline_stages
                    WHERE run_id = ?
                    """,
                    first.run_id,
                )

            # ---------------------------------------------------------
            # Insert the current authoritative timeline
            # ---------------------------------------------------------

            for metric in metrics:

                table = {
                    "stage": "pipeline_stages",
                    "job": "pipeline_jobs",
                    "task": "pipeline_tasks",
                }[metric.level]

                if metric.level == "stage":

                    column_names = """
                        stage_name
                    """

                    insert_names = """
                        stage_name
                    """

                    insert_values = "?"

                    hierarchy_values = [
                        metric.stage_name
                    ]

                elif metric.level == "job":

                    column_names = """
                        stage_name,
                        job_name
                    """

                    insert_names = """
                        stage_name,
                        job_name
                    """

                    insert_values = "?, ?"

                    hierarchy_values = [
                        metric.stage_name,
                        metric.job_name,
                    ]

                else:

                    column_names = """
                        stage_name,
                        job_name,
                        task_name
                    """

                    insert_names = """
                        stage_name,
                        job_name,
                        task_name
                    """

                    insert_values = "?, ?, ?"

                    hierarchy_values = [
                        metric.stage_name,
                        metric.job_name,
                        metric.task_name,
                    ]

                # -----------------------------------------------------
                # Use record_id as the ADO timeline identity.
                # -----------------------------------------------------

                cursor.execute(
                    f"""
                    INSERT INTO dbo.{table}
                    (
                        run_id,
                        record_id,
                        {insert_names},
                        agent_name,
                        start_time,
                        finish_time,
                        duration_seconds,
                        result,
                        retry_count,
                        failure_log_excerpt,
                        is_degraded,
                        data_quality
                    )
                    VALUES
                    (
                        ?,
                        ?,
                        {insert_values},
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,

                    metric.run_id,
                    metric.record_id,
                    *hierarchy_values,
                    metric.agent_name,
                    metric.start_time,
                    metric.finish_time,
                    metric.duration_seconds,
                    metric.result,
                    metric.retry_count,
                    metric.failure_log_excerpt,
                    1 if metric.is_degraded else 0,
                    metric.data_quality,
                )

            # ---------------------------------------------------------
            # Commit everything together.
            # ---------------------------------------------------------

            connection.commit()

    @staticmethod
    def _ensure_quality_columns(connection) -> None:
        statements = [
            """
            IF COL_LENGTH('dbo.pipeline_runs', 'is_degraded') IS NULL
                ALTER TABLE dbo.pipeline_runs ADD is_degraded BIT NOT NULL CONSTRAINT DF_pipeline_runs_is_degraded DEFAULT 0;
            IF COL_LENGTH('dbo.pipeline_runs', 'data_quality') IS NULL
                ALTER TABLE dbo.pipeline_runs ADD data_quality NVARCHAR(32) NOT NULL CONSTRAINT DF_pipeline_runs_data_quality DEFAULT 'complete';
            """,
            """
            IF COL_LENGTH('dbo.pipeline_stages', 'is_degraded') IS NULL
                ALTER TABLE dbo.pipeline_stages ADD is_degraded BIT NOT NULL CONSTRAINT DF_pipeline_stages_is_degraded DEFAULT 0;
            IF COL_LENGTH('dbo.pipeline_stages', 'data_quality') IS NULL
                ALTER TABLE dbo.pipeline_stages ADD data_quality NVARCHAR(32) NOT NULL CONSTRAINT DF_pipeline_stages_data_quality DEFAULT 'complete';
            """,
            """
            IF COL_LENGTH('dbo.pipeline_jobs', 'is_degraded') IS NULL
                ALTER TABLE dbo.pipeline_jobs ADD is_degraded BIT NOT NULL CONSTRAINT DF_pipeline_jobs_is_degraded DEFAULT 0;
            IF COL_LENGTH('dbo.pipeline_jobs', 'data_quality') IS NULL
                ALTER TABLE dbo.pipeline_jobs ADD data_quality NVARCHAR(32) NOT NULL CONSTRAINT DF_pipeline_jobs_data_quality DEFAULT 'complete';
            """,
            """
            IF COL_LENGTH('dbo.pipeline_tasks', 'is_degraded') IS NULL
                ALTER TABLE dbo.pipeline_tasks ADD is_degraded BIT NOT NULL CONSTRAINT DF_pipeline_tasks_is_degraded DEFAULT 0;
            IF COL_LENGTH('dbo.pipeline_tasks', 'data_quality') IS NULL
                ALTER TABLE dbo.pipeline_tasks ADD data_quality NVARCHAR(32) NOT NULL CONSTRAINT DF_pipeline_tasks_data_quality DEFAULT 'complete';
            """,
        ]
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)

    @staticmethod
    def _ensure_pipeline_context_columns(connection) -> None:
        cursor = connection.cursor()
        cursor.execute(
            """
            IF COL_LENGTH('dbo.pipelines', 'organization_name') IS NULL
                ALTER TABLE dbo.pipelines ADD organization_name NVARCHAR(256) NULL;
            IF COL_LENGTH('dbo.pipelines', 'project_name') IS NULL
                ALTER TABLE dbo.pipelines ADD project_name NVARCHAR(256) NULL;
            """
        )

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
            LEFT JOIN pipeline_tasks t ON t.run_id = r.run_id AND t.job_name = j.job_name AND t.stage_name = j.stage_name
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

    def get_dora_metrics(self, pipeline_id: int | None = None, days: int = 30) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        base_query = """
            SELECT metric_date, pipeline_id, pipeline_name, organization_name, project_name,
                   total_runs_count, successful_runs_count, failed_runs_count,
                   change_failure_rate_pct, avg_lead_time_seconds, avg_execution_duration_seconds
            FROM dbo.vw_dora_metrics
            WHERE metric_date >= CAST(? AS date)
        """
        params: list[Any] = [start]
        if pipeline_id is not None:
            base_query += " AND pipeline_id = ?"
            params.append(pipeline_id)
        base_query += " ORDER BY metric_date DESC"

        with self._connect() as connection:
            cursor = connection.cursor()
            columns = [col[0] for col in cursor.execute(base_query, *params).description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_agent_pool_stats(self, days: int = 30) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT metric_date, pool_name, total_runs, total_jobs,
                   avg_job_duration_seconds, avg_queue_wait_seconds, active_agents_count
            FROM dbo.vw_agent_pool_saturation
            WHERE metric_date >= CAST(? AS date)
            ORDER BY metric_date DESC, total_jobs DESC
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            columns = [col[0] for col in cursor.execute(query, start).description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_failure_clusters(self, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT TOP (?) cluster_id, signature_hash, error_pattern, first_seen_at,
                   last_seen_at, occurrences_count, severity, root_cause_summary, suggested_yaml_diff
            FROM dbo.failure_clusters
            ORDER BY last_seen_at DESC, occurrences_count DESC
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            columns = [col[0] for col in cursor.execute(query, limit).description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_paginated_runs(
        self,
        page: int = 1,
        page_size: int = 25,
        status: str | None = None,
        pipeline_id: int | None = None,
    ) -> dict[str, Any]:
        offset = max(0, (page - 1) * page_size)
        where_clauses = ["1=1"]
        params: list[Any] = []

        if status:
            where_clauses.append("r.result = ?")
            params.append(status)
        if pipeline_id:
            where_clauses.append("r.pipeline_id = ?")
            params.append(pipeline_id)

        where_sql = " AND ".join(where_clauses)
        count_query = f"SELECT COUNT(*) FROM dbo.pipeline_runs r WHERE {where_sql}"
        data_query = f"""
            SELECT r.run_id, r.pipeline_id, p.pipeline_name, p.organization_name, p.project_name,
                   r.source_branch, r.source_version, r.requested_by,
                   r.queue_time, r.start_time, r.finish_time, r.result, r.is_degraded, r.data_quality,
                   DATEDIFF(second, r.start_time, r.finish_time) AS duration_seconds
            FROM dbo.pipeline_runs r
            JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id
            WHERE {where_sql}
            ORDER BY r.start_time DESC
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """
        with self._connect() as connection:
            cursor = connection.cursor()
            total_count = cursor.execute(count_query, *params).fetchval()
            cursor.execute(data_query, *params, offset, page_size)
            columns = [col[0] for col in cursor.description]
            items = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1,
                "items": items,
            }



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
    now_utc = datetime.now(timezone.utc)
    latest_start = now_utc - timedelta(days=7)
    previous_start = now_utc - timedelta(days=14)
    latest = [row for row in rows if _as_utc(row.get("start_time")) and _as_utc(row.get("start_time")) >= latest_start]
    previous = [
        row
        for row in rows
        if _as_utc(row.get("start_time")) and previous_start <= _as_utc(row.get("start_time")) < latest_start
    ]
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


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# def _connection_variants(connection_string: str) -> list[str]:
#     variants: list[str] = []
#     if "ODBC Driver 18 for SQL Server" in connection_string:
#         variants.append(connection_string.replace("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"))
#     if "ODBC Driver 17 for SQL Server" in connection_string:
#         variants.append(connection_string.replace("ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"))
#     if "Driver={" not in connection_string:
#         variants.append(f"Driver={{ODBC Driver 18 for SQL Server}};{connection_string}")
#         variants.append(f"Driver={{ODBC Driver 17 for SQL Server}};{connection_string}")
#     # Keep order stable and remove duplicates.
#     seen: set[str] = set()
#     unique: list[str] = []
#     for variant in variants:
#         if variant not in seen:
#             seen.add(variant)
#             unique.append(variant)
#     return unique
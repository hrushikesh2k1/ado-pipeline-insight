from __future__ import annotations

import base64
import json
import os
import re
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from flask import Flask, g, jsonify, render_template, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ado_client import AzureDevOpsClient
from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient

app = Flask(__name__)

SYNTHETIC_STAGE_NAMES = {"summary", "__default"}


@app.before_request
def attach_request_id() -> None:
    g.request_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())


@app.after_request
def add_request_id_header(response):
    response.headers["X-Correlation-Id"] = g.get("request_id", "n/a")
    return response


@app.teardown_appcontext
def close_connection(_error: BaseException | None) -> None:
    connection = g.pop("db_connection", None)
    if connection is not None:
        connection.close()


def _json_error(message: str, status: int) -> tuple[Any, int]:
    return jsonify({"error": message, "request_id": g.get("request_id", "n/a")}), status


def _friendly_runtime_message(error: RuntimeError) -> str:
    text = str(error)
    if "is not allowed to access the server" in text:
        ip_match = re.search(r"Client with IP address '([^']+)'", text)
        ip_value = ip_match.group(1) if ip_match else "your current IP"
        return f"SQL firewall blocked access for {ip_value}. Add this IP to the Azure SQL server firewall and retry in a few minutes."
    if "IM002" in text:
        return "ODBC SQL driver is missing. Install ODBC Driver 17 or 18 for SQL Server."
    return text[:260]


def _setting_value(key: str) -> str | None:
    settings_paths = [
        PROJECT_ROOT / "local.settings.json",
        PROJECT_ROOT / "functions" / "local.settings.json",
    ]
    for settings_path in settings_paths:
        if not settings_path.exists():
            continue
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        value = (data.get("Values") or {}).get(key)
        if value:
            return str(value)
    from_env = os.environ.get(key)
    if from_env:
        return from_env
    return None


def _sql_connection_string() -> str:
    value = _setting_value("SQL_CONNECTION_STRING")
    if value:
        return value

    raise RuntimeError("SQL_CONNECTION_STRING is not set. Add it in env or local.settings.json.")


def _settings_values() -> dict[str, Any]:
    local_api_key = _setting_value("AZURE_OPENAI_API_KEY") or _setting_value("AZURE_OPENAI_KEY")
    from_env = {
        "AZURE_OPENAI_ENDPOINT": _setting_value("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_DEPLOYMENT": _setting_value("AZURE_OPENAI_DEPLOYMENT"),
        "AZURE_OPENAI_API_VERSION": _setting_value("AZURE_OPENAI_API_VERSION"),
        "AZURE_OPENAI_API_KEY": local_api_key,
    }
    if from_env["AZURE_OPENAI_ENDPOINT"] and from_env["AZURE_OPENAI_DEPLOYMENT"]:
        return from_env
    return from_env


def _connection():
    if "db_connection" not in g:
        repository = AlertRepository(_sql_connection_string())
        g.db_connection = repository._connect()  # noqa: SLF001 - reuse existing DB connector
    if "pipeline_context_ready" not in g:
        cursor = g.db_connection.cursor()
        cursor.execute(
            """
            IF COL_LENGTH('dbo.pipelines', 'organization_name') IS NULL
                ALTER TABLE dbo.pipelines ADD organization_name NVARCHAR(256) NULL;
            IF COL_LENGTH('dbo.pipelines', 'project_name') IS NULL
                ALTER TABLE dbo.pipelines ADD project_name NVARCHAR(256) NULL;
            """
        )
        g.pipeline_context_ready = True
    return g.db_connection


def _rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = _connection().cursor()
    cursor.execute(query, *params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _normalize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _project_from_pipeline_name(pipeline_name: str) -> str:
    name = (pipeline_name or "").strip()
    if not name:
        return "Unknown Project"
    if "/" in name:
        return name.split("/", 1)[0].strip() or "Unknown Project"
    return name


def _build_in_clause(column: str, values: list[int]) -> tuple[str, list[Any]]:
    if not values:
        return " AND 1=0", []
    placeholders = ",".join("?" for _ in values)
    return f" AND {column} IN ({placeholders})", list(values)


def _all_pipelines() -> list[dict[str, Any]]:
    query = """
        SELECT
            p.pipeline_id,
            p.pipeline_name,
            COALESCE(p.organization_name, '') AS organization_name,
            COALESCE(p.project_name, '') AS project_name
        FROM dbo.pipelines p
        JOIN (SELECT DISTINCT pipeline_id FROM dbo.pipeline_runs) r ON r.pipeline_id = p.pipeline_id
        ORDER BY p.pipeline_name
    """
    rows = _rows(query)
    return [
        {
            "pipeline_id": int(row["pipeline_id"]),
            "pipeline_name": row["pipeline_name"],
            "project_name": row.get("project_name") or _project_from_pipeline_name(row["pipeline_name"]),
            "organization_name": row.get("organization_name") or "Unknown Organization",
        }
        for row in rows
    ]


def _run_trend(months: int, pipeline_ids: list[int]) -> list[dict[str, Any]]:
    in_sql, in_params = _build_in_clause("r.pipeline_id", pipeline_ids)
    query = f"""
        SELECT
            CAST(COALESCE(r.start_time, r.queue_time, r.finish_time) AS date) AS run_date,
            r.run_id,
            r.pipeline_id,
            p.pipeline_name,
            r.result,
            r.start_time,
            r.finish_time,
            COALESCE(
                NULLIF(CAST(DATEDIFF_BIG(millisecond, r.start_time, r.finish_time) AS float) / 1000.0, 0),
                NULLIF(s.stage_duration_seconds, 0),
                NULL
            ) AS duration_seconds,
            CAST(COALESCE(f.has_fallback, 0) AS int) AS is_degraded
        FROM dbo.pipeline_runs r
        JOIN dbo.pipelines p ON p.pipeline_id = r.pipeline_id
        LEFT JOIN (
            SELECT run_id, SUM(COALESCE(duration_seconds, 0)) AS stage_duration_seconds
            FROM dbo.pipeline_stages
            WHERE record_id NOT LIKE 'fallback-%'
            GROUP BY run_id
        ) s ON s.run_id = r.run_id
        LEFT JOIN (
            SELECT run_id, 1 AS has_fallback
            FROM dbo.pipeline_stages
            WHERE record_id LIKE 'fallback-%'
            GROUP BY run_id
        ) f ON f.run_id = r.run_id
        WHERE COALESCE(r.start_time, r.queue_time, r.finish_time) >= DATEADD(month, -?, SYSUTCDATETIME())
        {in_sql}
        ORDER BY COALESCE(r.start_time, r.queue_time, r.finish_time), r.run_id
    """
    params: list[Any] = [months]
    params.extend(in_params)
    rows = _rows(query, tuple(params))
    return [
        {
            "label": f"#{row['run_id']}",
            "run_id": int(row["run_id"]),
            "run_date": str(row["run_date"]),
            "pipeline_id": int(row["pipeline_id"]),
            "pipeline_name": row["pipeline_name"],
            "result": (row.get("result") or "unknown").lower(),
            "duration_seconds": (round(float(row["duration_seconds"]), 2) if row.get("duration_seconds") is not None else None),
            "is_degraded": bool(row.get("is_degraded")),
            "start_time": _normalize(row.get("start_time")),
            "finish_time": _normalize(row.get("finish_time")),
        }
        for row in rows
    ]


def _stage_trend(months: int, pipeline_ids: list[int]) -> list[dict[str, Any]]:
    in_sql, in_params = _build_in_clause("r.pipeline_id", pipeline_ids)
    query = f"""
        SELECT
            CAST(COALESCE(r.start_time, r.queue_time, r.finish_time) AS date) AS run_date,
            s.stage_name,
            AVG(COALESCE(s.duration_seconds, 0)) AS avg_duration_seconds
        FROM dbo.pipeline_runs r
        JOIN dbo.pipeline_stages s ON s.run_id = r.run_id
        WHERE COALESCE(r.start_time, r.queue_time, r.finish_time) >= DATEADD(month, -?, SYSUTCDATETIME())
          AND s.record_id NOT LIKE 'fallback-%'
          {in_sql}
        GROUP BY CAST(COALESCE(r.start_time, r.queue_time, r.finish_time) AS date), s.stage_name
        ORDER BY run_date, s.stage_name
    """
    params: list[Any] = [months]
    params.extend(in_params)
    rows = _rows(query, tuple(params))
    return [
        {
            "run_date": str(row["run_date"]),
            "stage_name": row["stage_name"],
            "avg_duration_seconds": round(float(row["avg_duration_seconds"] or 0), 2),
        }
        for row in rows
    ]


def _delete_stale_runs(pipeline_id: int) -> dict[str, int]:
    connection = _connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT r.run_id
        FROM dbo.pipeline_runs r
        LEFT JOIN (
            SELECT
                run_id,
                SUM(CASE WHEN record_id LIKE 'fallback-%' THEN 1 ELSE 0 END) AS fallback_count,
                SUM(CASE WHEN record_id NOT LIKE 'fallback-%' THEN 1 ELSE 0 END) AS real_count
            FROM dbo.pipeline_stages
            GROUP BY run_id
        ) s ON s.run_id = r.run_id
        WHERE r.pipeline_id = ?
          AND COALESCE(s.fallback_count, 0) > 0
          AND COALESCE(s.real_count, 0) = 0
        """,
        pipeline_id,
    )
    stale_run_ids = [int(row[0]) for row in cursor.fetchall()]
    if not stale_run_ids:
        return {"removed_runs": 0}

    placeholders = ",".join("?" for _ in stale_run_ids)
    for table in ["pipeline_tasks", "pipeline_jobs", "pipeline_stages", "pipeline_runs"]:
        cursor.execute(f"DELETE FROM dbo.{table} WHERE run_id IN ({placeholders})", *stale_run_ids)
    connection.commit()
    return {"removed_runs": len(stale_run_ids)}


def _backfill_pipeline_context(organization_name: str) -> dict[str, int]:
    connection = _connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE dbo.pipelines
        SET organization_name = ?
        WHERE organization_name IS NULL OR LTRIM(RTRIM(organization_name)) = ''
        """,
        organization_name,
    )
    org_updated = int(cursor.rowcount or 0)

    cursor.execute("SELECT pipeline_id, pipeline_name FROM dbo.pipelines WHERE project_name IS NULL OR LTRIM(RTRIM(project_name)) = ''")
    empty_project_rows = cursor.fetchall()
    project_updated = 0
    for row in empty_project_rows:
        pipeline_id = int(row[0])
        project_name = _project_from_pipeline_name(row[1])
        cursor.execute("UPDATE dbo.pipelines SET project_name = ? WHERE pipeline_id = ?", project_name, pipeline_id)
        project_updated += 1

    connection.commit()
    return {"organization_updated": org_updated, "project_updated": project_updated}


def _set_pipeline_name(pipeline_id: int, pipeline_name: str) -> dict[str, int]:
    connection = _connection()
    cursor = connection.cursor()
    cursor.execute("UPDATE dbo.pipelines SET pipeline_name = ? WHERE pipeline_id = ?", pipeline_name, pipeline_id)
    connection.commit()
    return {"updated": int(cursor.rowcount or 0)}


def _list_user_tables() -> list[dict[str, Any]]:
    rows = _rows(
        """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_NAME
        """
    )
    return [{"schema": row["TABLE_SCHEMA"], "name": row["TABLE_NAME"]} for row in rows]


def _ensure_bootstrap_state_table() -> None:
    cursor = _connection().cursor()
    cursor.execute(
        """
        IF OBJECT_ID('dbo.ingestion_bootstrap_state', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.ingestion_bootstrap_state (
                organization_name NVARCHAR(256) NOT NULL PRIMARY KEY,
                completed_at DATETIME2 NULL,
                runs_ingested INT NOT NULL CONSTRAINT DF_bootstrap_runs DEFAULT 0,
                projects_scanned INT NOT NULL CONSTRAINT DF_bootstrap_projects DEFAULT 0,
                failed_runs INT NOT NULL CONSTRAINT DF_bootstrap_failed DEFAULT 0,
                note NVARCHAR(1024) NULL
            );
        END
        """
    )


def _read_bootstrap_state(organization_name: str) -> dict[str, Any] | None:
    _ensure_bootstrap_state_table()
    rows = _rows(
        """
        SELECT organization_name, completed_at, runs_ingested, projects_scanned, failed_runs, note
        FROM dbo.ingestion_bootstrap_state
        WHERE organization_name = ?
        """,
        (organization_name,),
    )
    return rows[0] if rows else None


def _write_bootstrap_state(
    organization_name: str,
    runs_ingested: int,
    projects_scanned: int,
    failed_runs: int,
    note: str,
) -> None:
    _ensure_bootstrap_state_table()
    cursor = _connection().cursor()
    cursor.execute(
        """
        MERGE dbo.ingestion_bootstrap_state AS target
        USING (SELECT ? AS organization_name) AS source
        ON target.organization_name = source.organization_name
        WHEN MATCHED THEN
            UPDATE SET
                completed_at = SYSUTCDATETIME(),
                runs_ingested = ?,
                projects_scanned = ?,
                failed_runs = ?,
                note = ?
        WHEN NOT MATCHED THEN
            INSERT (organization_name, completed_at, runs_ingested, projects_scanned, failed_runs, note)
            VALUES (?, SYSUTCDATETIME(), ?, ?, ?, ?);
        """,
        organization_name,
        runs_ingested,
        projects_scanned,
        failed_runs,
        note,
        organization_name,
        runs_ingested,
        projects_scanned,
        failed_runs,
        note,
    )
    _connection().commit()


def _bootstrap_organization_name() -> str:
    configured = _setting_value("ADO_ORGANIZATION")
    if configured:
        return configured
    pipelines = _all_pipelines()
    named = [item["organization_name"] for item in pipelines if item.get("organization_name") and item["organization_name"] != "Unknown Organization"]
    if named:
        return named[0]
    raise RuntimeError("ADO_ORGANIZATION is not configured.")


def _ado_session(pat: str) -> requests.Session:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    session = requests.Session()
    session.headers.update({"Authorization": f"Basic {token}"})
    return session


def _ado_get_json(session: requests.Session, url: str, params: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    continuation = response.headers.get("x-ms-continuationtoken")
    return response.json(), continuation


def _ado_projects(session: requests.Session, organization: str) -> list[str]:
    projects: list[str] = []
    continuation: str | None = None
    while True:
        params: dict[str, Any] = {"api-version": "7.1", "$top": 100}
        if continuation:
            params["continuationToken"] = continuation
        payload, continuation = _ado_get_json(session, f"https://dev.azure.com/{organization}/_apis/projects", params)
        projects.extend([item.get("name") for item in payload.get("value", []) if item.get("name")])
        if not continuation:
            break
    return projects


def _ado_build_ids(session: requests.Session, organization: str, project: str, max_runs_per_project: int) -> list[int]:
    build_ids: list[int] = []
    continuation: str | None = None
    while len(build_ids) < max_runs_per_project:
        params: dict[str, Any] = {
            "api-version": "7.1",
            "statusFilter": "completed",
            "queryOrder": "finishTimeDescending",
            "$top": min(200, max_runs_per_project - len(build_ids)),
        }
        if continuation:
            params["continuationToken"] = continuation
        payload, continuation = _ado_get_json(session, f"https://dev.azure.com/{organization}/{project}/_apis/build/builds", params)
        values = payload.get("value", [])
        if not values:
            break
        build_ids.extend([int(item["id"]) for item in values if item.get("id") is not None])
        if not continuation:
            break
    return build_ids


def _bootstrap_ingest(force: bool, max_runs_per_project: int) -> dict[str, Any]:
    organization = _bootstrap_organization_name()
    existing = _read_bootstrap_state(organization)
    if existing and not force:
        return {
            "status": "skipped",
            "organization": organization,
            "message": "Historical ingest already completed. Pass force=true to rerun.",
            "last_completed_at": _normalize(existing.get("completed_at")),
            "runs_ingested": int(existing.get("runs_ingested") or 0),
            "projects_scanned": int(existing.get("projects_scanned") or 0),
            "failed_runs": int(existing.get("failed_runs") or 0),
        }

    pat = _setting_value("ADO_PAT")
    if not pat:
        raise RuntimeError("ADO_PAT is not configured.")

    session = _ado_session(pat)
    client = AzureDevOpsClient(organization, pat, session=session)
    repository = AlertRepository(_sql_connection_string())

    projects = _ado_projects(session, organization)
    runs_ingested = 0
    failed_runs = 0

    for project in projects:
        build_ids = _ado_build_ids(session, organization, project, max_runs_per_project)
        for build_id in build_ids:
            try:
                build = client.get_build(project, build_id)
                timeline = client.get_timeline(project, build_id)
                metrics = client.flatten_timeline(build, timeline)
                project_name = (build.get("project") or {}).get("name") or project
                enriched = [
                    metric.__class__(
                        **{
                            **metric.__dict__,
                            "organization_name": organization,
                            "project_name": project_name,
                        }
                    )
                    for metric in metrics
                ]
                if not enriched:
                    continue
                repository.upsert_metrics(enriched)
                runs_ingested += 1
            except Exception:
                failed_runs += 1

    note = f"projects={len(projects)}, max_runs_per_project={max_runs_per_project}"
    _write_bootstrap_state(organization, runs_ingested, len(projects), failed_runs, note)
    return {
        "status": "completed",
        "organization": organization,
        "runs_ingested": runs_ingested,
        "projects_scanned": len(projects),
        "failed_runs": failed_runs,
        "note": note,
    }


def _cached_recommendations(pipeline_id: int) -> list[dict[str, Any]]:
    rows = _rows(
        """
        SELECT TOP 20 category, severity, stage_name, task_name, recommendation, evidence, generated_at
        FROM dbo.ai_recommendations
        WHERE pipeline_id = ?
        ORDER BY generated_at DESC
        """,
        (pipeline_id,),
    )
    findings = [
        {
            "category": row["category"],
            "severity": row["severity"],
            "stage_name": row["stage_name"],
            "task_name": row.get("task_name"),
            "recommendation": row["recommendation"],
            "evidence": row["evidence"],
            "generated_at": _normalize(row.get("generated_at")),
        }
        for row in rows
    ]
    return [item for item in findings if (item.get("stage_name") or "").strip().lower() not in SYNTHETIC_STAGE_NAMES]


def _generate_recommendations(pipeline_id: int, months: int) -> list[dict[str, Any]]:
    settings = _settings_values()
    endpoint = settings.get("AZURE_OPENAI_ENDPOINT")
    deployment = settings.get("AZURE_OPENAI_DEPLOYMENT")
    if not endpoint or not deployment:
        raise RuntimeError("Azure OpenAI is not configured for local dashboard.")

    repository = AlertRepository(_sql_connection_string())
    metric_rows = repository.get_pipeline_metrics(pipeline_id, days=max(7, months * 31))
    actionable_rows = [
        row
        for row in metric_rows
        if (row.get("stage_name") or "").strip().lower() not in SYNTHETIC_STAGE_NAMES
    ]
    if len(actionable_rows) < 3:
        raise RuntimeError("Not enough run history for AI recommendations yet.")

    summary = build_analysis_summary(actionable_rows, window_days=max(7, months * 31))
    summary["dashboard_context"] = {
        "build_trend": _run_trend(months, [pipeline_id]),
        "stage_trend": _stage_trend(months, [pipeline_id]),
    }
    client = PipelineRecommendationClient(
        endpoint=endpoint,
        deployment=deployment,
        api_version=settings.get("AZURE_OPENAI_API_VERSION") or "2024-10-21",
        api_key=settings.get("AZURE_OPENAI_API_KEY"),
    )
    findings = [finding.__dict__ for finding in client.recommend(summary).findings]
    findings = [item for item in findings if (item.get("stage_name") or "").strip().lower() not in SYNTHETIC_STAGE_NAMES]
    repository.upsert_recommendations(pipeline_id, findings)
    return findings


@app.get("/")
def home() -> str:
    return render_template("index.html")


@app.get("/api/version")
def version() -> Any:
    return jsonify({"version": "dashboard-clean-2026-08-31-1"})


@app.get("/api/options")
def options() -> Any:
    try:
        pipelines = _all_pipelines()
        organizations = sorted({item["organization_name"] for item in pipelines})
        if len(organizations) > 1 and "Unknown Organization" in organizations:
            organizations = [item for item in organizations if item != "Unknown Organization"]
        projects = sorted({item["project_name"] for item in pipelines})
        return jsonify(
            {
                "organizations": organizations,
                "projects": projects,
                "pipelines": pipelines,
                "note": "Project and organization are derived from pipeline metadata in SQL.",
            }
        )
    except RuntimeError as error:
        app.logger.exception("options runtime error")
        return jsonify(
            {
                "organizations": [],
                "projects": [],
                "pipelines": [],
                "note": f"SQL unavailable: {_friendly_runtime_message(error)}",
                "warning": "sql_unavailable",
            }
        )
    except Exception:
        app.logger.exception("options failed")
        return _json_error("Unable to load filter options.", 500)


@app.get("/api/trends")
def trends() -> Any:
    try:
        months = request.args.get("months", default=3, type=int)
        months = max(1, min(months, 24))

        selected_org = request.args.get("organization") or ""
        selected_project = request.args.get("project") or ""
        selected_pipeline_id = request.args.get("pipeline_id", type=int)
        include_degraded = request.args.get("include_degraded", default=0, type=int) == 1

        pipelines = _all_pipelines()
        filtered = pipelines
        if selected_org:
            filtered = [item for item in filtered if item["organization_name"] == selected_org]
        if selected_project:
            filtered = [item for item in filtered if item["project_name"] == selected_project]
        if selected_pipeline_id is not None:
            filtered = [item for item in filtered if item["pipeline_id"] == selected_pipeline_id]

        pipeline_ids = [item["pipeline_id"] for item in filtered]
        build_rows = _run_trend(months, pipeline_ids)
        if not include_degraded:
            build_rows = [row for row in build_rows if not row.get("is_degraded")]
        stage_rows = _stage_trend(months, pipeline_ids)

        return jsonify(
            {
                "months": months,
                "filters": {
                    "organization": selected_org,
                    "project": selected_project,
                    "pipeline_id": selected_pipeline_id,
                    "include_degraded": include_degraded,
                },
                "run_count": len(build_rows),
                "build_trend": build_rows,
                "stage_trend": stage_rows,
            }
        )
    except RuntimeError as error:
        app.logger.exception("trends runtime error")
        return jsonify(
            {
                "months": request.args.get("months", default=3, type=int),
                "filters": {
                    "organization": request.args.get("organization") or "",
                    "project": request.args.get("project") or "",
                    "pipeline_id": request.args.get("pipeline_id", type=int),
                },
                "run_count": 0,
                "build_trend": [],
                "stage_trend": [],
                "warning": f"SQL unavailable: {_friendly_runtime_message(error)}",
            }
        )
    except Exception:
        app.logger.exception("trends failed")
        return _json_error("Unable to load trend data.", 500)


@app.get("/api/recommendations")
def recommendations() -> Any:
    try:
        pipeline_id = request.args.get("pipeline_id", type=int)
        if pipeline_id is None or pipeline_id <= 0:
            return _json_error("pipeline_id is required.", 400)
        months = request.args.get("months", default=3, type=int)
        months = max(1, min(months, 24))

        findings = _generate_recommendations(pipeline_id, months)
        return jsonify({"pipeline_id": pipeline_id, "months": months, "source": "generated", "findings": findings})
    except RuntimeError as error:
        fallback_pipeline_id = request.args.get("pipeline_id", type=int) or 0
        cached = _cached_recommendations(fallback_pipeline_id) if fallback_pipeline_id > 0 else []
        return jsonify(
            {
                "pipeline_id": fallback_pipeline_id,
                "months": request.args.get("months", default=3, type=int),
                "source": "cached" if cached else "none",
                "warning": str(error),
                "findings": cached,
            }
        )
    except Exception:
        app.logger.exception("recommendations failed")
        return _json_error("Unable to load recommendations.", 500)


@app.post("/api/admin/cleanup-stale-runs")
def cleanup_stale_runs() -> Any:
    try:
        payload = request.get_json(silent=True) or {}
        pipeline_id = int(payload.get("pipeline_id") or 0)
        if pipeline_id <= 0:
            return _json_error("pipeline_id is required.", 400)
        result = _delete_stale_runs(pipeline_id)
        return jsonify({"pipeline_id": pipeline_id, **result})
    except RuntimeError as error:
        app.logger.exception("cleanup stale runtime error")
        return _json_error(str(error), 500)
    except Exception:
        app.logger.exception("cleanup stale failed")
        return _json_error("Unable to cleanup stale runs.", 500)


@app.post("/api/admin/backfill-pipeline-context")
def backfill_pipeline_context() -> Any:
    try:
        payload = request.get_json(silent=True) or {}
        organization_name = str(payload.get("organization_name") or "").strip()
        if not organization_name:
            return _json_error("organization_name is required.", 400)
        result = _backfill_pipeline_context(organization_name)
        return jsonify({"organization_name": organization_name, **result})
    except RuntimeError as error:
        app.logger.exception("backfill context runtime error")
        return _json_error(str(error), 500)
    except Exception:
        app.logger.exception("backfill context failed")
        return _json_error("Unable to backfill pipeline context.", 500)


@app.post("/api/admin/set-pipeline-name")
def set_pipeline_name() -> Any:
    try:
        payload = request.get_json(silent=True) or {}
        pipeline_id = int(payload.get("pipeline_id") or 0)
        pipeline_name = str(payload.get("pipeline_name") or "").strip()
        if pipeline_id <= 0:
            return _json_error("pipeline_id is required.", 400)
        if not pipeline_name:
            return _json_error("pipeline_name is required.", 400)
        result = _set_pipeline_name(pipeline_id, pipeline_name)
        return jsonify({"pipeline_id": pipeline_id, "pipeline_name": pipeline_name, **result})
    except RuntimeError as error:
        app.logger.exception("set pipeline name runtime error")
        return _json_error(str(error), 500)
    except Exception:
        app.logger.exception("set pipeline name failed")
        return _json_error("Unable to set pipeline name.", 500)


@app.post("/api/admin/bootstrap-ingest")
def bootstrap_ingest() -> Any:
    try:
        payload = request.get_json(silent=True) or {}
        force = bool(payload.get("force", False))
        max_runs_per_project = int(payload.get("max_runs_per_project") or 1000)
        max_runs_per_project = max(1, min(max_runs_per_project, 20000))
        result = _bootstrap_ingest(force=force, max_runs_per_project=max_runs_per_project)
        return jsonify(result)
    except RuntimeError as error:
        app.logger.exception("bootstrap ingest runtime error")
        return _json_error(str(error), 500)
    except Exception:
        app.logger.exception("bootstrap ingest failed")
        return _json_error("Unable to run historical ingest.", 500)


@app.get("/api/db/tables")
def db_tables() -> Any:
    try:
        return jsonify({"tables": _list_user_tables()})
    except RuntimeError as error:
        app.logger.exception("db tables runtime error")
        return _json_error(str(error), 500)
    except Exception:
        app.logger.exception("db tables failed")
        return _json_error("Unable to load database tables.", 500)


@app.route("/api/db/info", methods=["GET"])
def db_info() -> Any:
    try:
        info_rows = _rows("SELECT @@SERVERNAME AS server_name, DB_NAME() AS database_name")
        column_rows = _rows(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'pipelines'
            ORDER BY ORDINAL_POSITION
            """
        )
        sample_rows = _rows(
            """
            SELECT TOP 10 pipeline_id, pipeline_name, organization_name, project_name
            FROM dbo.pipelines
            ORDER BY pipeline_id
            """
        )
        return jsonify(
            {
                "request_id": g.get("request_id", "n/a"),
                "server_name": info_rows[0]["server_name"] if info_rows else None,
                "database_name": info_rows[0]["database_name"] if info_rows else None,
                "pipeline_columns": [row["COLUMN_NAME"] for row in column_rows],
                "pipeline_samples": sample_rows,
            }
        )
    except Exception:
        app.logger.exception("db_info failed")
        return _json_error("Failed to fetch DB info", 500)


# ==========================================
# Phase 1: Enterprise API Endpoints (v2)
# ==========================================

@app.get("/api/v2/dora")
def api_v2_dora() -> Any:
    try:
        pipeline_id = request.args.get("pipeline_id", type=int)
        days = request.args.get("days", default=30, type=int)
        repository = AlertRepository(_sql_connection_string())
        metrics = repository.get_dora_metrics(pipeline_id=pipeline_id, days=days)
        return jsonify({
            "request_id": g.get("request_id", "n/a"),
            "window_days": days,
            "pipeline_id": pipeline_id,
            "metrics": metrics,
        })
    except Exception as error:
        app.logger.exception("api_v2_dora failed")
        return _json_error(str(error), 500)


@app.get("/api/v2/pools")
def api_v2_pools() -> Any:
    try:
        days = request.args.get("days", default=30, type=int)
        repository = AlertRepository(_sql_connection_string())
        stats = repository.get_agent_pool_stats(days=days)
        return jsonify({
            "request_id": g.get("request_id", "n/a"),
            "window_days": days,
            "pools": stats,
        })
    except Exception as error:
        app.logger.exception("api_v2_pools failed")
        return _json_error(str(error), 500)


@app.get("/api/v2/runs")
def api_v2_runs() -> Any:
    try:
        page = request.args.get("page", default=1, type=int)
        page_size = request.args.get("page_size", default=25, type=int)
        status = request.args.get("status")
        pipeline_id = request.args.get("pipeline_id", type=int)
        repository = AlertRepository(_sql_connection_string())
        result = repository.get_paginated_runs(page=page, page_size=page_size, status=status, pipeline_id=pipeline_id)
        return jsonify({
            "request_id": g.get("request_id", "n/a"),
            **result,
        })
    except Exception as error:
        app.logger.exception("api_v2_runs failed")
        return _json_error(str(error), 500)


@app.get("/api/v2/ai/triage")
def api_v2_ai_triage() -> Any:
    try:
        limit = request.args.get("limit", default=50, type=int)
        repository = AlertRepository(_sql_connection_string())
        clusters = repository.get_failure_clusters(limit=limit)
        return jsonify({
            "request_id": g.get("request_id", "n/a"),
            "total_clusters": len(clusters),
            "clusters": clusters,
        })
    except Exception as error:
        app.logger.exception("api_v2_ai_triage failed")
        return _json_error(str(error), 500)


@app.get("/api/runs/<int:run_id>/timeline")
def api_run_timeline(run_id: int) -> Any:
    try:
        stages = _rows(
            """
            SELECT id, stage_name, agent_name, start_time, finish_time, duration_seconds, result, retry_count
            FROM dbo.pipeline_stages
            WHERE run_id = ?
            ORDER BY start_time
            """,
            (run_id,),
        )
        jobs = _rows(
            """
            SELECT id, stage_name, job_name, pool_name, agent_name, start_time, finish_time, duration_seconds, result, retry_count
            FROM dbo.pipeline_jobs
            WHERE run_id = ?
            ORDER BY start_time
            """,
            (run_id,),
        )
        tasks = _rows(
            """
            SELECT id, stage_name, job_name, task_name, agent_name, start_time, finish_time, duration_seconds, result, retry_count, failure_log_excerpt
            FROM dbo.pipeline_tasks
            WHERE run_id = ?
            ORDER BY start_time
            """,
            (run_id,),
        )
        return jsonify({
            "run_id": run_id,
            "stages": stages,
            "jobs": jobs,
            "tasks": tasks,
        })
    except Exception as error:
        app.logger.exception("api_run_timeline failed")
        return _json_error(str(error), 500)


@app.get("/api/runs/<int:run_id>/logs")
def api_run_logs(run_id: int) -> Any:
    try:
        rows = _rows(
            """
            SELECT task_name, failure_log_excerpt, result
            FROM dbo.pipeline_tasks
            WHERE run_id = ? AND (failure_log_excerpt IS NOT NULL OR result = 'failed')
            """,
            (run_id,),
        )
        excerpts = [row["failure_log_excerpt"] for row in rows if row.get("failure_log_excerpt")]
        if excerpts:
            log_content = "\n\n".join(excerpts)
        else:
            run_rows = _rows("SELECT result, is_degraded FROM dbo.pipeline_runs WHERE run_id = ?", (run_id,))
            res_str = run_rows[0]["result"] if run_rows else "unknown"
            log_content = f"Run #{run_id} finished with status: {res_str}.\nNo detailed failure log was captured for this run."

        return jsonify({
            "run_id": run_id,
            "log": log_content,
        })
    except Exception as error:
        app.logger.exception("api_run_logs failed")
        return _json_error(str(error), 500)




if __name__ == "__main__":
    debug_enabled = os.environ.get("DASHBOARD_DEBUG") == "1"
    app.run(host="127.0.0.1", port=5050, debug=debug_enabled)

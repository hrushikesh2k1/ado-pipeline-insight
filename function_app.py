import json
import logging
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import azure.functions as func
import requests

from core.ado_client import AzureDevOpsClient
from core.config import get_ado_pat, get_settings
from core.db import AlertRepository, build_analysis_summary
from core.models import TimelineMetric
from core.openai_client import PipelineRecommendationClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="ingest_run", methods=["POST"])
def ingest_run(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()
        resource = payload.get("resource", payload)
        organization = _extract_organization(payload, resource)
        organization_display = _extract_organization_display(payload, resource, organization)
        project = _extract_project(payload, resource)
        build_id = resource.get("id") or resource.get("buildId") or payload.get("runId")
        if not all([organization, project, build_id]):
            return func.HttpResponse("Webhook must include organization, project, and run/build ID.", status_code=400)
        build_id_int = int(build_id)
        try:
            client = AzureDevOpsClient(organization, get_ado_pat())
            build = client.get_build(project, build_id_int)
            timeline = client.get_timeline(project, build_id_int)
            metrics = client.flatten_timeline(build, timeline)
            if not metrics:
                raise ValueError("Azure DevOps returned no Stage/Job/Task timeline records; refusing to mark the run as successfully ingested.")
            metrics = [
                metric.__class__(
                    **{
                        **metric.__dict__,
                        "organization_name": organization_display,
                        "project_name": project,
                    }
                )
                for metric in metrics
            ]
            for index, metric in enumerate(metrics):
                if metric.level == "task" and metric.result == "failed" and metric.log_id:
                    metrics[index] = metric.__class__(**{**metric.__dict__, "failure_log_excerpt": client.get_log_tail(project, build_id_int, metric.log_id)})
        except requests.HTTPError as error:
            status_code = (error.response.status_code if error.response else 0)
            # Expected ADO API failures degrade gracefully; unknown statuses should still fail loudly.
            if status_code in {401, 403, 404, 408, 429} or status_code >= 500:
                logging.warning(
                    "ingest_run_degraded: ADO HTTP error; using fallback metric",
                    extra={"run_id": build_id_int, "status_code": status_code},
                    exc_info=True,
                )
                metrics = [_build_fallback_metric(resource, build_id_int, organization_display, project)]
            else:
                raise
        except (requests.Timeout, requests.ConnectionError) as error:
            logging.warning(
                "ingest_run_degraded: ADO network/timeout error; using fallback metric",
                extra={"run_id": build_id_int, "error_type": type(error).__name__},
                exc_info=True,
            )
            metrics = [_build_fallback_metric(resource, build_id_int, organization_display, project)]
        AlertRepository(get_settings().sql_connection_string).upsert_metrics(metrics)
        logging.info("ingest_run completed", extra={"run_id": build_id, "metric_count": len(metrics)})
        return func.HttpResponse(json.dumps({"run_id": build_id, "records_upserted": len(metrics)}), mimetype="application/json")
    except (ValueError, KeyError) as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        logging.exception("ingest_run failed")
        return func.HttpResponse("Unable to ingest pipeline run.", status_code=500)


def _extract_organization(payload: dict, resource: dict) -> str | None:
    # Accept explicit organization first when provided.
    explicit = payload.get("organization") or payload.get("org")
    if explicit:
        return explicit

    # Prefer Azure DevOps URLs to derive org name; resourceContainers.account.id is a GUID, not org name.
    url_candidates = [
        resource.get("url"),
        resource.get("_links", {}).get("web", {}).get("href"),
    ]
    for value in url_candidates:
        if not value:
            continue
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        path_parts = [part for part in parsed.path.split("/") if part]
        if host == "dev.azure.com" and path_parts:
            return path_parts[0]
        if host.endswith(".visualstudio.com"):
            return host.split(".")[0]

    # Last fallback: if account container has a human-readable name, use it.
    container_name = payload.get("resourceContainers", {}).get("account", {}).get("name")
    return container_name


def _extract_project(payload: dict, resource: dict) -> str | None:
    return (
        resource.get("project", {}).get("name")
        or resource.get("definition", {}).get("project", {}).get("name")
        or payload.get("resourceContainers", {}).get("project", {}).get("name")
        or resource.get("resourceContainers", {}).get("project", {}).get("name")
        or resource.get("project", {}).get("id")
        or resource.get("definition", {}).get("project", {}).get("id")
        or payload.get("resourceContainers", {}).get("project", {}).get("id")
    )


def _extract_organization_display(payload: dict, resource: dict, fallback: str | None) -> str | None:
    return (
        payload.get("organization_name")
        or payload.get("organizationName")
        or payload.get("resourceContainers", {}).get("account", {}).get("name")
        or resource.get("resourceContainers", {}).get("account", {}).get("name")
        or fallback
    )


def _build_fallback_metric(resource: dict, build_id: int, organization_name: str | None, project_name: str | None) -> TimelineMetric:
    definition = resource.get("definition", {})
    pipeline_id = int(definition.get("id") or resource.get("pipelineId") or 0)
    pipeline_name = definition.get("name") or resource.get("pipelineName") or f"pipeline-{pipeline_id or 'unknown'}"
    result = resource.get("result") or resource.get("status")
    now = datetime.now(timezone.utc)
    queue_time = _parse_resource_datetime(resource.get("queueTime"))
    start_time = _parse_resource_datetime(resource.get("startTime"))
    finish_time = _parse_resource_datetime(resource.get("finishTime"))
    timeline_start = start_time or queue_time or finish_time or now
    timeline_finish = finish_time or start_time or queue_time or now

    duration_seconds = None
    if timeline_start and timeline_finish:
        duration_seconds = max(0.0, (timeline_finish - timeline_start).total_seconds())

    return TimelineMetric(
        run_id=build_id,
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_name,
        organization_name=organization_name,
        project_name=project_name,
        level="stage",
        stage_name="summary",
        job_name=None,
        task_name=None,
        agent_name=None,
        queue_time=queue_time or now,
        start_time=timeline_start,
        finish_time=timeline_finish,
        duration_seconds=duration_seconds,
        result=result,
        retry_count=0,
        source_branch=resource.get("sourceBranch"),
        source_version=resource.get("sourceVersion"),
        requested_by=((resource.get("requestedFor") or {}).get("displayName") if isinstance(resource.get("requestedFor"), dict) else resource.get("requestedFor")),
        is_degraded=True,
        data_quality="degraded",
        failure_log_excerpt=None,
        log_id=None,
        record_id=f"fallback-{build_id}",
        parent_id=None,
    )


def _parse_resource_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@app.route(route="get_recommendations", methods=["POST"])
def get_recommendations(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        pipeline_id = int(body["pipeline_id"])
        settings = get_settings()
        repository = AlertRepository(settings.sql_connection_string)
        if repository.count_runs(pipeline_id) < settings.min_history_runs:
            message = f"Not enough run history yet for this pipeline - need at least {settings.min_history_runs} runs."
            return func.HttpResponse(json.dumps({"message": message}), status_code=200, mimetype="application/json")
        summary = build_analysis_summary(repository.get_pipeline_metrics(pipeline_id))
        client = PipelineRecommendationClient(settings.azure_openai_endpoint, settings.azure_openai_deployment, settings.azure_openai_api_version, os.environ.get("AZURE_OPENAI_API_KEY"))
        recommendations = client.recommend(summary)
        findings = [finding.__dict__ for finding in recommendations.findings]
        repository.upsert_recommendations(pipeline_id, findings)
        return func.HttpResponse(json.dumps({"pipeline_id": pipeline_id, "findings": findings}), mimetype="application/json")
    except (ValueError, KeyError, TypeError) as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        logging.exception("get_recommendations failed")
        return func.HttpResponse("Unable to generate recommendations.", status_code=500)
@app.route(route="ingest_pipeline", methods=["POST"])
def ingest_pipeline(req: func.HttpRequest) -> func.HttpResponse:
    """Initial historical ingestion for a user-selected ADO pipeline.

    The PAT is accepted only for this HTTPS request and is never written to SQL or logs.
    Ongoing webhook ingestion uses the configured Key Vault/env secret via get_ado_pat().
    """
    try:
        raw_body = req.get_body().decode("utf-8-sig").strip()
        logging.warning("INGEST_PIPELINE_V2_RAW_BODY=%r", raw_body)
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            logging.error("INGEST_PIPELINE_V2_JSON_ERROR=%s", exc)
            return func.HttpResponse(
                "V2_JSON_PARSE_ERROR",
                status_code=400
            )
        organization = str(body.get("organization", "")).strip()
        project = str(body.get("project", "")).strip()
        pipeline_id = int(body.get("pipeline_id"))
        days = int(body.get("days", 90))

        if not organization or not project:
            return func.HttpResponse(
                "organization and project are required.",
                status_code=400
            )

        if days < 1 or days > 730:
            return func.HttpResponse(
                "days must be between 1 and 730.",
                status_code=400
            )

        pat = get_ado_pat()
        client = AzureDevOpsClient(organization, pat)
        builds = client.list_builds(project, pipeline_id=pipeline_id, min_time=datetime.now(timezone.utc) - timedelta(days=days), top=200)
        completed = [b for b in builds if b.get("finishTime") and b.get("status") == "completed"]
        repository = AlertRepository(get_settings().sql_connection_string)
        total_records = 0
        processed = 0
        for build in completed:
            build_id = int(build["id"])
            metrics = client.flatten_timeline(build, client.get_timeline(project, build_id))
            if metrics:
                metrics = [m.__class__(**{**m.__dict__, "organization_name": organization, "project_name": project}) for m in metrics]
                for i, metric in enumerate(metrics):
                    if metric.level == "task" and str(metric.result or "").lower() == "failed" and metric.log_id:
                        try:
                            metrics[i] = metric.__class__(**{**metric.__dict__, "failure_log_excerpt": client.get_log_tail(project, build_id, metric.log_id)})
                        except requests.RequestException:
                            logging.warning("Could not retrieve failure log for run %s", build_id)
                repository.upsert_metrics(metrics)
                total_records += len(metrics)
                processed += 1
        logging.info("ingest_pipeline completed: organization=%s project=%s pipeline_id=%s runs=%s records=%s", organization, project, pipeline_id, processed, total_records)
        return func.HttpResponse(json.dumps({"organization": organization, "project": project, "pipeline_id": pipeline_id, "completed_runs_found": len(completed), "runs_ingested": processed, "records_upserted": total_records}), mimetype="application/json")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        return func.HttpResponse(f"Azure DevOps returned HTTP {code}.", status_code=502 if code not in {401,403} else 401)
    except (ValueError, KeyError) as exc:
        return func.HttpResponse(str(exc), status_code=400)
    except Exception:
        logging.exception("ingest_pipeline failed")
        return func.HttpResponse("Unable to ingest pipeline history.", status_code=500)

import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import azure.functions as func

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
        project = _extract_project(payload, resource)
        build_id = resource.get("id") or resource.get("buildId") or payload.get("runId")
        if not all([organization, project, build_id]):
            return func.HttpResponse("Webhook must include organization, project, and run/build ID.", status_code=400)
        build_id_int = int(build_id)
        try:
            client = AzureDevOpsClient(organization, get_ado_pat())
            build = client.get_build(project, build_id_int)
            metrics = client.flatten_timeline(build, client.get_timeline(project, build_id_int))
            for index, metric in enumerate(metrics):
                if metric.level == "task" and metric.result == "failed" and metric.log_id:
                    metrics[index] = metric.__class__(**{**metric.__dict__, "failure_log_excerpt": client.get_log_tail(project, build_id_int, metric.log_id)})
        except Exception:
            logging.exception("ingest_run enrichment failed; using fallback metric", extra={"run_id": build_id_int})
            metrics = [_build_fallback_metric(resource, build_id_int)]
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
        or resource.get("project", {}).get("id")
        or resource.get("definition", {}).get("project", {}).get("id")
        or payload.get("project")
        or payload.get("resourceContainers", {}).get("project", {}).get("id")
    )


def _build_fallback_metric(resource: dict, build_id: int) -> TimelineMetric:
    definition = resource.get("definition", {})
    pipeline_id = int(definition.get("id") or resource.get("pipelineId") or 0)
    pipeline_name = definition.get("name") or resource.get("pipelineName") or f"pipeline-{pipeline_id or 'unknown'}"
    result = resource.get("result") or resource.get("status")
    now = datetime.now(timezone.utc)
    return TimelineMetric(
        run_id=build_id,
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_name,
        level="stage",
        stage_name="summary",
        job_name=None,
        task_name=None,
        agent_name=None,
        queue_time=now,
        start_time=now,
        finish_time=now,
        duration_seconds=0,
        result=result,
        retry_count=0,
        failure_log_excerpt=None,
        log_id=None,
        record_id=f"fallback-{build_id}",
        parent_id=None,
    )


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
import json
import logging
import os

import azure.functions as func

from core.ado_client import AzureDevOpsClient
from core.config import get_ado_pat, get_settings
from core.db import AlertRepository, build_analysis_summary
from core.openai_client import PipelineRecommendationClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="ingest_run", methods=["POST"])
def ingest_run(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()
        resource = payload.get("resource", payload)
        organization = payload.get("resourceContainers", {}).get("account", {}).get("id") or payload.get("organization")
        project = resource.get("project", {}).get("name") or payload.get("project")
        build_id = resource.get("id") or resource.get("buildId") or payload.get("runId")
        if not all([organization, project, build_id]):
            return func.HttpResponse("Webhook must include organization, project, and run/build ID.", status_code=400)
        client = AzureDevOpsClient(organization, get_ado_pat())
        build = client.get_build(project, int(build_id))
        metrics = client.flatten_timeline(build, client.get_timeline(project, int(build_id)))
        for index, metric in enumerate(metrics):
            if metric.level == "task" and metric.result == "failed" and metric.log_id:
                metrics[index] = metric.__class__(**{**metric.__dict__, "failure_log_excerpt": client.get_log_tail(project, int(build_id), metric.log_id)})
        AlertRepository(get_settings().sql_connection_string).upsert_metrics(metrics)
        logging.info("ingest_run completed", extra={"run_id": build_id, "metric_count": len(metrics)})
        return func.HttpResponse(json.dumps({"run_id": build_id, "records_upserted": len(metrics)}), mimetype="application/json")
    except (ValueError, KeyError) as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        logging.exception("ingest_run failed")
        return func.HttpResponse("Unable to ingest pipeline run.", status_code=500)


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
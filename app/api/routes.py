from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as ApiPath
from app.core.db import fetch_one
from app.repositories.pipeline_repository import PipelineRepository
from app.services.pipeline_service import PipelineService
from app.services.ai_service import AIService
from app.core.config import get_settings
from app.core.errors import ServiceConfigError
from app.schemas.api import AnalyzeRequest
from app.schemas.connection import AdoConnectRequest, AdoConnectResponse, AdoProject, AdoPipeline, AdoIngestRequest
from core.ado_client import AzureDevOpsClient
from core.config import get_ado_pat
from core.db import AlertRepository
from datetime import datetime, timezone, timedelta
import threading
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

router = APIRouter(prefix="/api/v1")

MAX_ID = 2**31 - 1
RunId = Annotated[int, ApiPath(ge=1, le=MAX_ID)]
PipelineId = Annotated[int, ApiPath(ge=1, le=MAX_ID)]
GENERIC_UNAVAILABLE = "The service is temporarily unavailable. Please try again later."


def _unavailable(exc: Exception, message: str = GENERIC_UNAVAILABLE) -> HTTPException:
    """Build a 503 without leaking internals: configuration errors are safe to show, everything else is logged only."""
    if isinstance(exc, ServiceConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    logging.exception("API request failed")
    return HTTPException(status_code=503, detail=message)


def _resolve_pat(organization: str, supplied: str | None) -> str:
    """Use the caller's PAT, or fall back to the server-side PAT only for allow-listed organizations."""
    if supplied:
        return supplied.strip()
    allowed = get_settings().allowed_ado_org_list
    if allowed and organization.lower() not in allowed:
        raise HTTPException(status_code=403, detail="A personal access token is required for this organization.")
    try:
        return get_ado_pat(organization)
    except Exception as exc:
        logging.warning("Server-side PAT lookup failed: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="A personal access token is required for Azure DevOps access.") from exc
service = PipelineService()
repo = PipelineRepository()
ai_service = AIService()

@router.get("/health")
def health():
    try:
        row = fetch_one("SELECT 1 AS ok")
        return {"status": "ok", "database": "ok" if row and row["ok"] == 1 else "unknown"}
    except Exception as exc:
        raise _unavailable(exc, "Database unavailable.") from exc

@router.get("/options")
def options():
    try:
        return service.options()
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/summary")
def summary(pipeline_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None, days: int = Query(90, ge=1, le=730)):
    try:
        return service.summary(pipeline_id, days)
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/trends")
def trends(pipeline_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None, days: int = Query(90, ge=1, le=730)):
    try:
        return service.trends(pipeline_id, days)
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/runs")
def runs(
    pipeline_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(100, ge=1, le=1000),
    status: Annotated[str | None, Query(max_length=32, pattern=r"^[A-Za-z]+$")] = None,
    days: Annotated[int | None, Query(ge=1, le=730)] = None,
):
    try:
        return service.runs(pipeline_id, page, page_size, status, days)
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/runs/{run_id}/timeline")
def timeline(run_id: RunId):
    try:
        return repo.timeline(run_id)
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/runs/{run_id}/analysis")
def run_analysis(run_id: RunId):
    try:
        return repo.run_analysis(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/runs/{run_id}/logs")
def logs(run_id: RunId):
    try:
        return repo.logs(run_id)
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/pipelines/{pipeline_id}/recommendations")
def recommendations(pipeline_id: PipelineId, limit: int = Query(50, ge=1, le=100)):
    try:
        return {"pipeline_id": pipeline_id, "findings": repo.recommendations(pipeline_id, limit)}
    except Exception as exc:
        raise _unavailable(exc) from exc

@router.get("/pools")
def pools(days: int = Query(30, ge=1, le=730)):
    try:
        return {"window_days": days, "pools": repo.pools(days)}
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.post("/pipelines/{pipeline_id}/analyze")
def analyze(pipeline_id: PipelineId, request: AnalyzeRequest):
    try:
        return ai_service.analyze(pipeline_id, request.months * 31)
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.post("/ado/connect", response_model=AdoConnectResponse)
def ado_connect(request: AdoConnectRequest):
    """Discover projects and pipelines using a transient PAT.

    If no PAT is supplied, the existing Key Vault/env configuration is used
    for team-managed deployments. The supplied PAT is never persisted.
    """
    try:
        organization = request.organization.strip()
        pat = _resolve_pat(organization, request.pat)
        client = AzureDevOpsClient(organization, pat)
        projects_raw = client.list_projects()
        projects = [AdoProject(id=str(p["id"]), name=p["name"]) for p in projects_raw]
        pipelines: list[AdoPipeline] = []
        for project in projects:
            for item in client.list_pipelines(project.name):
                pipelines.append(AdoPipeline(
                    id=int(item["id"]), name=item.get("name", str(item["id"])),
                    project_id=project.id, project_name=project.name,
                ))
        return AdoConnectResponse(organization=organization, projects=projects, pipelines=pipelines)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in {401, 403}:
            raise HTTPException(status_code=401, detail="Azure DevOps authentication failed. Check the PAT permissions and organization name.") from exc
        raise HTTPException(status_code=502, detail=f"Azure DevOps returned HTTP {code}.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.error("Azure DevOps connection failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Azure DevOps connection failed.") from exc


import json
import tempfile
from pathlib import Path

_ingestion_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

def _get_state_file_path() -> Path:
    return Path(tempfile.gettempdir()) / "ado_ingestion_state.json"

def _load_persisted_jobs() -> dict:
    try:
        p = _get_state_file_path()
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logging.warning("Failed to load persisted ingestion state: %s", exc)
    return {}

def _save_persisted_jobs():
    try:
        p = _get_state_file_path()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_ingestion_jobs, f)
    except Exception as exc:
        logging.warning("Failed to save ingestion state: %s", exc)


def _run_historical_ingestion(organization: str, pat: str, project: str, pipeline_id: int, days: int, job_key: str):
    try:
        client = AzureDevOpsClient(organization, pat)
        settings = get_settings()
        repository = AlertRepository(settings.sql_connection_string)

        builds = client.list_builds(
            project,
            pipeline_id=pipeline_id,
            min_time=datetime.now(timezone.utc) - timedelta(days=days),
            top=200,
            max_builds=5000,
        )
        completed = [b for b in builds if b.get("finishTime") and b.get("status") == "completed"]
        completed_ids = {int(b["id"]) for b in completed}

        # Check runs already stored in SQL database so we skip re-ingesting them
        existing_run_ids = repository.get_existing_run_ids(pipeline_id)
        already_ingested = existing_run_ids.intersection(completed_ids)
        already_count = len(already_ingested)
        missing_builds = [b for b in completed if int(b["id"]) not in existing_run_ids]

        logging.info(
            "Historical ingestion for pipeline %s: %d total in ADO, %d already in SQL, %d missing to ingest",
            pipeline_id,
            len(completed),
            already_count,
            len(missing_builds),
        )

        with _jobs_lock:
            if job_key in _ingestion_jobs:
                _ingestion_jobs[job_key]["total_runs"] = len(completed)
                _ingestion_jobs[job_key]["processed_runs"] = already_count
                _save_persisted_jobs()

        if not missing_builds:
            logging.info("All %d runs for pipeline %s are already ingested into SQL.", len(completed), pipeline_id)
            with _jobs_lock:
                if job_key in _ingestion_jobs:
                    _ingestion_jobs[job_key]["status"] = "completed"
                    _ingestion_jobs[job_key]["processed_runs"] = len(completed)
                    _ingestion_jobs[job_key]["finish_time"] = datetime.now(timezone.utc).isoformat()
                    _save_persisted_jobs()
            return

        def process_and_save_build(build: dict) -> int:
            b_id = int(build["id"])
            timeline = client.get_timeline(project, b_id)
            metrics = client.flatten_timeline(build, timeline)
            if not metrics:
                return 0
            metrics = [m.__class__(**{**m.__dict__, "organization_name": organization, "project_name": project}) for m in metrics]
            for i, metric in enumerate(metrics):
                if metric.level == "task" and str(metric.result or "").lower() == "failed" and metric.log_id:
                    try:
                        metrics[i] = metric.__class__(**{**metric.__dict__, "failure_log_excerpt": client.get_log_tail(project, b_id, metric.log_id)})
                    except Exception as log_exc:
                        logging.debug("Could not fetch failure log for build %s: %s", b_id, type(log_exc).__name__)
            repository.upsert_metrics(metrics)
            return len(metrics)

        processed_count = already_count
        total_records = 0

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_build = {executor.submit(process_and_save_build, b): b for b in missing_builds}
            for future in as_completed(future_to_build):
                build = future_to_build[future]
                try:
                    records = future.result()
                    total_records += records
                    processed_count += 1
                except Exception as err:
                    logging.warning("Error ingesting build %s: %s", build.get("id"), err)
                    processed_count += 1

                with _jobs_lock:
                    if job_key in _ingestion_jobs:
                        _ingestion_jobs[job_key]["processed_runs"] = processed_count
                        _ingestion_jobs[job_key]["records_upserted"] = total_records
                        _ingestion_jobs[job_key]["current_run_date"] = build.get("finishTime")
                        _save_persisted_jobs()

        with _jobs_lock:
            if job_key in _ingestion_jobs:
                _ingestion_jobs[job_key]["status"] = "completed"
                _ingestion_jobs[job_key]["processed_runs"] = len(completed)
                _ingestion_jobs[job_key]["finish_time"] = datetime.now(timezone.utc).isoformat()
                _save_persisted_jobs()
    except Exception as exc:
        logging.exception("Background ingestion failed for %s", job_key)
        with _jobs_lock:
            if job_key in _ingestion_jobs:
                _ingestion_jobs[job_key]["status"] = "failed"
                _ingestion_jobs[job_key]["error"] = f"Ingestion failed ({type(exc).__name__}); see server logs."
                _save_persisted_jobs()


@router.post("/ado/ingest")
def ado_ingest(request: AdoIngestRequest):
    """Start initial historical ingestion asynchronously in background."""
    organization = request.organization.strip()
    project = request.project.strip()
    pat = _resolve_pat(organization, request.pat)
    if not pat:
        raise HTTPException(status_code=401, detail="A PAT is required for Azure DevOps access.")

    job_key = f"{organization}:{request.pipeline_id}"

    with _jobs_lock:
        existing = _ingestion_jobs.get(job_key)
        if existing and existing.get("status") == "running":
            return existing

        _ingestion_jobs[job_key] = {
            "status": "running",
            "organization": organization,
            "project": project,
            "pipeline_id": request.pipeline_id,
            "days": request.days,
            "processed_runs": 0,
            "total_runs": None,
            "records_upserted": 0,
            "current_run_date": None,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "finish_time": None,
            "error": None,
        }
        _save_persisted_jobs()

    thread = threading.Thread(
        target=_run_historical_ingestion,
        args=(organization, pat, project, request.pipeline_id, request.days, job_key),
        daemon=True,
    )
    thread.start()

    return {
        "status": "running",
        "message": f"Historical ingestion for the last {request.days} days started in background.",
        "pipeline_id": request.pipeline_id,
        "processed_runs": 0,
        "total_runs": None,
    }


@router.get("/ado/ingest/status")
def ado_ingest_status(
    organization: Annotated[str, Query(max_length=256)] = "",
    pipeline_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
):
    """Get the current progress of background ingestion for a pipeline or the active job."""
    global _ingestion_jobs
    with _jobs_lock:
        disk_jobs = _load_persisted_jobs()
        for k, v in disk_jobs.items():
            if k not in _ingestion_jobs:
                _ingestion_jobs[k] = v

        if organization and pipeline_id:
            job_key = f"{organization.strip()}:{pipeline_id}"
            job = _ingestion_jobs.get(job_key)
            if job:
                return job
            return {"status": "idle", "processed_runs": 0, "total_runs": 0}

        # If no specific key or looking for active job
        running = [j for j in _ingestion_jobs.values() if j.get("status") == "running"]
        if running:
            return running[-1]

        # Return latest job if any exist
        if _ingestion_jobs:
            return list(_ingestion_jobs.values())[-1]

        return {"status": "idle", "processed_runs": 0, "total_runs": 0}


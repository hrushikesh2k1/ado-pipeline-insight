from fastapi import APIRouter, HTTPException, Query
from backend.app.core.db import fetch_one
from backend.app.repositories.pipeline_repository import PipelineRepository
from backend.app.services.pipeline_service import PipelineService
from backend.app.services.ai_service import AIService
from backend.app.schemas.api import AnalyzeRequest
from backend.app.schemas.connection import AdoConnectRequest, AdoConnectResponse, AdoProject, AdoPipeline, AdoIngestRequest
from core.ado_client import AzureDevOpsClient
import os
import requests

router = APIRouter(prefix="/api/v1")
service = PipelineService()
repo = PipelineRepository()
ai_service = AIService()

@router.get("/health")
def health():
    try:
        row = fetch_one("SELECT 1 AS ok")
        return {"status": "ok", "database": "ok" if row and row["ok"] == 1 else "unknown"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

@router.get("/options")
def options():
    try:
        return service.options()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/summary")
def summary(pipeline_id: int | None = None, days: int = Query(90, ge=1, le=730)):
    try:
        return service.summary(pipeline_id, days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/trends")
def trends(pipeline_id: int | None = None, days: int = Query(90, ge=1, le=730)):
    try:
        return service.trends(pipeline_id, days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/runs")
def runs(pipeline_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), status: str | None = None):
    try:
        return service.runs(pipeline_id, page, page_size, status)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/runs/{run_id}/timeline")
def timeline(run_id: int):
    try:
        return repo.timeline(run_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/runs/{run_id}/analysis")
def run_analysis(run_id: int):
    try:
        return repo.run_analysis(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/runs/{run_id}/logs")
def logs(run_id: int):
    try:
        return repo.logs(run_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/pipelines/{pipeline_id}/recommendations")
def recommendations(pipeline_id: int, limit: int = Query(50, ge=1, le=100)):
    try:
        return {"pipeline_id": pipeline_id, "findings": repo.recommendations(pipeline_id, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/pools")
def pools(days: int = Query(30, ge=1, le=730)):
    try:
        return {"window_days": days, "pools": repo.pools(days)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/pipelines/{pipeline_id}/analyze")
def analyze(pipeline_id: int, request: AnalyzeRequest):
    try:
        return ai_service.analyze(pipeline_id, request.months * 31)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ado/connect", response_model=AdoConnectResponse)
def ado_connect(request: AdoConnectRequest):
    """Validate an ADO PAT and discover projects/pipelines without persisting the secret."""
    try:
        client = AzureDevOpsClient(request.organization.strip(), request.pat)
        projects_raw = client.list_projects()
        projects = [AdoProject(id=str(p["id"]), name=p["name"]) for p in projects_raw]
        pipelines: list[AdoPipeline] = []
        for project in projects:
            for item in client.list_pipelines(project.name):
                pipelines.append(AdoPipeline(
                    id=int(item["id"]), name=item.get("name", str(item["id"])),
                    project_id=project.id, project_name=project.name,
                ))
        return AdoConnectResponse(organization=request.organization.strip(), projects=projects, pipelines=pipelines)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in {401, 403}:
            raise HTTPException(status_code=401, detail="Azure DevOps authentication failed. Check the PAT permissions and organization name.") from exc
        raise HTTPException(status_code=502, detail=f"Azure DevOps returned HTTP {code}.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Azure DevOps connection failed: {exc}") from exc


@router.post("/ado/ingest")
def ado_ingest(request: AdoIngestRequest):
    """Start initial historical ingestion through the Azure Function."""
    function_url = get_settings().ingest_function_url.strip()
    if not function_url:
        raise HTTPException(status_code=503, detail="INGEST_FUNCTION_URL is not configured.")
    try:
        response = requests.post(function_url, json=request.model_dump(), timeout=60)
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise HTTPException(status_code=502, detail=f"Ingestion function failed: {detail}")
        return response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Unable to reach ingestion function: {exc}") from exc

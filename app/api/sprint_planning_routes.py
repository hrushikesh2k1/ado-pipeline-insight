"""Sprint planning over HTTP. The plan is returned for display only: nothing is written to Azure DevOps."""
from __future__ import annotations

import logging

import requests
from fastapi import APIRouter, Header, HTTPException, Query

from app.api.routes import _resolve_pat
from app.schemas.sprint_planning import SprintCommitRequest, SprintCommitResponse, SprintPlan, SprintPlanRequest, SprintPlanningSetup
from app.services import sprint_planning
from core.ado_client import AzureDevOpsClient
from core.validation import validate_organization, validate_project

router = APIRouter(prefix="/api/v1")


def _names(organization: str, project: str) -> tuple[str, str]:
    """The organization and project names, checked: a name that cannot be one is a 422 for the caller, not a server error."""
    try:
        return validate_organization(organization.strip()), validate_project(project.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _explain(exc: Exception) -> HTTPException:
    """The HTTP error for a planning failure, in words the person planning can act on."""
    if isinstance(exc, sprint_planning.PlanningError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        if code in {401, 403, 203}:
            return HTTPException(status_code=401, detail="Azure DevOps authentication failed. Check that the PAT can read Work Items, Project and team.")
        if code == 404:
            return HTTPException(status_code=404, detail="The project, the team or a sprint was not found in Azure DevOps.")
        return HTTPException(status_code=502, detail=f"Azure DevOps returned HTTP {code}.")
    logging.error("Sprint planning failed: %s", type(exc).__name__)
    return HTTPException(status_code=502, detail="Sprint planning failed. Nothing was changed in Azure DevOps.")


@router.get("/ado/sprint-planning/setup", response_model=SprintPlanningSetup, tags=["ado"], operation_id="sprint_planning_setup")
def sprint_planning_setup(
    organization: str = Query(..., min_length=1, max_length=256),
    project: str = Query(..., min_length=1, max_length=256),
    team: str = Query(..., min_length=1, max_length=256),
    pat: str | None = Query(default=None, max_length=512),
    x_ado_pat: str | None = Header(default=None, alias="X-ADO-PAT"),
) -> SprintPlanningSetup:
    """What the planning page needs: the team's sprints (with the current and the next one proposed), its members, the area paths to choose from and the story types."""
    org_clean, proj_clean = _names(organization, project)
    token = _resolve_pat(org_clean, pat or x_ado_pat)
    try:
        return SprintPlanningSetup(**sprint_planning.team_setup(AzureDevOpsClient(organization=org_clean, pat=token), proj_clean, team.strip()))
    except Exception as exc:
        raise _explain(exc) from exc


@router.post("/ado/sprint-planning/plan", response_model=SprintPlan, tags=["ado"], operation_id="sprint_planning_plan")
def sprint_planning_plan(payload: SprintPlanRequest) -> SprintPlan:
    """Plan the next sprint: each person's stories (carried over and new, by area of choice), and the carried-over stories that are blocked or have been
    active too long with their last 3 comments. IMPORTANT: the plan is only returned for display. Nothing is written to Azure DevOps."""
    org_clean, proj_clean = _names(payload.organization, payload.project)
    token = _resolve_pat(org_clean, payload.pat)
    try:
        plan = sprint_planning.plan_sprint(
            AzureDevOpsClient(organization=org_clean, pat=token), organization=org_clean, project=proj_clean, team=payload.team.strip(),
            from_iteration_id=payload.from_iteration_id, to_iteration_id=payload.to_iteration_id,
            people=[p.model_dump() for p in payload.people], per_person=payload.per_person, active_days=payload.active_days, work_item_types=payload.work_item_types,
            sprint_goal=payload.sprint_goal, capacity_mode=payload.capacity_mode, focus_factor=payload.focus_factor,
            tags=payload.tags, area_filter=payload.area_filter,
        )
    except Exception as exc:
        raise _explain(exc) from exc
    return SprintPlan(**plan)


@router.post("/ado/sprint-planning/commit", response_model=SprintCommitResponse, tags=["ado"], operation_id="sprint_planning_commit")
def sprint_planning_commit(payload: SprintCommitRequest) -> SprintCommitResponse:
    """Commit the chosen plan assignments and iteration path into Azure DevOps."""
    org_clean, proj_clean = _names(payload.organization, payload.project)
    token = _resolve_pat(org_clean, payload.pat)
    try:
        result = sprint_planning.commit_sprint_plan(
            AzureDevOpsClient(organization=org_clean, pat=token),
            project=proj_clean,
            iteration_path=payload.to_iteration_path.strip(),
            assignments=[a.model_dump() for a in payload.assignments],
            sprint_goal=payload.sprint_goal,
        )
    except Exception as exc:
        raise _explain(exc) from exc
    return SprintCommitResponse(**result)


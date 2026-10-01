from typing import Any
from pydantic import BaseModel, Field, field_validator

from core.validation import validate_organization, validate_pat, validate_project


class _Validated(BaseModel):
    @field_validator("organization", check_fields=False)
    @classmethod
    def _organization(cls, value: str) -> str:
        return validate_organization(value)

    @field_validator("project", check_fields=False)
    @classmethod
    def _project(cls, value: str) -> str:
        return validate_project(value)

    @field_validator("pat", check_fields=False)
    @classmethod
    def _pat(cls, value: str | None) -> str | None:
        return None if value is None else validate_pat(value.strip())


class AdoConnectRequest(_Validated):
    organization: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, min_length=1, max_length=512)

class AdoProject(BaseModel):
    id: str
    name: str

class AdoPipeline(BaseModel):
    id: int
    name: str
    project_id: str | None = None
    project_name: str | None = None

class AdoConnectResponse(BaseModel):
    organization: str
    projects: list[AdoProject]
    pipelines: list[AdoPipeline]

class AdoIngestRequest(_Validated):
    organization: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, min_length=1, max_length=512)
    project: str = Field(min_length=1, max_length=256)
    pipeline_id: int = Field(ge=1, le=2**31 - 1)
    days: int = Field(default=90, ge=1, le=730)
    max_runs: int | None = Field(default=300, ge=1, le=5000)

class AdoRepository(BaseModel):
    id: str
    name: str
    default_branch: str | None = None
    web_url: str | None = None

class AdoReviewer(BaseModel):
    id: str | None = None
    display_name: str
    unique_name: str | None = None
    image_url: str | None = None
    vote: int = 0
    is_required: bool = False

class AdoPullRequest(BaseModel):
    id: int
    title: str
    description: str | None = None
    status: str
    created_by_name: str
    created_by_avatar: str | None = None
    creation_date: str
    source_branch: str
    target_branch: str
    repository_id: str
    repository_name: str
    project_name: str
    is_draft: bool = False
    merge_status: str | None = None
    reviewers: list[AdoReviewer] = Field(default_factory=list)
    web_url: str | None = None
    comments_count: int | None = None


class PullRequestReviewRequest(BaseModel):
    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    repository_id: str = Field(min_length=1, max_length=256)
    pull_request_id: int = Field(ge=1, le=2**31 - 1)
    pat: str | None = Field(default=None, max_length=512)


class PullRequestReviewCommentSchema(BaseModel):
    id: str
    category: str
    severity: str
    title: str
    comment: str
    file_path: str | None = None
    line_number: int | None = None
    suggestion_code: str | None = None


class PullRequestReviewResponseSchema(BaseModel):
    pull_request_id: int
    verdict: str
    summary: str
    scorecard: dict[str, str] = Field(default_factory=dict)
    comments: list[PullRequestReviewCommentSchema] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)
    posted_to_ado: bool = False


class AdoTeam(BaseModel):
    id: str
    name: str
    description: str | None = None


class AdoIteration(BaseModel):
    id: str
    name: str
    path: str
    start_date: str | None = None
    finish_date: str | None = None
    time_frame: str | None = None


class AdoWorkItem(BaseModel):
    id: int
    title: str
    work_item_type: str
    state: str
    assigned_to_name: str | None = None
    assigned_to_avatar: str | None = None
    remaining_work: float | None = None
    completed_work: float | None = None
    original_estimate: float | None = None
    parent_id: int | None = None
    state_change_date: str | None = None
    changed_date: str | None = None
    web_url: str | None = None
    business_days_in_review: int | None = None
    is_closed_without_hours: bool = False
    is_stale_in_review: bool = False
    description: str | None = None
    acceptance_criteria: str | None = None
    area_path: str | None = None
    severity: str | None = None
    priority: int | None = None


class AdoSprintChecksSummary(BaseModel):
    total_tasks: int = 0
    tasks_closed_count: int = 0
    tasks_closed_without_hours_count: int = 0
    total_user_stories: int = 0
    stories_in_review_count: int = 0
    stories_in_review_stale_count: int = 0
    flagged_item_ids: list[int] = Field(default_factory=list)


class AdoMilestoneItem(BaseModel):
    id: int
    title: str
    work_item_type: str
    state: str
    assigned_to_name: str | None = None
    assigned_to_avatar: str | None = None
    completed_date: str | None = None
    web_url: str | None = None
    category: str = "Feature & Business Value"
    milestone_stream: str = "Alert Creation & Telemetry"
    hours_delivered: float = 0.0
    child_tasks_total: int = 0
    child_tasks_closed: int = 0
    description: str | None = None
    acceptance_criteria: str | None = None
    issue_summary: str | None = None
    achievement_summary: str | None = None


class MilestoneStreamMetric(BaseModel):
    name: str
    total_count: int = 0
    closed_count: int = 0
    delivered_hours: float = 0.0
    completion_pct: float = 0.0
    issues_addressed_count: int = 0
    next_sprint_baseline_target: int = 0
    next_sprint_recommendation: str = ""


class MilestoneGraphData(BaseModel):
    streams: list[MilestoneStreamMetric] = Field(default_factory=list)
    overall_reliability_baseline_pct: float = 0.0
    bug_resolution_rate_pct: float = 0.0
    next_sprint_recommended_capacity: str = ""
    next_sprint_focus_areas: list[str] = Field(default_factory=list)


class AdoSprintMilestoneSummary(BaseModel):
    total_stories: int = 0
    closed_stories_count: int = 0
    open_stories_count: int = 0
    completion_rate_pct: float = 0.0
    total_delivered_hours: float = 0.0
    features_delivered_count: int = 0
    bugs_resolved_count: int = 0
    achieved_items: list[AdoMilestoneItem] = Field(default_factory=list)
    key_achievements: list[str] = Field(default_factory=list)
    graph_data: MilestoneGraphData | None = None


class AdoSprintBoardResponse(BaseModel):
    team: AdoTeam
    iteration: AdoIteration | None = None
    work_items: list[AdoWorkItem] = Field(default_factory=list)
    checks_summary: AdoSprintChecksSummary
    working_days_remaining: int | None = None
    milestone: AdoSprintMilestoneSummary | None = None


class MilestoneAiSummaryRequest(BaseModel):
    sprint_name: str | None = None
    team_name: str | None = None
    achieved_items: list[dict[str, Any]] = Field(default_factory=list)
    total_stories: int = 0
    closed_stories_count: int = 0
    total_delivered_hours: float = 0.0


class MilestoneAiSummaryResponse(BaseModel):
    summary: str
    highlights: list[str] = Field(default_factory=list)
    business_impact: str | None = None
    issues_summary: list[dict[str, str]] = Field(default_factory=list)
    achievements_summary: list[dict[str, str]] = Field(default_factory=list)
    graph_data: MilestoneGraphData | None = None


# ============================================================================
# Release Readiness Scorecard Schemas
# ============================================================================

class ReleaseBranchCandidate(BaseModel):
    branch: str
    last_built: str | None = None
    run_count: int = 0
    is_default: bool = False


class ReleaseDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    organization_name: str = Field(min_length=1, max_length=256)
    project_name: str = Field(min_length=1, max_length=256)
    repository_id: str | None = Field(default=None, max_length=256)
    repository_name: str | None = Field(default=None, max_length=256)
    pipeline_id: int | None = Field(default=None, ge=1)
    target_branch: str = Field(min_length=1, max_length=512)
    scope_feature_title: str | None = Field(default=None, max_length=512)
    target_ship_date: str | None = Field(default=None, max_length=32)


class ReleaseDefinition(BaseModel):
    release_id: str
    name: str
    organization_name: str
    project_name: str
    repository_id: str | None = None
    repository_name: str | None = None
    pipeline_id: int | None = None
    target_branch: str
    scope_feature_title: str | None = None
    target_ship_date: str | None = None
    created_by: str | None = None
    created_at: str


class ReleaseDimensionEvidenceItem(BaseModel):
    id: str | int
    title: str
    item_type: str
    status_or_result: str
    severity: str | None = None
    web_url: str | None = None
    details: str | None = None


class ReleaseDimension(BaseModel):
    key: str
    name: str
    status: str  # "green" | "yellow" | "red"
    score_text: str
    summary: str
    evidence_items: list[ReleaseDimensionEvidenceItem] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ReleaseScorecard(BaseModel):
    release: ReleaseDefinition
    overall_status: str  # "green" | "yellow" | "red" (worst dimension wins)
    computed_at: str
    dimensions: dict[str, ReleaseDimension]
    ai_narrative: str
    ai_generated: bool = False
    recommendations: list[str] = Field(default_factory=list)


class ReleaseScorecardHistoryItem(BaseModel):
    history_id: int | None = None
    release_id: str
    computed_at: str
    overall_status: str
    dimension_statuses: dict[str, str] = Field(default_factory=dict)


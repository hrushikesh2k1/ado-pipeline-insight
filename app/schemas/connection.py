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
    last_source_commit: str | None = None  # the commit at the tip of the source branch, so a review can tell it is out of date
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
    end_line: int | None = None  # the last line when the comment covers a range; a suggestion replaces lines line_number..end_line
    suggestion_code: str | None = None
    language: str | None = None
    failing_case: str | None = None  # the concrete input or situation, and the wrong result: a finding without one is not shown
    evidence: str | None = None  # the code the finding relies on, quoted from the file
    existing_thread: str | None = None  # set when people already raised this in the pull request comments
    existing_status: str | None = None
    verified: bool | None = None  # True = confirmed by a second check; None = the second check did not run (or, for a static check, was not needed)
    source: str | None = None  # "ai" = found by the AI and checked; "static" = found by an exact check made in code, without the AI
    checked_with: list[str] = Field(default_factory=list)  # what the second check looked up in the repository, for example "read src/Api/Api.csproj"


class PullRequestReviewedFile(BaseModel):
    path: str
    language: str | None = None
    change_type: str = "edit"
    status: str  # reviewed | skipped
    reason: str | None = None  # why a file was skipped
    findings: int = 0
    purpose: str | None = None


class PullRequestChecklistCheck(BaseModel):
    item: str
    checked: bool | None = None
    status: str  # ok | mismatch | open | unverifiable
    evidence: str = ""


class PullRequestReviewResponseSchema(BaseModel):
    pull_request_id: int
    verdict: str
    summary: str
    scorecard: dict[str, str] = Field(default_factory=dict)
    comments: list[PullRequestReviewCommentSchema] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)
    posted_to_ado: bool = False
    method: str = "diff-per-file"
    source_commit: str | None = None
    iterations: int = 0
    files: list[PullRequestReviewedFile] = Field(default_factory=list)
    checklist: list[PullRequestChecklistCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    scope_note: str = ""


class PullRequestReviewJobError(BaseModel):
    status_code: int
    detail: str


class PullRequestReviewJobSchema(BaseModel):
    """A review running in the background: where it is, and, when it is over, the review or why there is none."""
    job_id: str
    status: str  # running | done | failed
    message: str = ""
    done: int = 0
    total: int = 0
    elapsed_seconds: int = 0
    result: PullRequestReviewResponseSchema | None = None
    error: PullRequestReviewJobError | None = None


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
    iteration_path: str | None = None
    iteration_id: int | None = None
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


class AdoWiki(BaseModel):
    id: str
    name: str
    type: str | None = None
    url: str | None = None
    remote_url: str | None = None


class AdoWikiPage(BaseModel):
    id: int | None = None
    path: str
    order: int | None = None
    is_parent_page: bool | None = None
    git_item_path: str | None = None
    sub_pages: list[Any] = Field(default_factory=list)


class IrpCaseInput(BaseModel):
    """A root cause of the alert, as proposed by the analysis and possibly edited by its owner."""

    name: str = Field(min_length=1, max_length=200)
    signal: str | None = Field(default=None, max_length=600)


class IrpGenerateRequest(BaseModel):
    alert_name: str = Field(min_length=1, max_length=256)
    cvrd: str | None = Field(default=None, max_length=256)
    alert_output_columns: str | None = None
    arm_template_context: str | None = None  # the alert's ARM template (JSON); read for its query, threshold, severity and scope
    alert_kql: str | None = Field(default=None, max_length=100_000)  # the alert's KQL query; wins over the one in the ARM template
    alert_details: str | None = None
    target_resource: str | None = Field(default=None, max_length=256)
    severity: str = Field(default="Sev0 (Critical)")
    trigger_condition: str | None = None
    owning_team: str | None = None
    environment: str | None = "Production"
    irp_template: str | None = None
    irp_example: str | None = None
    additional_notes: str | None = None
    cases: list[IrpCaseInput] | None = Field(default=None, max_length=8)  # the root causes to write rows for; proposed from the alert when absent


class IrpAnalyzeRequest(BaseModel):
    alert_name: str = Field(min_length=1, max_length=256)
    alert_output_columns: str | None = None
    arm_template_context: str | None = None
    alert_kql: str | None = Field(default=None, max_length=100_000)
    alert_details: str | None = None
    severity: str = Field(default="Sev0 (Critical)")
    owning_team: str | None = None
    environment: str | None = "Production"
    irp_template: str | None = None
    additional_notes: str | None = None


class IrpAnalyzeResponse(BaseModel):
    facts: dict[str, Any]
    cases: list[dict[str, str]] = Field(default_factory=list)
    severity: str | None = None  # the severity the ARM template gives, as 'Sev1 (Error)'
    notice: str | None = None


class IrpGenerateResponse(BaseModel):
    alert_name: str
    severity: str
    target_resource: str
    markdown_content: str
    suggested_wiki_path: str
    generated_by: str = "ai"  # "ai" when the model wrote it, "built-in" when the canned plan was used
    method: str = "single-pass"  # "case-by-case" (grounded in the alert's ARM/KQL), "single-pass", or "built-in"
    notice: str | None = None  # why the built-in plan was used, or what could not be repaired
    facts: dict[str, Any] | None = None  # what was read from the ARM template and the query
    cases: list[dict[str, str]] | None = None  # the root causes the rows were written for
    scorecard: dict[str, Any] | None = None  # the authoring checklist, checked
    commands: list[dict[str, Any]] | None = None  # every command in the IRP, for QA to test


class IrpPublishRequest(_Validated):
    organization: str = Field(min_length=1, max_length=256)
    project: str = Field(min_length=1, max_length=256)
    pat: str | None = Field(default=None, min_length=1, max_length=512)
    wiki_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    comment: str | None = "Add Incident Response Plan"
    update_inventory: bool = True
    inventory_page_path: str | None = "/Alert-Inventory"
    alert_name: str | None = None
    severity: str | None = "Sev-1"
    owning_team: str | None = "Cloud Operations"


class IrpPublishResponse(BaseModel):
    success: bool
    page_path: str
    wiki_id: str
    inventory_updated: bool
    page_details: dict[str, Any] = Field(default_factory=dict)



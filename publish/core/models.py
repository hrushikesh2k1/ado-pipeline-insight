from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


MetricLevel = Literal["stage", "job", "task"]


@dataclass(frozen=True)
class TimelineMetric:
    run_id: int
    pipeline_id: int
    pipeline_name: str
    level: MetricLevel
    organization_name: str | None = None
    project_name: str | None = None
    stage_name: str | None = None
    job_name: str | None = None
    task_name: str | None = None
    agent_name: str | None = None
    queue_time: datetime | None = None
    source_branch: str | None = None
    source_version: str | None = None
    requested_by: str | None = None
    start_time: datetime | None = None
    finish_time: datetime | None = None
    duration_seconds: float | None = None
    result: str | None = None
    run_result: str | None = None
    retry_count: int = 0
    is_degraded: bool = False
    data_quality: str = "complete"
    failure_log_excerpt: str | None = None
    log_id: int | None = None
    record_id: str | None = None
    parent_id: str | None = None
    build_number: str | None = None
    run_start_time: datetime | None = None
    run_finish_time: datetime | None = None


@dataclass(frozen=True)
class Finding:
    category: Literal[
        "queue_capacity",
        "flaky_step",
        "regression",
        "bottleneck",
        "parallelization_opportunity",
        "caching_opportunity",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    stage_name: str
    task_name: str | None
    recommendation: str
    evidence: str


@dataclass(frozen=True)
class RecommendationResponse:
    findings: list[Finding]


@dataclass(frozen=True)
class PullRequestReviewComment:
    id: str
    category: Literal["correctness", "security", "performance", "maintainability", "test_coverage"]
    severity: Literal["critical", "warning", "suggestion", "praise"]
    title: str
    comment: str
    file_path: str | None = None
    line_number: int | None = None
    suggestion_code: str | None = None


@dataclass(frozen=True)
class PullRequestReviewResponse:
    pull_request_id: int
    verdict: str  # "APPROVED", "APPROVED_WITH_SUGGESTIONS", "CHANGES_REQUESTED"
    summary: str
    scorecard: dict[str, str]
    comments: list[PullRequestReviewComment]
    clarifications: list[str] = field(default_factory=list)
    posted_to_ado: bool = False


@dataclass(frozen=True)
class DoraMetric:
    metric_date: str
    pipeline_id: int
    pipeline_name: str
    organization_name: str | None
    project_name: str | None
    total_runs_count: int
    successful_runs_count: int
    failed_runs_count: int
    change_failure_rate_pct: float
    avg_lead_time_seconds: float | None
    avg_execution_duration_seconds: float | None


@dataclass(frozen=True)
class FailureCluster:
    cluster_id: str
    signature_hash: str
    error_pattern: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences_count: int
    severity: Literal["low", "medium", "high"]
    root_cause_summary: str | None = None
    suggested_yaml_diff: str | None = None
    impacted_pipeline_ids: list[int] | None = None


@dataclass(frozen=True)
class AgentPoolStat:
    metric_date: str
    pool_name: str
    total_runs: int
    total_jobs: int
    avg_job_duration_seconds: float | None
    avg_queue_wait_seconds: float | None
    active_agents_count: int


@dataclass(frozen=True)
class YamlDiffProposal:
    pipeline_id: int
    pipeline_name: str
    target_file: str
    diff_patch: str
    explanation: str
    estimated_time_saved_seconds: float | None = None


@dataclass(frozen=True)
class SprintTeam:
    id: str
    name: str
    description: str | None = None


@dataclass(frozen=True)
class SprintIteration:
    id: str
    name: str
    path: str
    start_date: str | None = None
    finish_date: str | None = None
    time_frame: str | None = None


@dataclass(frozen=True)
class SprintWorkItem:
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


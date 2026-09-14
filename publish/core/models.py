from __future__ import annotations

from dataclasses import dataclass
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
    retry_count: int = 0
    is_degraded: bool = False
    data_quality: str = "complete"
    failure_log_excerpt: str | None = None
    log_id: int | None = None
    record_id: str | None = None
    parent_id: str | None = None
    run_start_time: datetime | None = None
    run_finish_time: datetime | None = None


@dataclass(frozen=True)
class Finding:
    category: Literal[
        "queue_capacity",
        "flaky_step",
        "regression",
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


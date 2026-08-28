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
    stage_name: str | None
    job_name: str | None
    task_name: str | None
    agent_name: str | None
    queue_time: datetime | None
    start_time: datetime | None
    finish_time: datetime | None
    duration_seconds: float | None
    result: str | None
    retry_count: int = 0
    failure_log_excerpt: str | None = None
    log_id: int | None = None
    record_id: str | None = None
    parent_id: str | None = None


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

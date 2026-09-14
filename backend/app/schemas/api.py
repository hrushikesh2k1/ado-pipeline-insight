from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class PipelineOption(BaseModel):
    organization_name: str | None = None
    project_name: str | None = None
    pipeline_id: int
    pipeline_name: str

class OptionsResponse(BaseModel):
    organizations: list[str]
    projects: list[str]
    pipelines: list[PipelineOption]

class SummaryResponse(BaseModel):
    pipeline_id: int | None
    window_days: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate_pct: float
    failure_rate_pct: float
    average_duration_seconds: float | None
    p90_duration_seconds: float | None
    average_queue_seconds: float | None
    stages: list[dict[str, Any]]

class Recommendation(BaseModel):
    id: int | None = None
    pipeline_id: int
    category: str
    severity: str
    stage_name: str
    task_name: str | None = None
    recommendation: str
    evidence: str
    generated_at: datetime | None = None

class AnalyzeRequest(BaseModel):
    months: int = Field(default=3, ge=1, le=24)

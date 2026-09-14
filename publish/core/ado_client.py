from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

import requests

from core.models import TimelineMetric


class AzureDevOpsClient:
    """Small REST client that returns normalized Azure DevOps build data."""

    api_version = "7.1"

    def __init__(self, organization: str, pat: str, session: requests.Session | None = None):
        self.organization = organization
        self.session = session or requests.Session()
        token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
        self.session.headers.update({"Authorization": f"Basic {token}"})

    def get_build(self, project: str, build_id: int) -> dict[str, Any]:
        return self._get(project, f"_apis/build/builds/{build_id}")

    def list_projects(self) -> list[dict[str, Any]]:
        response = self.session.get(
            f"https://dev.azure.com/{self.organization}/_apis/projects",
            params={"api-version": self.api_version, "$top": 200},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("value", [])

    def list_pipelines(self, project: str) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, "_apis/pipelines"),
            params={"api-version": self.api_version, "$top": 200},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("value", [])


    def list_builds(self, project: str, pipeline_id: int | None = None, min_time: datetime | None = None, top: int = 200) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"api-version": self.api_version, "$top": top, "queryOrder": "finishTimeDescending"}
        if pipeline_id is not None:
            params["definitions"] = pipeline_id
        if min_time is not None:
            params["minTime"] = min_time.isoformat()
        response = self.session.get(self._url(project, "_apis/build/builds"), params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("value", [])

    def get_timeline(self, project: str, build_id: int) -> dict[str, Any]:
        return self._get(project, f"_apis/build/builds/{build_id}/timeline")

    def get_log_tail(self, project: str, build_id: int, log_id: int) -> str:
        url = self._url(project, f"_apis/build/builds/{build_id}/logs/{log_id}")
        response = self.session.get(url, params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        lines = response.text.splitlines()[-100:]
        return "\n".join(lines)[-4000:]

    def flatten_timeline(self, build: dict[str, Any], timeline: dict[str, Any]) -> list[TimelineMetric]:
        records = timeline.get("records", [])
        by_id = {record.get("id"): record for record in records}
        metrics: list[TimelineMetric] = []
        run_id = int(build["id"])
        pipeline_id = int(build["definition"]["id"])
        pipeline_name = build["definition"]["name"]
        queue_time = _parse_datetime(build.get("queueTime"))
        source_branch = build.get("sourceBranch")
        source_version = build.get("sourceVersion")
        requested_by = (build.get("requestedFor") or {}).get("displayName") if isinstance(build.get("requestedFor"), dict) else build.get("requestedFor")
        run_start_time = _parse_datetime(build.get("startTime"))
        run_finish_time = _parse_datetime(build.get("finishTime"))

        for record in records:
            record_type = record.get("type", "").lower()
            level = {"stage": "stage", "phase": "job", "job": "job", "task": "task"}.get(record_type)
            if not level:
                continue
            stage, job = _parent_names(record, by_id)
            if level == "stage":
                stage, job = record.get("name"), None
            elif level == "job":
                job = record.get("name")
            metrics.append(
                TimelineMetric(
                    run_id=run_id,
                    pipeline_id=pipeline_id,
                    pipeline_name=pipeline_name,
                    level=level,
                    stage_name=stage,
                    job_name=job,
                    task_name=record.get("name") if level == "task" else None,
                    agent_name=record.get("workerName"),
                    queue_time=queue_time,
                    source_branch=source_branch,
                    source_version=source_version,
                    requested_by=requested_by,
                    start_time=_parse_datetime(record.get("startTime")),
                    finish_time=_parse_datetime(record.get("finishTime")),
                    duration_seconds=_record_duration_seconds(record),
                    result=record.get("result"),
                    retry_count=_retry_count(record),
                    is_degraded=False,
                    data_quality="complete",
                    log_id=(record.get("log") or {}).get("id"),
                    record_id=record.get("id"),
                    parent_id=record.get("parentId"),
                    run_start_time=run_start_time,
                    run_finish_time=run_finish_time,
                )
            )
        return metrics

    def _get(self, project: str, path: str) -> dict[str, Any]:
        response = self.session.get(self._url(project, path), params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        return response.json()

    def _url(self, project: str, path: str) -> str:
        return f"https://dev.azure.com/{self.organization}/{project}/{path}"


def _parent_names(record: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    names: list[tuple[str, str]] = []
    current = record
    while current.get("parentId") and current.get("parentId") in by_id:
        current = by_id[current["parentId"]]
        names.append((current.get("type", "").lower(), current.get("name", "")))
    stage = next((name for record_type, name in names if record_type == "stage"), None)
    job = next((name for record_type, name in names if record_type in {"phase", "job"}), None)
    return stage, job


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

def _record_duration_seconds(record: dict[str, Any]) -> float | None:
    """Prefer timeline timestamps over optional duration fields."""
    start = _parse_datetime(record.get("startTime"))
    finish = _parse_datetime(record.get("finishTime"))
    if start and finish and finish >= start:
        return (finish - start).total_seconds()
    for key in ("durationInMilliseconds", "duration"):
        value = record.get(key)
        if value is not None:
            try:
                return float(value) / 1000.0
            except (TypeError, ValueError):
                return None
    return None


def _retry_count(record: dict[str, Any]) -> int:
    attempt = record.get("attempt")
    if attempt is not None:
        try:
            return max(int(attempt) - 1, 0)
        except (TypeError, ValueError):
            pass
    previous_attempts = record.get("previousAttempts")
    if isinstance(previous_attempts, list):
        return len(previous_attempts)
    return 0

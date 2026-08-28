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
                    start_time=_parse_datetime(record.get("startTime")),
                    finish_time=_parse_datetime(record.get("finishTime")),
                    duration_seconds=record.get("duration") / 1000 if record.get("duration") is not None else None,
                    result=record.get("result"),
                    retry_count=int(record.get("attempt", 1)) - 1,
                    log_id=record.get("log", {}).get("id"),
                    record_id=record.get("id"),
                    parent_id=record.get("parentId"),
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
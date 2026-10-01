from __future__ import annotations

import base64
from datetime import datetime
from typing import Any
from urllib.parse import quote

import logging
import requests

from core.models import TimelineMetric
from core.validation import validate_organization


class AzureDevOpsClient:
    """Small REST client that returns normalized Azure DevOps build data."""

    api_version = "7.1"

    def __init__(self, organization: str, pat: str, session: requests.Session | None = None):
        self.organization = validate_organization(organization)
        self.session = session or requests.Session()
        token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
        self.session.headers.update({"Authorization": f"Basic {token}"})

    def get_build(self, project: str, build_id: int) -> dict[str, Any]:
        return self._get(project, f"_apis/build/builds/{build_id}")

    def list_projects(self) -> list[dict[str, Any]]:
        response = self.session.get(
            f"https://dev.azure.com/{quote(self.organization, safe='')}/_apis/projects",
            params={"api-version": self.api_version, "$top": 200},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def list_pipelines(self, project: str) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, "_apis/pipelines"),
            params={"api-version": self.api_version, "$top": 200},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def list_repositories(self, project: str) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, "_apis/git/repositories"),
            params={"api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def list_pull_requests(
        self, project: str, repository_id: str, status: str = "active", top: int = 100
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/pullrequests"),
            params={"searchCriteria.status": status, "$top": top, "api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def get_pull_request(
        self, project: str, repository_id: str, pull_request_id: int
    ) -> dict[str, Any]:
        response = self.session.get(
            self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/pullrequests/{pull_request_id}"),
            params={"api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response)

    def get_pull_request_commits(
        self, project: str, repository_id: str, pull_request_id: int, top: int = 50
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/pullrequests/{pull_request_id}/commits"),
            params={"$top": top, "api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def get_pull_request_iterations(
        self, project: str, repository_id: str, pull_request_id: int
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/pullrequests/{pull_request_id}/iterations"),
            params={"api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def get_pull_request_iteration_changes(
        self, project: str, repository_id: str, pull_request_id: int, iteration_id: int, top: int = 100
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/pullrequests/{pull_request_id}/iterations/{iteration_id}/changes"),
            params={"$top": top, "api-version": self.api_version},
            timeout=30,
        )
        response.raise_for_status()
        return self._json_response(response).get("changeEntries", [])

    def get_blob_content(self, project: str, repository_id: str, object_id: str) -> str | None:
        """Fetch the text content of a Git blob by its object ID."""
        try:
            response = self.session.get(
                self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/blobs/{object_id}"),
                params={"api-version": self.api_version},
                headers={"Accept": "text/plain"},
                timeout=20,
            )
            if response.status_code == 200:
                return response.text
        except Exception as e:
            logging.debug("Could not fetch blob %s: %s", object_id, e)
        return None

    def get_item_content(
        self, project: str, repository_id: str, path: str, version: str | None = None
    ) -> str | None:
        """Fetch the text content of an item/file in a Git repo."""
        try:
            params = {"api-version": self.api_version, "includeContent": "true"}
            if version:
                params["versionDescriptor.version"] = version
                params["versionDescriptor.versionType"] = "commit" if len(version) == 40 else "branch"
            response = self.session.get(
                self._url(project, f"_apis/git/repositories/{quote(repository_id, safe='')}/items"),
                params=params,
                timeout=20,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("content")
        except Exception as e:
            logging.debug("Could not fetch item %s: %s", path, e)
        return None

    def list_teams(self, project: str, top: int = 100) -> list[dict[str, Any]]:
        """List all teams within a project."""
        url = f"https://dev.azure.com/{quote(self.organization, safe='')}/_apis/projects/{quote(project, safe='')}/teams"
        try:
            response = self.session.get(
                url,
                params={"$top": top, "api-version": self.api_version},
                timeout=30,
            )
            response.raise_for_status()
            return self._json_response(response).get("value", [])
        except Exception:
            # Fallback to alternate route
            url_alt = self._url(project, "_apis/teams")
            response = self.session.get(
                url_alt,
                params={"$top": top, "api-version": self.api_version},
                timeout=30,
            )
            response.raise_for_status()
            return self._json_response(response).get("value", [])

    def list_team_iterations(
        self, project: str, team: str, timeframe: str | None = None
    ) -> list[dict[str, Any]]:
        """List all iterations (sprints) assigned to a team."""
        url = f"https://dev.azure.com/{quote(self.organization, safe='')}/{quote(project, safe='')}/{quote(team, safe='')}/_apis/work/teamsettings/iterations"
        params: dict[str, Any] = {"api-version": self.api_version}
        if timeframe:
            params["$timeframe"] = timeframe
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return self._json_response(response).get("value", [])

    def get_iteration_work_items(
        self, project: str, team: str, iteration_id: str
    ) -> list[dict[str, Any]]:
        """Get work item relations for a team sprint iteration."""
        url = f"https://dev.azure.com/{quote(self.organization, safe='')}/{quote(project, safe='')}/{quote(team, safe='')}/_apis/work/teamsettings/iterations/{quote(iteration_id, safe='')}/workitems"
        response = self.session.get(url, params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        data = self._json_response(response)
        if "workItemRelations" in data:
            return data["workItemRelations"]
        if "workItems" in data:
            return data["workItems"]
        if "value" in data:
            return data["value"]
        return []

    def query_wiql(self, project: str, wiql_query: str) -> list[int]:
        """Execute a WIQL query and return a list of matching work item IDs."""
        url = self._url(project, "_apis/wit/wiql")
        payload = {"query": wiql_query}
        response = self.session.post(url, json=payload, params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        data = self._json_response(response)

        item_ids: list[int] = []
        if "workItems" in data and isinstance(data["workItems"], list):
            for item in data["workItems"]:
                if isinstance(item, dict) and "id" in item:
                    try:
                        item_ids.append(int(item["id"]))
                    except (ValueError, TypeError):
                        pass
        elif "workItemRelations" in data and isinstance(data["workItemRelations"], list):
            for rel in data["workItemRelations"]:
                if isinstance(rel, dict):
                    target = rel.get("target")
                    if isinstance(target, dict) and "id" in target:
                        try:
                            item_ids.append(int(target["id"]))
                        except (ValueError, TypeError):
                            pass
                    source = rel.get("source")
                    if isinstance(source, dict) and "id" in source:
                        try:
                            item_ids.append(int(source["id"]))
                        except (ValueError, TypeError):
                            pass
        return list(dict.fromkeys(item_ids))

    def get_team_iteration(
        self, project: str, team: str, iteration_id: str
    ) -> dict[str, Any]:
        """Fetch details of a single team iteration by ID."""
        url = f"https://dev.azure.com/{quote(self.organization, safe='')}/{quote(project, safe='')}/{quote(team, safe='')}/_apis/work/teamsettings/iterations/{quote(iteration_id, safe='')}"
        response = self.session.get(url, params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        return self._json_response(response)

    def get_work_items_batch(
        self, project: str, ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Batch fetch work items by their IDs."""
        if not ids:
            return []
        url = self._url(project, "_apis/wit/workitemsbatch")
        default_fields = [
            "System.Id",
            "System.Title",
            "System.State",
            "System.WorkItemType",
            "System.AssignedTo",
            "System.ChangedDate",
            "System.CreatedDate",
            "System.IterationPath",
            "System.AreaPath",
            "System.Parent",
            "Microsoft.VSTS.Scheduling.RemainingWork",
            "Microsoft.VSTS.Scheduling.CompletedWork",
            "Microsoft.VSTS.Scheduling.OriginalEstimate",
            "Microsoft.VSTS.Common.StateChangeDate",
            "System.BoardColumn",
            "System.Description",
            "Microsoft.VSTS.Common.AcceptanceCriteria",
            "Microsoft.VSTS.TCM.ReproSteps",
            "System.Tags",
        ]
        results: list[dict[str, Any]] = []
        for i in range(0, len(ids), 200):
            chunk = ids[i : i + 200]
            payload = {
                "ids": chunk,
                "fields": fields or default_fields,
            }
            response = self.session.post(url, json=payload, params={"api-version": self.api_version}, timeout=30)
            response.raise_for_status()
            results.extend(self._json_response(response).get("value", []))
        return results

    def list_builds(
        self,
        project: str,
        pipeline_id: int | None = None,
        min_time: datetime | None = None,
        top: int = 200,
        max_builds: int = 5000,
    ) -> list[dict[str, Any]]:
        """Return completed or in-progress builds across all ADO result pages.

        ``top`` is the page size. Azure DevOps returns a continuation token
        when more builds are available. The caller still gets one combined
        list, bounded by ``max_builds`` as a safety limit.
        """
        page_size = max(1, min(int(top), 200))
        max_builds = max(page_size, int(max_builds))
        params: dict[str, Any] = {
            "api-version": self.api_version,
            "$top": page_size,
            "queryOrder": "finishTimeDescending",
        }
        if pipeline_id is not None:
            params["definitions"] = pipeline_id
        if min_time is not None:
            params["minTime"] = min_time.isoformat()

        builds: list[dict[str, Any]] = []
        continuation_token: str | None = None

        while len(builds) < max_builds:
            if continuation_token:
                params["continuationToken"] = continuation_token
            else:
                params.pop("continuationToken", None)

            response = self.session.get(
                self._url(project, "_apis/build/builds"),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            payload = self._json_response(response)
            page = payload.get("value", [])
            if not page:
                break

            builds.extend(page)
            continuation_token = (
                response.headers.get("x-ms-continuationtoken")
                or response.headers.get("X-MS-ContinuationToken")
            )
            if not continuation_token or len(page) < page_size:
                break

        return builds[:max_builds]

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
        run_result = build.get("result")
        requested_by = (build.get("requestedFor") or {}).get("displayName") if isinstance(build.get("requestedFor"), dict) else build.get("requestedFor")
        run_start_time = _parse_datetime(build.get("startTime"))
        run_finish_time = _parse_datetime(build.get("finishTime"))
        build_number = build.get("buildNumber")

        for record in records:
            record_type = str(record.get("type", "")).strip().lower()

            # Azure DevOps emits several timeline record types. For pipeline
            # analytics we only persist the real execution hierarchy:
            # Stage -> Job/Phase -> Task.
            #
            # Some builds contain Task records that are internal timeline
            # detail records (for example a Task named "Job") and whose
            # parent is not a Job/Phase. Those are not pipeline tasks and
            # must not become task rows with NULL stage/job names.
            level = {
                "stage": "stage",
                "phase": "job",
                "job": "job",
                "task": "task",
            }.get(record_type)
            if not level:
                continue

            stage, job = _parent_names(record, by_id)

            if level == "stage":
                stage, job = record.get("name"), None
            elif level == "job":
                job = record.get("name")
            elif job is None:
                # A task without a Job/Phase ancestor is an internal/detail
                # timeline record, not a task in the pipeline hierarchy.
                continue

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
                    run_result=run_result,
                    retry_count=_retry_count(record),
                    is_degraded=False,
                    data_quality="complete",
                    log_id=(record.get("log") or {}).get("id"),
                    record_id=record.get("id"),
                    parent_id=record.get("parentId"),
                    build_number=build_number,
                    run_start_time=run_start_time,
                    run_finish_time=run_finish_time,
                )
            )
        return metrics

    def _get(self, project: str, path: str) -> dict[str, Any]:
        response = self.session.get(self._url(project, path), params={"api-version": self.api_version}, timeout=30)
        response.raise_for_status()
        return self._json_response(response)

    @staticmethod
    def _json_response(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            logging.error(
                "ADO_NON_JSON_RESPONSE status=%s content_type=%s url=%s body=%r",
                response.status_code,
                response.headers.get("Content-Type"),
                response.url,
                response.text[:1000],
            )
            raise requests.HTTPError(
                "Azure DevOps returned a non-JSON response.",
                response=response,
            ) from exc

        if not isinstance(payload, dict):
            raise requests.HTTPError(
                "Azure DevOps returned an unexpected JSON response.",
                response=response,
            )
        return payload

    def _url(self, project: str, path: str) -> str:
        return f"https://dev.azure.com/{quote(self.organization, safe='')}/{quote(project, safe='')}/{path}"


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

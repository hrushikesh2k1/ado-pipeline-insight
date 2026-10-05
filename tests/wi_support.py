"""Fakes shared by the work item insights tests: an Azure DevOps client, an AI client and a work item builder."""
from __future__ import annotations

import json
import re
import threading
from types import SimpleNamespace
from typing import Any

import requests

AREAS = [
    {"name": "VPN issues", "description": "VPN tunnels and gateways"},
    {"name": "Login and authentication", "description": "Sign-in problems"},
    {"name": "AKS container restarts", "description": "Pods restarting"},
]

STATES = {
    "Bug": {"New": "Proposed", "Active": "InProgress", "Resolved": "Resolved", "Closed": "Completed", "Removed": "Removed"},
    "User Story": {"New": "Proposed", "Active": "InProgress", "Resolved": "Resolved", "Closed": "Completed", "Removed": "Removed"},
    "Task": {"To Do": "Proposed", "In Progress": "InProgress", "Done": "Completed", "Removed": "Removed"},
}


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


def raw_item(item_id: int, *, type: str = "Bug", state: str = "New", title: str = "Something", description: str = "",
             assigned: Any = "Asha Rao", created: str = "2026-09-10T08:00:00Z", changed: str | None = None,
             closed: str | None = None, state_change: str | None = None, area: str = "Proj\\Monitoring",
             iteration: str = "Proj\\Sprint 5", tags: str = "monitoring", rev: int = 1, repro: str = "") -> dict[str, Any]:
    fields: dict[str, Any] = {
        "System.Id": item_id, "System.WorkItemType": type, "System.Title": title, "System.State": state,
        "System.AssignedTo": assigned, "System.CreatedDate": created, "System.ChangedDate": changed or closed or created,
        "System.AreaPath": area, "System.IterationPath": iteration, "System.Tags": tags, "System.Description": description,
    }
    if closed:
        fields["Microsoft.VSTS.Common.ClosedDate"] = closed
    if state_change:
        fields["Microsoft.VSTS.Common.StateChangeDate"] = state_change
    if repro:
        fields["Microsoft.VSTS.TCM.ReproSteps"] = repro
    return {"id": item_id, "rev": rev, "fields": fields}


class FakeAdo:
    """Serves work items the way the real client's methods do. The query is only recorded: exact filtering happens in code."""

    def __init__(self, raws: list[dict[str, Any]], *, team_fields: dict[str, Any] | None = None, reject_optional: bool = False,
                 wiql_error: Any = None, states_fail: bool = False):
        self.raws = {r["id"]: r for r in raws}
        self.team_fields = team_fields if team_fields is not None else {"values": [{"value": "Proj\\Monitoring", "includeChildren": True}]}
        self.reject_optional = reject_optional
        self.wiql_error = wiql_error
        self.states_fail = states_fail
        self.queries: list[tuple[str, int | None]] = []
        self.batches: list[tuple[list[int], list[str] | None]] = []

    def list_work_item_types(self, project: str) -> list[dict[str, Any]]:
        if self.states_fail:
            raise http_error(500)
        return [{"name": name} for name in STATES]

    def list_work_item_type_states(self, project: str, type_name: str) -> list[dict[str, Any]]:
        return [{"name": n, "category": c} for n, c in STATES[type_name].items()]

    def get_team_field_values(self, project: str, team: str) -> dict[str, Any]:
        if isinstance(self.team_fields, Exception):
            raise self.team_fields
        return self.team_fields

    def query_wiql(self, project: str, query: str, top: int | None = None) -> list[int]:
        self.queries.append((query, top))
        if callable(self.wiql_error):
            error = self.wiql_error(top)
            if error:
                raise error
        after = re.search(r"\[System\.Id\] > (\d+)", query)
        floor = int(after.group(1)) if after else 0
        ids = sorted(i for i in self.raws if i > floor)
        return ids[:top] if top else ids

    def get_work_items_batch(self, project: str, ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        self.batches.append((list(ids), fields))
        if self.reject_optional and fields and any(f.startswith("Microsoft.VSTS") for f in fields):
            raise http_error(400)
        return [self.raws[i] for i in ids if i in self.raws]


def keyword_area(title: str) -> str:
    lowered = title.lower()
    if "vpn" in lowered:
        return "VPN issues"
    if "login" in lowered or "sign in" in lowered:
        return "Login and authentication"
    if "aks" in lowered or "pod" in lowered:
        return "AKS container restarts"
    return "Other"


def smart_responder(system: str, user: str) -> str:
    """What a sensible model answers: areas from the discover prompt, an area per item by keyword, alert_work by the word 'alert'."""
    if system.startswith("You are given the titles"):
        return json.dumps({"areas": AREAS})
    items = json.loads(user)["items"]
    if "say whether each one asks for a new monitoring alert" in system:
        return json.dumps({"items": [{"id": i["id"], "alert_work": "new alert" in i["title"].lower()} for i in items]})
    with_alert = '"alert_work"' in system
    rows = []
    for item in items:
        row: dict[str, Any] = {"id": item["id"], "area": keyword_area(item["title"])}
        if with_alert:
            row["alert_work"] = "new alert" in item["title"].lower()
        rows.append(row)
    return json.dumps({"items": rows})


class FakeAI:
    """Looks like PipelineRecommendationClient: .deployment and .client.chat.completions.create(...)."""

    def __init__(self, responder=smart_responder):
        self.deployment = "fake-deployment"
        self.responder = responder
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    def _create(self, model: str, messages: list[dict[str, str]], temperature: float = 0, response_format: Any = None) -> Any:
        system, user = messages[0]["content"], messages[1]["content"]
        with self._lock:
            self.calls.append((system, user))
        text = self.responder(system, user)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def calls_of(self, kind: str) -> list[tuple[str, str]]:
        marks = {
            "discover": lambda s: s.startswith("You are given the titles"),
            "alert_only": lambda s: "say whether each one asks for a new monitoring alert" in s,
            "assign": lambda s: s.startswith("You place Azure DevOps work items"),
        }
        return [c for c in self.calls if marks[kind](c[0])]

    def assigned_ids(self) -> list[int]:
        return sorted(i["id"] for _s, u in self.calls_of("assign") for i in json.loads(u)["items"])

"""A pretend Azure DevOps for the sprint planning tests. Every name, area and title here is made up.

`query_wiql` really reads the WIQL text it is sent (iteration, state, type, assignee and area clauses), so a wrong query fails a test.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import requests

PROJECT = "Demo"
TEAM = "Alpha"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

SPRINTS = [
    {"id": "s1", "name": "Sprint 1", "path": "Demo\\Sprint 1", "attributes": {"startDate": "2026-09-07T00:00:00Z", "finishDate": "2026-09-18T00:00:00Z", "timeFrame": "past"}},
    {"id": "s2", "name": "Sprint 2", "path": "Demo\\Sprint 2", "attributes": {"startDate": "2026-09-21T00:00:00Z", "finishDate": "2026-10-02T00:00:00Z", "timeFrame": "current"}},
    {"id": "s3", "name": "Sprint 3", "path": "Demo\\Sprint 3", "attributes": {"startDate": "2026-10-05T00:00:00Z", "finishDate": "2026-10-16T00:00:00Z", "timeFrame": "future"}},
    {"id": "s4", "name": "Sprint 4", "path": "Demo\\Sprint 4", "attributes": {"startDate": "2026-10-19T00:00:00Z", "finishDate": "2026-10-30T00:00:00Z", "timeFrame": "future"}},
]
STATES = {
    "User Story": {"New": "Proposed", "Active": "InProgress", "Resolved": "Resolved", "Closed": "Completed", "Removed": "Removed"},
    "Bug": {"New": "Proposed", "Active": "InProgress", "Resolved": "Resolved", "Closed": "Completed"},
    "Task": {"To Do": "Proposed", "In Progress": "InProgress", "Done": "Completed"},
}
AREA_TREE = {"name": "Demo", "children": [
    {"name": "Alpha", "children": [{"name": "Backend", "children": [{"name": "Api"}]}, {"name": "Frontend"}, {"name": "Ops"}]},
    {"name": "Beta", "children": [{"name": "Reports"}]},
]}
PEOPLE = {
    "ava": ("Ava Stone", "ava@example.test"), "ben": ("Ben Ortiz", "ben@example.test"), "cara": ("Cara Lin", "cara@example.test"), "dan": ("Dan Reyes", "dan@example.test"),
}


def ago(days: float = 0, hours: float = 0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def person(key: str | None) -> dict[str, str] | None:
    if key is None:
        return None
    name, unique = PEOPLE[key]
    return {"displayName": name, "uniqueName": unique}


def story(item_id: int, title: str = "", *, state: str = "New", area: str = "Demo\\Alpha\\Backend", iteration: str = "Demo", who: str | None = None, tags: str = "",
          since: str | None = None, rank: float | None = None, kind: str = "User Story", points: float | None = None, blocked: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "System.Id": item_id, "System.WorkItemType": kind, "System.Title": title or f"Story {item_id}", "System.State": state, "System.AreaPath": area, "System.IterationPath": iteration,
        "System.Tags": tags, "System.ChangedDate": since or ago(1), "Microsoft.VSTS.Common.StateChangeDate": since or ago(1),
        "Microsoft.VSTS.Common.BacklogPriority": rank if rank is not None else float(item_id),
    }
    if who:
        fields["System.AssignedTo"] = person(who)
    if points is not None:
        fields["Microsoft.VSTS.Scheduling.StoryPoints"] = points
    if blocked is not None:
        fields["Microsoft.VSTS.CMMI.Blocked"] = blocked
    return {"id": item_id, "rev": 1, "fields": fields}


def comment(text: str, author: str = "Ava Stone", when: str = "2026-10-01T09:00:00Z") -> dict[str, Any]:
    return {"text": text, "createdBy": {"displayName": author}, "createdDate": when}


def http_error(code: int) -> requests.HTTPError:
    return requests.HTTPError(f"HTTP {code}", response=SimpleNamespace(status_code=code))


def _values(text: str) -> list[str]:
    return [m.replace("''", "'") for m in re.findall(r"'((?:[^']|'')*)'", text)]


class FakeBoard:
    """What the planning code calls. `items` are raw work items (see `story`)."""

    def __init__(self, items: list[dict[str, Any]], *, sprints: list[dict[str, Any]] | None = None, comments: dict[int, Any] | None = None,
                 members: list[dict[str, Any]] | None = None, team_areas: Any = "default", reject_fields: tuple[str, ...] = (), no_backlog_order: bool = False,
                 no_stack_rank: bool = False, fail: tuple[str, ...] = (), types: list[str] | None = None, ignore_areas: bool = False):
        self.items = {i["id"]: i for i in items}
        self.sprints = sprints if sprints is not None else SPRINTS
        self.comments = comments or {}
        self.members = members if members is not None else [{"isTeamAdmin": False, "identity": {"id": k, "displayName": n, "uniqueName": u}} for k, (n, u) in PEOPLE.items()]
        self.team_areas = {"values": [{"value": "Demo\\Alpha", "includeChildren": True}], "defaultValue": "Demo\\Alpha"} if team_areas == "default" else team_areas
        self.reject_fields, self.no_backlog_order, self.no_stack_rank, self.fail = reject_fields, no_backlog_order, no_stack_rank, fail
        self.ignore_areas = ignore_areas  # a server that answers with more than the area clause allows
        self.types = types if types is not None else list(STATES)
        self.queries: list[str] = []
        self.field_requests: list[list[str]] = []
        self.comment_reads: list[int] = []

    # --- the team
    def list_team_iterations(self, project, team, timeframe=None):
        self._maybe_fail("iterations")
        return self.sprints

    def get_team_field_values(self, project, team):
        self._maybe_fail("team_areas")
        return self.team_areas

    def list_team_members(self, project, team, top=200):
        self._maybe_fail("members")
        return self.members

    def get_area_tree(self, project, depth=6):
        self._maybe_fail("area_tree")
        return AREA_TREE

    def list_work_item_types(self, project):
        self._maybe_fail("types")
        return [{"name": n} for n in self.types]

    def list_work_item_type_states(self, project, type_name):
        return [{"name": s, "category": c} for s, c in STATES.get(type_name, {}).items()]

    def _maybe_fail(self, what: str):
        if what in self.fail:
            raise http_error(500)

    # --- work items
    def query_wiql(self, project, wiql, top=None):
        self.queries.append(wiql)
        if self.no_backlog_order and "BacklogPriority" in wiql:
            raise http_error(400)
        if self.no_stack_rank and "StackRank" in wiql:
            raise http_error(400)
        where = wiql.split(" WHERE ", 1)[1].split(" ORDER BY ", 1)[0]
        iterations = _values(re.search(r"\[System\.IterationPath\] IN \(([^)]*)\)", where).group(1)) if "[System.IterationPath] IN" in where else None
        kinds = _values(re.search(r"\[System\.WorkItemType\] IN \(([^)]*)\)", where).group(1))
        states_in = _values(re.search(r"\[System\.State\] IN \(([^)]*)\)", where).group(1)) if "[System.State] IN" in where else None
        states_not = _values(re.search(r"\[System\.State\] NOT IN \(([^)]*)\)", where).group(1)) if "[System.State] NOT IN" in where else None
        areas = [(m.group(1), m.group(2).replace("''", "'")) for m in re.finditer(r"\[System\.AreaPath\] (UNDER|=) '((?:[^']|'')*)'", where)]
        found = []
        for item in self.items.values():
            f = item["fields"]
            if f["System.WorkItemType"] not in kinds:
                continue
            if iterations is not None and f["System.IterationPath"] not in iterations:
                continue
            if states_in is not None and f["System.State"] not in states_in:
                continue
            if states_not is not None and f["System.State"] in states_not:
                continue
            if "[System.AssignedTo] = ''" in where and f.get("System.AssignedTo"):
                continue
            if areas and not self.ignore_areas and not any(f["System.AreaPath"] == path or (op == "UNDER" and f["System.AreaPath"].startswith(path + "\\")) for op, path in areas):
                continue
            found.append(item)
        found.sort(key=lambda i: (i["fields"].get("Microsoft.VSTS.Common.BacklogPriority", 0), i["id"]))
        ids = [i["id"] for i in found]
        return ids[:top] if top else ids

    def get_work_items_batch(self, project, ids, fields=None):
        self.field_requests.append(list(fields or []))
        if fields and any(f in self.reject_fields for f in fields):
            raise http_error(400)
        return [{**self.items[i], "fields": {k: v for k, v in self.items[i]["fields"].items() if not fields or k in fields}} for i in ids if i in self.items]

    def get_work_item_comments(self, project, work_item_id, top=3):
        self.comment_reads.append(work_item_id)
        value = self.comments.get(work_item_id, [])
        if isinstance(value, Exception):
            raise value
        return value[:top]

"""Reads the work items of a scope (a team and/or a tag) from Azure DevOps and turns them into plain records.

The scope is everything that is still open, whatever its age, plus everything closed in the last few months.
Nothing here is specific to one team's process: which states mean "closed" comes from Azure DevOps itself (the state
categories of each work item type), and the team and tag filters are both optional.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from app.services.board_service import is_in_team_areas, parse_team_area_scopes, strip_html_tags

logger = logging.getLogger(__name__)

DEFAULT_MONTHS = 6
ID_PAGE = 5_000
MIN_ID_PAGE = 250
BATCH = 200
MAX_ID_PAGES = 400
DESCRIPTION_CHARS = 1_500
UNASSIGNED = "Unassigned"
NO_SPRINT = "No sprint"

# Present in every process Azure DevOps ships.
FIELDS_SAFE = [
    "System.Id", "System.WorkItemType", "System.Title", "System.State", "System.AssignedTo", "System.CreatedDate",
    "System.ChangedDate", "System.AreaPath", "System.IterationPath", "System.Tags", "System.Description",
]
# Not guaranteed in a customised process. If Azure DevOps rejects them, the safe list is used instead.
FIELDS_FULL = FIELDS_SAFE + [
    "Microsoft.VSTS.Common.ClosedDate", "Microsoft.VSTS.Common.StateChangeDate", "Microsoft.VSTS.TCM.ReproSteps",
]

# Used only for a state Azure DevOps did not describe (the call failed or the type was not listed).
_FALLBACK_CATEGORY = {
    "closed": "completed", "done": "completed", "completed": "completed", "removed": "removed", "resolved": "resolved",
    "new": "proposed", "to do": "proposed", "proposed": "proposed",
}
_FALLBACK_FINISHED = ["Closed", "Done", "Completed", "Removed"]

Progress = Callable[[str, int, int], None]


def _noop(_phase: str, _done: int, _total: int) -> None:
    return None


class StateMap:
    """What each state means for each work item type, as Azure DevOps defines it.

    Categories: proposed (not started), inprogress, resolved, completed (closed) and removed.
    """

    def __init__(self, by_type: dict[str, dict[str, str]] | None = None):
        self._by_type: dict[str, dict[str, str]] = {}
        self._spelling: dict[str, str] = {}
        for type_name, states in (by_type or {}).items():
            table = self._by_type.setdefault(type_name.lower(), {})
            for state, category in states.items():
                table[state.lower()] = category.lower()
                if category.lower() in ("completed", "removed"):
                    self._spelling.setdefault(state.lower(), state)

    def category(self, work_item_type: str, state: str) -> str:
        key = (state or "").strip().lower()
        known = self._by_type.get((work_item_type or "").strip().lower(), {}).get(key)
        if known:
            return known
        return _FALLBACK_CATEGORY.get(key, "inprogress")

    def finished_state_names(self) -> list[str]:
        """Every state, of any type, that means closed or removed; they are not part of the open backlog."""
        return sorted(self._spelling.values()) or list(_FALLBACK_FINISHED)


def load_state_map(client: Any, project: str) -> StateMap:
    by_type: dict[str, dict[str, str]] = {}
    try:
        types = client.list_work_item_types(project)
    except Exception as exc:
        logger.warning("Could not list work item types, using the common state names: %s", type(exc).__name__)
        return StateMap()
    for item in types:
        name = str(item.get("name") or "")
        if not name or item.get("isDisabled"):
            continue
        try:
            states = client.list_work_item_type_states(project, name)
        except Exception as exc:
            logger.info("Could not read the states of '%s': %s", name, type(exc).__name__)
            continue
        table = {str(s.get("name")): str(s.get("category") or "") for s in states if s.get("name")}
        if table:
            by_type[name] = table
    return StateMap(by_type)


def window_start(now: datetime, months: int) -> datetime:
    """First day, 00:00 UTC, of the month `months` months before the current one."""
    year, month = now.year, now.month - months
    while month < 1:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def parse_when(value: Any) -> datetime | None:
    """Azure DevOps timestamps carry up to 7 fractional digits; Python reads at most 6."""
    if not value:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).strip().replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def team_area_paths(field_values: dict[str, Any] | None) -> list[tuple[str, bool]]:
    """The team's area paths with their original spelling, as (path, includes_children)."""
    if not isinstance(field_values, dict):
        return []
    paths = [
        (str(v["value"]).strip(), bool(v.get("includeChildren")))
        for v in field_values.get("values") or []
        if isinstance(v, dict) and v.get("value")
    ]
    if not paths and field_values.get("defaultValue"):
        paths = [(str(field_values["defaultValue"]).strip(), False)]
    return paths


def _q(text: str) -> str:
    return text.replace("'", "''")


def build_wiql(
    project: str,
    *,
    areas: list[tuple[str, bool]],
    tag: str,
    months: int,
    finished_states: list[str],
    after_id: int = 0,
) -> str:
    """Ids of what is open now, or was changed within the window (a closed item can only have closed in it if it changed)."""
    clauses = [f"[System.TeamProject] = '{_q(project)}'", "[System.WorkItemType] <> ''"]
    if areas:
        parts = [f"[System.AreaPath] {'UNDER' if children else '='} '{_q(path)}'" for path, children in areas]
        clauses.append("(" + " OR ".join(parts) + ")")
    if tag:
        clauses.append(f"[System.Tags] CONTAINS '{_q(tag)}'")
    states = ", ".join(f"'{_q(s)}'" for s in finished_states)
    clauses.append(f"([System.ChangedDate] >= @StartOfMonth - {int(months)} OR [System.State] NOT IN ({states}))")
    if after_id:
        clauses.append(f"[System.Id] > {int(after_id)}")
    return "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses) + " ORDER BY [System.Id]"


def list_item_ids(client: Any, project: str, *, areas: list[tuple[str, bool]], tag: str, months: int,
                  finished_states: list[str], progress: Progress = _noop) -> list[int]:
    """All matching ids, read in pages by id so that no single answer depends on a server-side size limit."""
    ids: list[int] = []
    last = 0
    page = ID_PAGE
    for _ in range(MAX_ID_PAGES):
        query = build_wiql(project, areas=areas, tag=tag, months=months, finished_states=finished_states, after_id=last)
        try:
            batch = client.query_wiql(project, query, top=page)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (400, 413) and page > MIN_ID_PAGE:
                page = max(MIN_ID_PAGE, page // 2)
                logger.info("Work item query failed (%s); retrying with pages of %d ids", exc, page)
                continue
            raise
        if not batch:
            break
        ids.extend(batch)
        progress("reading", len(ids), 0)
        if len(batch) < page:
            break
        last = max(batch)
    return list(dict.fromkeys(ids))


def fetch_raw_items(client: Any, project: str, ids: list[int], progress: Progress = _noop) -> list[dict[str, Any]]:
    """Work item fields in batches of 200. A customised process may lack some optional fields; then the safe list is used."""
    fields = FIELDS_FULL
    items: list[dict[str, Any]] = []
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        try:
            items.extend(client.get_work_items_batch(project, chunk, fields))
        except requests.HTTPError as exc:
            if fields is FIELDS_SAFE or getattr(exc.response, "status_code", None) != 400:
                raise
            logger.info("Azure DevOps rejected an optional field; reading the common fields only")
            fields = FIELDS_SAFE
            items.extend(client.get_work_items_batch(project, chunk, fields))
        progress("reading", min(start + BATCH, len(ids)), len(ids))
    return items


def _person(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("displayName") or value.get("uniqueName") or "").strip() or UNASSIGNED
    text = str(value or "").split("<")[0].strip()
    return text or UNASSIGNED


def _sprint(iteration_path: Any) -> str:
    """The path below the project root ("2026\\Sprint 5"); two sprints can share a last name."""
    parts = [p for p in str(iteration_path or "").replace("/", "\\").split("\\") if p]
    return "\\".join(parts[1:]) if len(parts) > 1 else NO_SPRINT


def _tags(value: Any) -> list[str]:
    return [t.strip() for t in str(value or "").split(";") if t.strip()]


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def normalize_item(raw: dict[str, Any], states: StateMap) -> dict[str, Any] | None:
    fields = raw.get("fields") or {}
    item_id = raw.get("id") or fields.get("System.Id")
    if not item_id:
        return None
    item_type = str(fields.get("System.WorkItemType") or "")
    state = str(fields.get("System.State") or "")
    category = states.category(item_type, state)
    changed = parse_when(fields.get("System.ChangedDate"))
    closed = None
    if category == "completed":
        closed = (
            parse_when(fields.get("Microsoft.VSTS.Common.ClosedDate"))
            or parse_when(fields.get("Microsoft.VSTS.Common.StateChangeDate"))
            or changed
        )
    text = strip_html_tags(fields.get("System.Description")) or strip_html_tags(fields.get("Microsoft.VSTS.TCM.ReproSteps"))
    return {
        "id": int(item_id),
        "rev": int(raw.get("rev") or 0),
        "type": item_type,
        "title": str(fields.get("System.Title") or "").strip(),
        "state": state,
        "state_category": category,
        "assigned_to": _person(fields.get("System.AssignedTo")),
        "created": _iso(parse_when(fields.get("System.CreatedDate"))),
        "closed": _iso(closed),
        "changed": _iso(changed),
        "sprint": _sprint(fields.get("System.IterationPath")),
        "area_path": str(fields.get("System.AreaPath") or "").strip(),
        "tags": _tags(fields.get("System.Tags")),
        "description": text[:DESCRIPTION_CHARS],
    }


def keep_item(item: dict[str, Any], *, start: datetime, tag: str, team_scopes: list[tuple[str, bool]]) -> bool:
    """The exact scope rules. The query is only a wide first cut; tag matching and the closing date are decided here."""
    if item["state_category"] == "removed":
        return False
    if item["state_category"] == "completed":
        closed = parse_when(item["closed"])
        if closed is None or closed < start:
            return False
    if tag and tag.lower() not in (t.lower() for t in item["tags"]):
        return False
    return is_in_team_areas(item["area_path"], team_scopes)


def collect_scope_items(
    client: Any,
    project: str,
    *,
    team: str = "",
    tag: str = "",
    months: int = DEFAULT_MONTHS,
    now: datetime | None = None,
    progress: Progress = _noop,
) -> list[dict[str, Any]]:
    """The work items of one scope as plain records, newest information from Azure DevOps."""
    now = now or datetime.now(timezone.utc)
    start = window_start(now, months)
    area_paths: list[tuple[str, bool]] = []
    if team:
        try:
            field_values = client.get_team_field_values(project, team)
        except Exception as exc:
            raise ValueError(f"Could not read the area paths of team '{team}': {exc}") from exc
        area_paths = team_area_paths(field_values)
        if not area_paths:
            raise ValueError(f"Team '{team}' has no area paths in Azure DevOps, so its work items cannot be told apart.")
    scopes = parse_team_area_scopes({"values": [{"value": p, "includeChildren": c} for p, c in area_paths]})

    states = load_state_map(client, project)
    progress("reading", 0, 0)
    ids = list_item_ids(client, project, areas=area_paths, tag=tag, months=months,
                        finished_states=states.finished_state_names(), progress=progress)
    raw = fetch_raw_items(client, project, ids, progress)
    items = [n for n in (normalize_item(r, states) for r in raw) if n]
    return [i for i in items if keep_item(i, start=start, tag=tag, team_scopes=scopes)]

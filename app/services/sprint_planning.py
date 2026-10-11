"""Sprint planning: which stories each person takes into the next sprint, and which carried-over stories need a look first.

The plan is shown on screen only; nothing is written to Azure DevOps. The rules (the first ones; more will follow):

1. Every person is planned for the same number of stories (6 by default). The stories a person still has open in the current sprint move
   to the next sprint with that person and count towards the six.
2. A carried-over story that is Blocked, or has been in an active state for more than 10 days, is flagged, and its last 3 comments are read
   so that its situation can be understood.
3. Every person has areas of choice (area paths; several people may share one). The places that are still free are filled with unassigned
   stories whose Area Path is one of the person's areas or under it, in backlog order.

Which states mean "finished", "not started" and "active" comes from Azure DevOps itself (the state categories of each work item type).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

from app.services.board_service import _norm_area, is_in_team_areas, parse_team_area_scopes, safe_float, strip_html_tags
from app.services.work_item_scope import StateMap, load_state_map, parse_when, team_area_paths

logger = logging.getLogger(__name__)

DEFAULT_PER_PERSON = 6
MAX_PER_PERSON = 30
DEFAULT_ACTIVE_DAYS = 10
MAX_ACTIVE_DAYS = 90
MAX_PEOPLE = 40
COMMENTS_SHOWN = 3
COMMENT_CHARS = 700
MAX_BACKLOG = 300  # how far down the backlog the plan reads
MAX_UNPLACED_LISTED = 50
MAX_COMMENT_READS = 60
STORY_TYPES = ("User Story", "Product Backlog Item", "Requirement", "Issue", "Bug")
DEFAULT_TYPES = ("User Story", "Product Backlog Item", "Requirement", "Issue")  # the story type of each process (a process has one of them)
ANY_AREA = "*"
BLOCKED = "blocked"
LONG_ACTIVE = "active_too_long"

BASE_FIELDS = [
    "System.Id", "System.WorkItemType", "System.Title", "System.State", "System.AssignedTo", "System.AreaPath", "System.IterationPath",
    "System.Tags", "System.ChangedDate", "Microsoft.VSTS.Common.StateChangeDate",
]
OPTIONAL_FIELDS = ["Microsoft.VSTS.Common.ActivatedDate", "Microsoft.VSTS.CMMI.Blocked", "Microsoft.VSTS.Scheduling.StoryPoints"]
# a customised process may lack a field; Azure DevOps then answers 400 and the next shorter list is used
FIELD_LISTS = (BASE_FIELDS + OPTIONAL_FIELDS, BASE_FIELDS, [f for f in BASE_FIELDS if f != "Microsoft.VSTS.Common.StateChangeDate"])
ORDERS = ("[Microsoft.VSTS.Common.BacklogPriority] ASC, [System.Id] ASC", "[Microsoft.VSTS.Common.StackRank] ASC, [System.Id] ASC", "[System.Id] ASC")
FALLBACK_PROPOSED = ["New", "Proposed", "To Do", "Approved"]


class PlanningError(Exception):
    """Something the person planning can fix (no next sprint, nobody to plan for, ...)."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------- sprints

def _sprint(raw: dict[str, Any]) -> dict[str, Any]:
    attributes = raw.get("attributes") or {}
    return {"id": str(raw.get("id") or ""), "name": str(raw.get("name") or ""), "path": str(raw.get("path") or ""),
            "start": attributes.get("startDate"), "finish": attributes.get("finishDate"), "time_frame": str(attributes.get("timeFrame") or "").lower()}


def list_sprints(client: Any, project: str, team: str) -> list[dict[str, Any]]:
    """The team's sprints, oldest first (a sprint without dates goes last)."""
    sprints = [_sprint(i) for i in client.list_team_iterations(project, team) if i.get("id") and i.get("path")]
    return sorted(sprints, key=lambda s: (s["start"] is None, s["start"] or ""))


def default_sprints(sprints: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """(the sprint to carry from, the sprint to plan): the current one and the one after it; with no current sprint, the last past one and the first future one."""
    current = next((i for i, s in enumerate(sprints) if s["time_frame"] == "current"), None)
    if current is None:
        past = [i for i, s in enumerate(sprints) if s["time_frame"] == "past"]
        current = past[-1] if past else None
    nxt = None
    if current is not None:
        nxt = next((i for i in range(current + 1, len(sprints)) if sprints[i]["time_frame"] in ("future", "")), None)
    else:
        nxt = next((i for i, s in enumerate(sprints) if s["time_frame"] == "future"), None)
    return (sprints[current]["id"] if current is not None else None, sprints[nxt]["id"] if nxt is not None else None)


# ---------------------------------------------------------------- reading work items

def _q(text: str) -> str:
    return text.replace("'", "''")


def _in(values: list[str]) -> str:
    return ", ".join(f"'{_q(v)}'" for v in values)


def build_wiql(project: str, *, types: list[str], areas: list[tuple[str, bool]] | None = None, order: str, iterations: list[str] | None = None,
               iterations_not: list[str] | None = None,
               states: list[str] | None = None, states_not: list[str] | None = None, unassigned: bool = False,
               tags: list[str] | None = None) -> str:
    """The ids of the stories in a place (sprints), optionally only those in or not in some states, unassigned, and in the team's areas."""
    clauses = [f"[System.TeamProject] = '{_q(project)}'", f"[System.WorkItemType] IN ({_in(types)})"]
    if iterations:
        clauses.append(f"[System.IterationPath] IN ({_in(iterations)})")
    if iterations_not:
        clauses.append(f"[System.IterationPath] NOT IN ({_in(iterations_not)})")
    if states:
        clauses.append(f"[System.State] IN ({_in(states)})")
    if states_not:
        clauses.append(f"[System.State] NOT IN ({_in(states_not)})")
    if unassigned:
        clauses.append("[System.AssignedTo] = ''")
    if areas:
        clauses.append("(" + " OR ".join(f"[System.AreaPath] {'UNDER' if children else '='} '{_q(path)}'" for path, children in areas) + ")")
    if tags:
        clean_tags: list[str] = []
        for t in tags:
            for part in str(t).replace("(", "").replace(")", "").replace("[", "").replace("]", "").replace("/", ",").split(","):
                p = part.strip()
                if p and p not in clean_tags:
                    clean_tags.append(p)
        if clean_tags:
            tag_clauses = " OR ".join(f"[System.Tags] CONTAINS '{_q(t)}'" for t in clean_tags)
            clauses.append(f"({tag_clauses})")
    return "SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses) + f" ORDER BY {order}"


def read_ids(client: Any, project: str, top: int | None = None, **query: Any) -> list[int]:
    """The ids, in backlog order. A process without the backlog fields answers 400 to the first orders: the next one is tried."""
    for index, order in enumerate(ORDERS):
        try:
            return client.query_wiql(project, build_wiql(project, order=order, **query), top=top)
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) != 400:
                raise
            if index == len(ORDERS) - 1:
                if query.get("tags"):
                    try:
                        query_no_tags = {k: v for k, v in query.items() if k != "tags"}
                        return read_ids(client, project, top=top, **query_no_tags)
                    except Exception:
                        pass
                if query.get("areas"):
                    try:
                        query_no_areas = {k: v for k, v in query.items() if k != "areas"}
                        return read_ids(client, project, top=top, **query_no_areas)
                    except Exception:
                        pass
                if query.get("iterations_not"):
                    try:
                        query_no_iter = {k: v for k, v in query.items() if k != "iterations_not"}
                        return read_ids(client, project, top=top, **query_no_iter)
                    except Exception:
                        pass
                raise
    return []


def read_items(client: Any, project: str, ids: list[int]) -> dict[int, dict[str, Any]]:
    """The raw work items by id, with as many of the wanted fields as the project's process has."""
    if not ids:
        return {}
    for index, fields in enumerate(FIELD_LISTS):
        try:
            raw = client.get_work_items_batch(project, ids, fields)
            return {int(r["id"]): r for r in raw if r.get("id")}
        except requests.HTTPError as exc:
            if index == len(FIELD_LISTS) - 1 or getattr(exc.response, "status_code", None) != 400:
                raise
            logger.info("Azure DevOps rejected an optional field; reading fewer fields")
    return {}


# ---------------------------------------------------------------- one story

def assignee(value: Any) -> tuple[str, str]:
    """(display name, unique name) of who a story is assigned to; empty when nobody."""
    if isinstance(value, dict):
        return str(value.get("displayName") or "").strip(), str(value.get("uniqueName") or "").strip()
    text = str(value or "").strip()
    if "<" in text and text.endswith(">"):
        name, _, mail = text.partition("<")
        return name.strip(), mail.rstrip(">").strip()
    return text, ""


def _tags(value: Any) -> list[str]:
    return [t.strip() for t in str(value or "").split(";") if t.strip()]


def story_flags(state: str, category: str, tags: list[str], blocked_field: Any, elapsed: timedelta | None, active_days: int) -> list[dict[str, str]]:
    """Why a story needs a look: blocked (a tag, a state or the Blocked field says so) or in an active state for more than `active_days` days."""
    flags: list[dict[str, str]] = []
    reasons = []
    tag = next((t for t in tags if BLOCKED in t.lower()), None)
    if tag:
        reasons.append(f'tag "{tag}"')
    if BLOCKED in state.lower():
        reasons.append(f'state "{state}"')
    if str(blocked_field or "").strip().lower() in ("yes", "true"):
        reasons.append("the Blocked field is Yes")
    if reasons:
        flags.append({"code": BLOCKED, "reason": "Blocked: " + ", ".join(reasons)})
    if category == "inprogress" and elapsed is not None and elapsed > timedelta(days=active_days):
        flags.append({"code": LONG_ACTIVE, "reason": f'In "{state}" for {elapsed.days} days (more than {active_days})'})
    return flags


def make_story(raw: dict[str, Any], *, states: StateMap, now: datetime, active_days: int, organization: str, project: str) -> dict[str, Any]:
    fields = raw.get("fields") or {}
    item_id = int(raw.get("id") or fields.get("System.Id") or 0)
    item_type, state = str(fields.get("System.WorkItemType") or ""), str(fields.get("System.State") or "")
    category = states.category(item_type, state)
    name, unique = assignee(fields.get("System.AssignedTo"))
    tags = _tags(fields.get("System.Tags"))
    since, exact = parse_when(fields.get("Microsoft.VSTS.Common.StateChangeDate")), True
    if since is None:  # not every process has the date a state last changed: the date it was activated, or last changed, is the best guess
        since, exact = (parse_when(fields.get("Microsoft.VSTS.Common.ActivatedDate")) if category == "inprogress" else None) or parse_when(fields.get("System.ChangedDate")), False
    elapsed = (now - since) if since else None
    return {
        "id": item_id, "title": str(fields.get("System.Title") or "").strip(), "type": item_type, "state": state, "state_category": category,
        "area_path": str(fields.get("System.AreaPath") or "").strip(), "iteration_path": str(fields.get("System.IterationPath") or "").strip(),
        "assigned_to": name, "assigned_unique": unique, "tags": tags, "points": safe_float(fields.get("Microsoft.VSTS.Scheduling.StoryPoints")),
        "days_in_state": max(0, elapsed.days) if elapsed is not None else None,
        "state_since": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if since else None, "state_since_exact": exact,
        "flags": story_flags(state, category, tags, fields.get("Microsoft.VSTS.CMMI.Blocked"), elapsed, active_days),
        "url": f"https://dev.azure.com/{quote(organization, safe='')}/{quote(project, safe='')}/_workitems/edit/{item_id}",
        "comments": None, "matched_area": None,
    }


def read_comments(client: Any, project: str, story_id: int) -> list[dict[str, str]] | None:
    """The last comments of a story, oldest of them first, as plain text; None when they could not be read."""
    try:
        raw = client.get_work_item_comments(project, story_id, COMMENTS_SHOWN)
    except Exception as exc:  # noqa: BLE001
        logger.info("The comments of work item %s could not be read (%s)", story_id, type(exc).__name__)
        return None
    comments = []
    for c in raw[:COMMENTS_SHOWN]:
        text = strip_html_tags(c.get("text")) or ""
        comments.append({"author": str((c.get("createdBy") or {}).get("displayName") or "Unknown"), "date": str(c.get("createdDate") or ""),
                         "text": text if len(text) <= COMMENT_CHARS else text[:COMMENT_CHARS - 1].rstrip() + "…"})
    return list(reversed(comments))


def usable_types(client: Any, project: str, wanted: list[str]) -> list[str]:
    """The wanted story types that the project's process really has, in the project's own spelling. When the types cannot be listed the wanted ones are used as they are."""
    try:
        names = [str(t.get("name")) for t in client.list_work_item_types(project) if t.get("name") and not t.get("isDisabled")]
    except Exception as exc:  # noqa: BLE001
        logger.info("The work item types could not be listed (%s)", type(exc).__name__)
        return wanted
    by_lower = {n.lower(): n for n in names}
    return [by_lower[w.lower()] for w in dict.fromkeys(wanted) if w.lower() in by_lower]


# ---------------------------------------------------------------- people and areas

def normalize_people(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for person in people:
        name, unique = str(person.get("name") or "").strip(), str(person.get("unique_name") or "").strip()
        key = (unique or name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        areas = list(dict.fromkeys(a.strip() for a in person.get("areas") or [] if str(a).strip()))
        item: dict[str, Any] = {"name": name or unique, "unique_name": unique, "areas": areas}
        if "capacity_points" in person and person["capacity_points"] is not None:
            item["capacity_points"] = safe_float(person["capacity_points"])
        if "working_days" in person and person["working_days"] is not None:
            item["working_days"] = safe_float(person["working_days"])
        if "pto_days" in person and person["pto_days"] is not None:
            item["pto_days"] = safe_float(person["pto_days"])
        if "focus_factor" in person and person["focus_factor"] is not None:
            item["focus_factor"] = safe_float(person["focus_factor"])
        clean.append(item)
    return clean



def area_matches(area_path: str, chosen: list[str], tags: list[str] | None = None) -> str | None:
    """The chosen area that a story's Area Path is, or is under, or matches tags; None when none. "*" means any area."""
    if ANY_AREA in chosen:
        return ANY_AREA
    area = _norm_area(area_path)
    tags_list = [str(t).strip().lower() for t in (tags or []) if str(t).strip()]
    for choice in chosen:
        if choice == ANY_AREA:
            return choice
        base = _norm_area(choice)
        if base and (area == base or area.startswith(base + "\\")):
            return choice
        choice_lower = choice.lower().strip()
        if any(choice_lower == t or choice_lower in t or t in choice_lower for t in tags_list):
            return choice
    return None


def _owner(people: list[dict[str, Any]], story: dict[str, Any]) -> dict[str, Any] | None:
    unique, name = story["assigned_unique"].lower(), story["assigned_to"].lower()
    for person in people:
        if unique and person["unique_name"].lower() == unique:
            return person
        if name and person["name"].lower() == name:
            return person
    return None


# ---------------------------------------------------------------- the plan

def _sum_points(stories: list[dict[str, Any]]) -> float:
    return round(sum(s.get("points") or 0.0 for s in stories), 1)


def make_plan(*, people: list[dict[str, Any]], carried: list[dict[str, Any]], planned: list[dict[str, Any]], backlog: list[dict[str, Any]], per_person: int) -> dict[str, Any]:
    """Who takes what. `carried` are the open stories of the current sprint, `planned` those already in the next sprint, `backlog` the unassigned stories
    that may be taken (in the order they should be taken). Pure: no calls to Azure DevOps."""
    rows = []
    for p in people:
        cap_pts = p.get("capacity_points")
        if cap_pts is None:
            avail_days = max(0.0, (p.get("working_days") or 10.0) - (p.get("pto_days") or 0.0))
            cap_pts = round(avail_days * (p.get("focus_factor") or 0.8), 1)
        rows.append({
            **p,
            "capacity": per_person,
            "capacity_points": cap_pts,
            "points_capacity": cap_pts,
            "carried": [],
            "already_planned": [],
            "new": [],
            "warnings": [],
        })

    by_key = {id(p): r for p, r in zip(people, rows)}
    leftovers: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    outside_planned = 0
    for story in carried:
        owner = _owner(people, story)
        if owner:
            by_key[id(owner)]["carried"].append(story)
        elif story["assigned_to"]:
            outside.append(story)
        else:
            leftovers.append(story)  # open in the current sprint with nobody on it: it is taken first
    for story in planned:
        owner = _owner(people, story)
        if owner:
            by_key[id(owner)]["already_planned"].append(story)
        else:
            outside_planned += 1

    def free(row: dict[str, Any]) -> int:
        return per_person - len(row["carried"]) - len(row["already_planned"]) - len(row["new"])

    unplaced: list[dict[str, Any]] = []
    unplaced_total = 0
    pool = leftovers + backlog
    taken = 0
    for story in pool:
        if not any(free(r) > 0 and r["areas"] for r in rows):  # nobody who can still take a story
            break
        taken += 1
        candidates = [(r, area_matches(story["area_path"], r["areas"], story.get("tags"))) for r in rows if free(r) > 0 and r["areas"]]
        candidates = [(r, area) for r, area in candidates if area]
        if candidates:
            # If story already has an owner who is among candidate team members, prioritize assigning to them
            orig_owner = _owner([c[0] for c in candidates], story) if story.get("assigned_to") else None
            if orig_owner:
                chosen_candidate = next((c for c in candidates if c[0]["name"] == orig_owner["name"]), None)
                if not chosen_candidate:
                    chosen_candidate = min(candidates, key=lambda c: (-free(c[0]), len(c[0]["areas"]), rows.index(c[0])))
            else:
                chosen_candidate = min(candidates, key=lambda c: (-free(c[0]), len(c[0]["areas"]), rows.index(c[0])))
            row, area = chosen_candidate
            row["new"].append({**story, "matched_area": area})
            continue
        unplaced_total += 1
        anyone = any(area_matches(story["area_path"], r["areas"], story.get("tags")) for r in rows if r["areas"])
        if len(unplaced) < MAX_UNPLACED_LISTED:
            unplaced.append({"story": story, "reason": "everyone who chose this area already has a full sprint" if anyone else "nobody has chosen this area"})

    for row in rows:
        row["total"] = len(row["carried"]) + len(row["already_planned"]) + len(row["new"])
        row["open_places"] = max(0, per_person - row["total"])
        row["over_by"] = max(0, row["total"] - per_person)
        row["points_carried"] = _sum_points(row["carried"])
        row["points_already_planned"] = _sum_points(row["already_planned"])
        row["points_new"] = _sum_points(row["new"])
        row["points_planned"] = round(row["points_carried"] + row["points_already_planned"] + row["points_new"], 1)
        cap = row.get("points_capacity") or 0.0
        row["points_over_by"] = max(0.0, round(row["points_planned"] - cap, 1)) if cap > 0 else 0.0
        row["points_open"] = max(0.0, round(cap - row["points_planned"], 1)) if cap > 0 else 0.0

        if not row["areas"]:
            row["warnings"].append("No area of choice is set, so no new story can be given to this person.")
        if row["open_places"]:
            where = "any area" if ANY_AREA in row["areas"] else "their areas" if row["areas"] else "no area"
            row["warnings"].append(f"{row['open_places']} place{'s' if row['open_places'] != 1 else ''} still empty: no unassigned story is left in {where}.")
        if row["over_by"]:
            row["warnings"].append(f"{row['over_by']} more than the {per_person} planned: that many stories are carried over or already in the sprint.")
        if row["points_capacity"] and row["points_planned"] > row["points_capacity"] * 1.15:
            row["warnings"].append(f"Capacity exceeded: {row['points_planned']} pts allocated exceeds estimated {row['points_capacity']} pts capacity.")

    return {"people": rows, "outside_plan": outside, "outside_planned": outside_planned, "unplaced": unplaced, "unplaced_total": unplaced_total,
            "backlog_left": max(0, len(pool) - taken)}


# ---------------------------------------------------------------- setup and plan, from Azure DevOps

def _walk_areas(node: dict[str, Any], parent: str, out: list[str]) -> None:
    path = f"{parent}\\{node.get('name')}" if parent else str(node.get("name") or "")
    if path:
        out.append(path)
    for child in node.get("children") or []:
        _walk_areas(child, path, out)


def area_choices(client: Any, project: str, scopes: list[tuple[str, bool]]) -> list[str]:
    """Every area path of the project, or those inside the team's areas when the team has some, as Azure DevOps writes them in a work item's Area Path."""
    paths: list[str] = []
    _walk_areas(client.get_area_tree(project), "", paths)
    return [p for p in paths if is_in_team_areas(p, scopes)]


def team_scopes(client: Any, project: str, team: str) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]], str | None]:
    """(the team's area paths as written, the same normalized, a note when they could not be read)."""
    try:
        written = team_area_paths(client.get_team_field_values(project, team))
    except Exception as exc:  # noqa: BLE001
        logger.info("The area paths of team %s could not be read (%s)", team, type(exc).__name__)
        return [], [], f"The area paths of team '{team}' could not be read, so stories of every area are considered."
    return written, parse_team_area_scopes({"values": [{"value": p, "includeChildren": c} for p, c in written]}), None


def team_setup(client: Any, project: str, team: str) -> dict[str, Any]:
    """What the planning page needs to start: the sprints and the two to propose, the team's members, the area paths to choose from and the story types."""
    notes: list[str] = []
    sprints = list_sprints(client, project, team)
    from_id, to_id = default_sprints(sprints)
    written, scopes, note = team_scopes(client, project, team)
    if note:
        notes.append(note)
    try:
        members = [m["identity"] for m in client.list_team_members(project, team) if isinstance(m.get("identity"), dict) and not m["identity"].get("isContainer")]
    except Exception as exc:  # noqa: BLE001
        logger.info("The members of team %s could not be read (%s)", team, type(exc).__name__)
        members, notes = [], notes + ["The members of the team could not be read: add the people by hand."]
    try:
        areas = area_choices(client, project, scopes)
    except Exception as exc:  # noqa: BLE001
        logger.info("The area tree could not be read (%s)", type(exc).__name__)
        areas, notes = [], notes + ["The areas of the project could not be read: type the area paths by hand."]
    try:
        names = [str(t.get("name")) for t in client.list_work_item_types(project) if t.get("name") and not t.get("isDisabled")]
    except Exception as exc:  # noqa: BLE001
        logger.info("The work item types could not be read (%s)", type(exc).__name__)
        names = []
    types = [t for t in STORY_TYPES if t in names] or list(DEFAULT_TYPES)
    return {"team": team, "sprints": sprints, "default_from_id": from_id, "default_to_id": to_id,
            "members": [{"name": str(m.get("displayName") or ""), "unique_name": str(m.get("uniqueName") or "")} for m in members if m.get("displayName") or m.get("uniqueName")],
            "areas": areas, "work_item_types": types, "default_types": [t for t in types if t in DEFAULT_TYPES] or types[:1],
            "per_person": DEFAULT_PER_PERSON, "active_days": DEFAULT_ACTIVE_DAYS, "notes": notes}


def _calculate_risks(people_rows: list[dict[str, Any]], flagged: list[dict[str, Any]], all_planned_stories: list[dict[str, Any]]) -> tuple[str, list[str], int, list[str]]:
    reasons: list[str] = []
    recommendations: list[str] = []
    score_points = 0

    blocked_count = sum(1 for s in flagged if any(f["code"] == BLOCKED for f in s.get("flags", [])))
    if blocked_count > 0:
        reasons.append(f"{blocked_count} carried-over {'story is' if blocked_count == 1 else 'stories are'} currently Blocked.")
        recommendations.append(f"Unblock or descope {blocked_count} blocked work items before confirming sprint commitment.")
        score_points += blocked_count * 2

    unpointed = [s for s in all_planned_stories if s.get("points") is None]
    if unpointed:
        reasons.append(f"{len(unpointed)} planned {'story has' if len(unpointed) == 1 else 'stories have'} no Story Points estimated.")
        recommendations.append(f"Estimate points for {len(unpointed)} unpointed items to ensure accurate workload balancing.")
        score_points += 1 if len(unpointed) < 3 else 2

    overloaded = [r for r in people_rows if r.get("points_capacity") and r.get("points_planned", 0) > r["points_capacity"]]
    if overloaded:
        names = ", ".join(r["name"] for r in overloaded)
        reasons.append(f"Capacity exceeded for {names}.")
        recommendations.append(f"Rebalance assignments from {names} to team members with available capacity.")
        score_points += 2

    empty_members = [r for r in people_rows if r.get("open_places", 0) > 0 and r.get("areas")]
    if empty_members and not overloaded:
        recommendations.append("All team members are within capacity limits. Review sprint goal alignment.")

    risk_score = "High" if score_points >= 4 else "Medium" if score_points >= 2 else "Low"
    confidence = max(40, min(95, 95 - (score_points * 12)))
    return risk_score, reasons, confidence, recommendations


def plan_sprint(client: Any, *, organization: str, project: str, team: str, from_iteration_id: str, to_iteration_id: str, people: list[dict[str, Any]],
                per_person: int = DEFAULT_PER_PERSON, active_days: int = DEFAULT_ACTIVE_DAYS, work_item_types: list[str] | None = None,
                sprint_goal: str | None = None, capacity_mode: str = "stories", focus_factor: float = 0.8,
                tags: list[str] | None = None, area_filter: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    crew = normalize_people(people)
    if not crew:
        raise PlanningError("Add at least one person to plan for.")
    if len(crew) > MAX_PEOPLE:
        raise PlanningError(f"At most {MAX_PEOPLE} people can be planned at once.")
    if not 1 <= per_person <= MAX_PER_PERSON:
        raise PlanningError(f"Stories per person must be between 1 and {MAX_PER_PERSON}.")
    if not 1 <= active_days <= MAX_ACTIVE_DAYS:
        raise PlanningError(f"The days in an active state must be between 1 and {MAX_ACTIVE_DAYS}.")
    sprints = {s["id"]: s for s in list_sprints(client, project, team)}
    source, target = sprints.get(str(from_iteration_id)), sprints.get(str(to_iteration_id))
    if source is None or target is None:
        raise PlanningError("Choose the sprint to carry stories from and the sprint to plan: one of them is not a sprint of this team.")
    if source["id"] == target["id"]:
        raise PlanningError("The sprint to plan must be a different sprint than the one stories are carried from.")
    wanted = [t.strip() for t in (work_item_types or list(DEFAULT_TYPES)) if t.strip()] or list(DEFAULT_TYPES)
    types = usable_types(client, project, wanted)
    if not types:
        raise PlanningError(f"None of the story types ({', '.join(wanted)}) exists in project '{project}'. Choose the types to plan from.")
    notes: list[str] = []
    written, scopes, note = team_scopes(client, project, team)
    if note:
        notes.append(note)
    states = load_state_map(client, project)
    finished = states.finished_state_names()

    backlog_areas = written
    if area_filter and area_filter.strip():
        filt = area_filter.strip()
        if filt == project or filt.lower().startswith(f"{project.lower()}\\"):
            backlog_areas = [(filt, True)]
        else:
            try:
                all_areas = area_choices(client, project, [])
                matched = next((a for a in all_areas if a.lower() == filt.lower() or a.lower().endswith("\\" + filt.lower()) or a.lower() == f"{project.lower()}\\{filt.lower()}"), None)
                if matched:
                    backlog_areas = [(matched, True)]
                else:
                    backlog_areas = [(f"{project}\\{filt}", True)]
            except Exception:
                backlog_areas = [(f"{project}\\{filt}", True)]

    carried_ids = read_ids(client, project, types=types, areas=written, iterations=[source["path"]], states_not=finished)
    planned_ids = read_ids(client, project, types=types, areas=written, iterations=[target["path"]], states_not=finished)

    # 1. Primary query: unassigned candidate stories in backlog areas not in source sprint, not finished
    backlog_ids = read_ids(
        client, project, top=MAX_BACKLOG, types=types, areas=backlog_areas,
        iterations_not=[source["path"]], states_not=finished, unassigned=True, tags=tags
    )

    # 2. Fallback: If 0 found with unassigned=True, query all open backlog stories (assigned or unassigned)
    if not backlog_ids:
        backlog_ids = read_ids(
            client, project, top=MAX_BACKLOG, types=types, areas=backlog_areas,
            iterations_not=[source["path"]], states_not=finished, tags=tags
        )

    # 3. Fallback: If still 0 and tags were specified in WIQL, relax tags in query
    if not backlog_ids and tags:
        backlog_ids = read_ids(
            client, project, top=MAX_BACKLOG, types=types, areas=backlog_areas,
            iterations_not=[source["path"]], states_not=finished
        )

    # 4. Fallback: If still 0 and area_filter differed from written scopes, try written scopes
    if not backlog_ids and area_filter and backlog_areas != written:
        backlog_ids = read_ids(
            client, project, top=MAX_BACKLOG, types=types, areas=written,
            iterations_not=[source["path"]], states_not=finished
        )

    # 5. Fallback: If still 0, query project-level open stories
    if not backlog_ids and (written or backlog_areas):
        backlog_ids = read_ids(
            client, project, top=MAX_BACKLOG, types=types,
            iterations_not=[source["path"]], states_not=finished
        )

    all_backlog_ids = backlog_ids
    raw = read_items(client, project, list(dict.fromkeys(carried_ids + planned_ids + all_backlog_ids)))

    def matches_team_item(s: dict[str, Any]) -> bool:
        if not scopes and not area_filter and not tags:
            return True
        if is_in_team_areas(s["area_path"], scopes):
            return True
        if area_filter and (area_filter.lower() in s.get("area_path", "").lower() or s.get("area_path", "").lower() in area_filter.lower()):
            return True
        story_tags_lower = [t.lower() for t in s.get("tags", [])]
        if tags:
            check_kws = [k.lower().strip() for k in tags if k.strip()]
            for ck in check_kws:
                for part in ck.replace("/", ",").split(","):
                    p = part.strip()
                    if p and any(p in st or st in p for st in story_tags_lower):
                        return True
        return False

    def stories(ids: list[int]) -> list[dict[str, Any]]:
        made = [make_story(raw[i], states=states, now=now, active_days=active_days, organization=organization, project=project) for i in ids if i in raw]
        return [s for s in made if matches_team_item(s)]

    carried = stories(carried_ids)
    planned = [s for s in stories(planned_ids) if s["assigned_to"]]  # a story in the next sprint that nobody has yet is offered like the backlog (it is in the backlog query)
    taken = {s["id"] for s in carried} | {s["id"] for s in planned}
    backlog = [s for s in stories(all_backlog_ids) if s["id"] not in taken]
    if not backlog:
        notes.append(f"No backlog stories were found matching team criteria in '{project}'.")
    result = make_plan(people=crew, carried=carried, planned=planned, backlog=backlog, per_person=per_person)


    flagged = [s for s in carried if s["flags"]]
    if flagged:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for story, comments in zip(flagged[:MAX_COMMENT_READS], pool.map(lambda s: read_comments(client, project, s["id"]), flagged[:MAX_COMMENT_READS])):
                story["comments"] = comments
        if len(flagged) > MAX_COMMENT_READS:
            notes.append(f"Comments were read for the first {MAX_COMMENT_READS} of {len(flagged)} flagged stories.")
        if any(s["comments"] is None for s in flagged[:MAX_COMMENT_READS]):
            notes.append("The comments of some flagged stories could not be read (the token may lack the Work Items read scope).")
    if any(not s["state_since_exact"] for s in carried if s["state_category"] == "inprogress"):
        notes.append("Some stories have no 'state changed' date in this process: the days in state are counted from the date they were activated or last changed.")
    if result["outside_plan"]:
        notes.append(f"Open stories of people who are not in this plan: {len(result['outside_plan'])} (listed apart, not counted for anyone).")
    if result["outside_planned"]:
        notes.append(f"Stories already in {target['name']} that belong to people who are not in this plan: {result['outside_planned']} (not counted for anyone).")

    people_rows = result["people"]
    all_planned = [s for r in people_rows for s in (r["carried"] + r["already_planned"] + r["new"])]
    risk_score, risk_reasons, confidence, ai_recs = _calculate_risks(people_rows, flagged, all_planned)

    total_pts_planned = round(sum(r.get("points_planned", 0.0) for r in people_rows), 1)
    total_pts_cap = round(sum(r.get("points_capacity", 0.0) or 0.0 for r in people_rows), 1)
    pts_carried = round(sum(r.get("points_carried", 0.0) for r in people_rows), 1)
    pts_new = round(sum(r.get("points_new", 0.0) for r in people_rows), 1)
    unpointed_count = sum(1 for s in all_planned if s.get("points") is None)

    return {
        "team": team, "project": project, "from_sprint": source, "to_sprint": target, "per_person": per_person, "active_days": active_days, "work_item_types": types,
        "sprint_goal": sprint_goal or "", "capacity_mode": capacity_mode, "people": people_rows, "flagged": flagged, "unplaced": result["unplaced"],
        "unplaced_total": result["unplaced_total"], "outside_plan": result["outside_plan"], "backlog_left": result["backlog_left"], "notes": notes,
        "ai_recommendations": ai_recs,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "posted_to_ado": False,
        "summary": {
            "people": len(people_rows), "stories_planned": sum(r["total"] for r in people_rows), "carried": sum(len(r["carried"]) for r in people_rows),
            "new": sum(len(r["new"]) for r in people_rows), "already_planned": sum(len(r["already_planned"]) for r in people_rows),
            "flagged": len(flagged), "blocked": sum(1 for s in flagged if any(f["code"] == BLOCKED for f in s["flags"])),
            "long_active": sum(1 for s in flagged if any(f["code"] == LONG_ACTIVE for f in s["flags"])),
            "unplaced": result["unplaced_total"], "open_places": sum(r["open_places"] for r in people_rows),
            "total_points_planned": total_pts_planned,
            "total_points_capacity": total_pts_cap,
            "points_carried": pts_carried,
            "points_new": pts_new,
            "unpointed_stories": unpointed_count,
            "risk_score": risk_score,
            "risk_reasons": risk_reasons,
            "sprint_confidence_pct": confidence,
        },
    }


def commit_sprint_plan(client: Any, *, project: str, iteration_path: str, assignments: list[dict[str, Any]], sprint_goal: str | None = None) -> dict[str, Any]:
    """Applies the planned assignments and target iteration path to Azure DevOps work items."""
    updated = 0
    errors: list[str] = []
    for item in assignments:
        story_id = item.get("story_id")
        if not story_id:
            continue
        patch: list[dict[str, Any]] = [
            {"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path}
        ]
        assigned_to = item.get("assigned_to")
        if assigned_to is not None:
            patch.append({"op": "add", "path": "/fields/System.AssignedTo", "value": assigned_to})
        try:
            client.update_work_item(project, int(story_id), patch)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to commit work item %s: %s", story_id, exc)
            errors.append(f"#{story_id}: {getattr(exc, 'message', str(exc))}")

    message = f"Successfully updated {updated} work item{'s' if updated != 1 else ''} into '{iteration_path}'."
    if errors:
        message += f" Encountered {len(errors)} error{'s' if len(errors) != 1 else ''}."
    return {"success": len(errors) == 0, "updated_count": updated, "message": message, "errors": errors}


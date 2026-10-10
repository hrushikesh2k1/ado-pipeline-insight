"""Completion-event reporting, independent of the assigned iteration.

Use the last completed episode within a period, with state at period end.
Re-completions of previously delivered items are shown separately, without
counting their cumulative effort twice. No effort is inferred from capacity.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import math
import re
from typing import Any
from urllib.parse import quote

from app.services.board_service import is_in_team_areas, parse_team_area_scopes
from app.services.work_item_scope import parse_when as parse_ado_date


def identity(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"id": str(raw or "unassigned"), "name": str(raw or "Unassigned"), "email": None}
    email = raw.get("uniqueName") or raw.get("mailAddress") or ""
    email = email if re.fullmatch(r"[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+", email) else None
    return {"id": raw.get("id") or email or raw.get("displayName") or "unassigned",
            "name": raw.get("displayName") or email or "Unassigned", "email": email}


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def completed(fields: dict, states: dict[str, set[str]]) -> bool:
    return str(fields.get("System.State", "")).lower() in states.get(str(fields.get("System.WorkItemType", "")).lower(), set())


def completion_record(revisions: list[dict], states: dict[str, set[str]], start: datetime,
                      end: datetime, scopes: list, iteration_path: str) -> dict | None:
    ordered = sorted(revisions, key=lambda r: int(r.get("rev", 0)))
    previous_done = False
    events: list[tuple[dict, datetime]] = []
    snapshot = None
    for revision in ordered:
        fields = revision.get("fields", {})
        changed = parse_ado_date(fields.get("System.ChangedDate"))
        if not changed:
            raise ValueError("A work item revision has no valid change date; historical reporting is unavailable.")
        done = completed(fields, states)
        if done and not previous_done:
            events.append((revision, changed))
        previous_done = done
        if changed < end:
            snapshot = revision
    if not snapshot:
        return None
    candidates = [(rev, when) for rev, when in events if start <= when < end]
    if not candidates:
        return None
    closing, when = candidates[-1]
    fields = closing["fields"]
    if not is_in_team_areas(fields.get("System.AreaPath"), scopes):
        return None
    past_delivery = any(date < start for _, date in events)
    still_done = completed(snapshot["fields"], states)
    latest = ordered[-1]["fields"]
    parent = fields.get("System.Parent") or snapshot["fields"].get("System.Parent")
    effort = number(snapshot["fields"].get("Microsoft.VSTS.Scheduling.CompletedWork"))
    path = fields.get("System.IterationPath", "")
    return {"id": closing.get("id") or fields.get("System.Id"),
            "title": fields.get("System.Title", ""), "type": fields.get("System.WorkItemType", ""),
            "owner": identity(fields.get("System.AssignedTo")), "completed_at": when.isoformat(),
            "iteration_path": path, "cross_iteration": path.lower() != iteration_path.lower(),
            "parent_id": parent, "recorded_hours": effort,
            "status": "reopened_in_period" if not still_done else "recompleted" if past_delivery else "delivered",
            "reopened_after_period": still_done and not completed(latest, states),
            "completion_events_in_period": len(candidates)}


def available_hours(capacity: dict, start: datetime, end: datetime, team_days: list,
                    working_days: set[int] | None = None) -> float | None:
    daily_values = [number(a.get("capacityPerDay")) for a in capacity.get("activities", [])]
    if not daily_values or any(value is None for value in daily_values):
        return None
    days_off = capacity.get("daysOff", []) + team_days
    day = start.date()
    finish = (end - timedelta(microseconds=1)).date()
    workdays = 0
    while day <= finish:
        absent = False
        for off in days_off:
            first, last = parse_ado_date(off.get("start")), parse_ado_date(off.get("end"))
            if not first or not last:
                return None
            if first.date() <= day <= last.date():
                absent = True
        if day.weekday() in (working_days if working_days is not None else {0, 1, 2, 3, 4}) and not absent:
            workdays += 1
        day += timedelta(days=1)
    return round(workdays * sum(daily_values), 2)


def build_report(ado: Any, project: str, team: str, iteration_id: str) -> dict:
    iteration = ado.get_team_iteration(project, team, iteration_id)
    attrs = iteration.get("attributes") or {}
    start_raw, finish_raw = parse_ado_date(attrs.get("startDate")), parse_ado_date(attrs.get("finishDate"))
    if not start_raw or not finish_raw:
        raise ValueError("Configure the sprint start and finish dates in Azure DevOps before generating deliverables.")
    # Azure iteration dates are calendar dates. Include the entire finish day in UTC.
    start = datetime.combine(start_raw.date(), datetime.min.time(), timezone.utc)
    end = datetime.combine(finish_raw.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
    if end <= start:
        raise ValueError("The sprint finish date must not precede its start date.")
    scopes = parse_team_area_scopes(ado.get_team_field_values(project, team))
    if not scopes:
        raise ValueError("The selected team's area paths could not be verified. Configure team areas before reporting.")
    states = {}
    for kind in ado.list_work_item_types(project):
        name = kind["name"]
        states[name.lower()] = {s["name"].lower() for s in ado.list_work_item_type_states(project, name)
                                if str(s.get("category", "")).lower() == "completed"}
    if not any(states.values()):
        raise ValueError("Azure DevOps completed-state definitions are unavailable.")
    # Project-wide candidates deliberately have NO iteration or current-area restriction:
    # a delivered item may have been moved or reopened since sprint end.
    ids: list[int] = []
    last_id = 0
    safe_project = project.replace("'", "''")
    while True:
        page = ado.query_wiql(project,
            f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{safe_project}' "
            f"AND [System.ChangedDate] >= '{start.isoformat()}' AND [System.Id] > {last_id} ORDER BY [System.Id]", top=5000)
        if not page:
            break
        if min(page) <= last_id:
            raise ValueError("Azure DevOps candidate pagination did not advance.")
        ids.extend(page)
        last_id = max(page)
        if len(ids) > 50000:
            raise ValueError("This report exceeds 50,000 changed items. Use a shorter sprint period.")
        if len(page) < 5000:
            break
    def read_record(item_id: int) -> dict | None:
        record = completion_record(ado.list_work_item_revisions(project, item_id), states, start, end,
                                   scopes, iteration.get("path", ""))
        if record:
            record["web_url"] = f"https://dev.azure.com/{quote(ado.organization, safe='')}/{quote(project, safe='')}/_workitems/edit/{item_id}"
        return record
    # Bounded read concurrency keeps history requests practical for monthly sprints.
    # Any failed read aborts the report rather than presenting incomplete totals.
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = [record for record in pool.map(read_record, ids) if record]
    warnings = ["Dates use UTC calendar days. Team areas, state definitions and recipient membership use current Azure DevOps configuration.",
                "Recorded effort is cumulative Completed Work at sprint end, not hours worked during this sprint. Only task effort is summed; parent effort is excluded."]
    members = []
    recipients_verified = True
    try:
        members = [identity(m.get("identity", {})) for m in ado.list_team_members(project, team)]
    except Exception:
        recipients_verified = False
        warnings.append("Team membership could not be verified. Outlook drafting is disabled.")
    capacities = {}
    breakdowns = {}
    try:
        raw = ado.get_iteration_capacity(project, team, iteration_id)
        team_days = ado.get_team_days_off(project, team, iteration_id).get("daysOff", [])
        settings = ado.get_team_settings(project, team)
        weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        configured = settings.get("workingDays")
        if not isinstance(configured, list) or any(str(day).lower() not in weekday_names for day in configured):
            raise ValueError("Team working days could not be verified.")
        working_days = {weekday_names.index(str(day).lower()) for day in configured}
        for cap in raw.get("teamMembers", raw.get("value", [])):
            who = identity(cap.get("teamMember", {}))
            hours = available_hours(cap, start, end, team_days, working_days)
            daily_values = [number(a.get("capacityPerDay")) for a in cap.get("activities", [])]
            daily = sum(daily_values) if daily_values and all(v is not None for v in daily_values) else None
            working_count = sum((start + timedelta(days=i)).weekday() in working_days for i in range((end-start).days))
            capacities[who["id"]] = hours
            breakdowns[who["id"]] = {"source": "Azure DevOps iteration capacities and team settings (current configuration)",
                "daily_hours": daily, "available_days": hours / daily if daily and hours is not None else None,
                "working_days_before_leave": working_count,
                "days_off_on_working_days": working_count - hours / daily if daily and hours is not None else None,
                "working_days": configured, "individual_days_off": cap.get("daysOff", []), "team_days_off": team_days}
    except Exception:
        warnings.append("Available capacity is unavailable. No default hours or leave estimates were substituted.")
    people = {m["id"]: {**m, "items": [], "available_hours": capacities.get(m["id"])} for m in members}
    for item in records:
        who = item["owner"]
        person = people.setdefault(who["id"], {**who, "items": [], "available_hours": capacities.get(who["id"])})
        person["items"].append(item)
    for person in people.values():
        person["capacity_breakdown"] = breakdowns.get(person["id"])
        delivered = [i for i in person["items"] if i["status"] == "delivered"]
        tasks = [i for i in delivered if i["type"].lower() == "task"]
        person.update(delivered_count=len([i for i in delivered if i["type"].lower() != "task"]),
                      completed_tasks=len(tasks), recorded_hours=round(sum(i["recorded_hours"] or 0 for i in tasks), 2),
                      missing_effort_count=sum(i["recorded_hours"] is None for i in tasks))
    delivered = [i for i in records if i["status"] == "delivered"]
    return {"team": team, "sprint": iteration.get("name", iteration_id),
            "iteration_path": iteration.get("path", ""), "start": start.isoformat(), "end_exclusive": end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(), "provisional": datetime.now(timezone.utc) < end,
            "delivered_count": sum(i["type"].lower() != "task" for i in delivered),
            "completed_tasks": sum(i["type"].lower() == "task" for i in delivered),
            "recorded_hours": round(sum(p["recorded_hours"] for p in people.values()), 2),
            "missing_effort_count": sum(p["missing_effort_count"] for p in people.values()),
            "cross_iteration_count": sum(i["cross_iteration"] for i in delivered),
            "people": sorted(people.values(), key=lambda p: p["name"].lower()),
            "recipients": sorted({m["email"] for m in members if m["email"]}),
            "missing_recipient_names": [m["name"] for m in members if not m["email"]],
            "recipients_verified": recipients_verified, "warnings": warnings}

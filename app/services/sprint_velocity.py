"""Single-sprint individual forecasts. Capacity hours are never converted to points."""
from datetime import datetime, time, timezone
from typing import Any

from app.services.board_service import calculate_sprint_working_days
from app.services.sprint_capacity import normalize_capacity_members
from app.services import sprint_planning as planning


def previous_completed_sprint(sprints: list[dict], target: dict, now: datetime) -> dict | None:
    target_start = planning.parse_when(target.get("start"))
    candidates = []
    for sprint in sprints:
        finish = planning.parse_when(sprint.get("finish"))
        if not finish or sprint["id"] == target["id"]:
            continue
        end = datetime.combine(finish.date(), time.max, tzinfo=timezone.utc)
        if end < now and (not target_start or end < target_start):
            candidates.append((end, sprint))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def capacity_snapshot(client: Any, project: str, team: str, sprint: dict) -> dict:
    start, finish = planning.parse_when(sprint.get("start")), planning.parse_when(sprint.get("finish"))
    days = calculate_sprint_working_days(start, finish)
    if days is None:
        raise planning.PlanningError("Sprint dates are required to read Capacity-tab working days.")
    members = normalize_capacity_members(client.get_iteration_capacities(project, team, sprint["id"]), start, finish)
    return {"iteration_id": sprint["id"], "working_days": days, "members": members}


def velocity_context(client: Any, project: str, team: str, target_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sprints = planning.list_sprints(client, project, team)
    target = next((s for s in sprints if s["id"] == target_id), None)
    if target is None:
        raise planning.PlanningError("The target sprint is not a sprint of the selected team.")
    previous = previous_completed_sprint(sprints, target, now)
    notes = ["Forecast uses one completed sprint and may be affected by unusual incidents or blocked work."]
    snapshots = {}
    for label, sprint in (("upcoming", target), ("previous", previous)):
        if not sprint:
            snapshots[f"{label}_capacity"] = None
            continue
        try:
            snapshots[f"{label}_capacity"] = capacity_snapshot(client, project, team, sprint)
        except Exception as exc:
            planning.logger.warning("Capacity source unavailable (%s)", type(exc).__name__)
            days = calculate_sprint_working_days(planning.parse_when(sprint.get("start")), planning.parse_when(sprint.get("finish")))
            snapshots[f"{label}_capacity"] = {"iteration_id": sprint["id"], "working_days": days, "members": []} if days is not None else None
            notes.append(f"{label.capitalize()} Azure DevOps Capacity data could not be read. Only saved Capacity-tab entries with valid sprint dates can be used; no default availability will be assumed.")
    return {"target": target, "previous": previous, **snapshots, "notes": notes}


def completed_points(client: Any, project: str, team: str, sprint: dict, types: list[str]) -> list[dict]:
    finish = planning.parse_when(sprint["finish"])
    as_of = datetime.combine(finish.date(), time.max, tzinfo=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    written, _, note = planning.team_scopes(client, project, team)
    if note:
        raise planning.PlanningError("Historical team scope could not be read; velocity cannot be established reliably.")
    query = planning.build_wiql(project, types=types, areas=written, iterations=[sprint["path"]], order="[System.Id] ASC")
    ids = client.query_wiql(project, query + f" ASOF '{as_of}'")
    fields = ["System.Id", "System.AssignedTo", "System.State", "System.WorkItemType", "Microsoft.VSTS.Scheduling.StoryPoints"]
    items = client.get_work_items_batch(project, ids, fields=fields, as_of=as_of)
    if {int(item["id"]) for item in items} != set(ids):
        raise planning.PlanningError("Historical work-item snapshots are incomplete; velocity is unavailable.")
    states = {}
    for kind in types:
        definitions = client.list_work_item_type_states(project, kind)
        if not definitions or any(not state.get("name") or not state.get("category") for state in definitions):
            raise planning.PlanningError("Process state categories are unavailable; completed-point history cannot be verified.")
        states[kind.casefold()] = {state["name"].casefold(): state["category"].casefold() for state in definitions}
    totals: dict[str, dict] = {}
    for item in items:
        data = item.get("fields") or {}
        category = states.get(data.get("System.WorkItemType", "").casefold(), {}).get(data.get("System.State", "").casefold())
        if category is None:
            raise planning.PlanningError("A historical work-item state has no verified process category; velocity is unavailable.")
        if category != "completed":
            continue
        name, unique = planning.assignee(data.get("System.AssignedTo"))
        key = (unique or name).strip().casefold()
        if not key:
            continue
        row = totals.setdefault(key, {"name": name, "unique_name": unique, "points": 0.0, "missing_points": False})
        points = planning.safe_float(data.get("Microsoft.VSTS.Scheduling.StoryPoints"))
        if points is None or points < 0:
            row["missing_points"] = True
        else:
            row["points"] += points
    return list(totals.values())


def exact_person(rows: list[dict], person: dict) -> dict | None:
    unique = person.get("unique_name", "").strip().casefold()
    if unique:
        matches = [row for row in rows if (row.get("unique_name") or "").strip().casefold() == unique]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
    # Name fallback is only safe if neither side supplies conflicting identity information.
    matches = [row for row in rows if row.get("name", "").strip().casefold() == person["name"].strip().casefold()
               and (not unique or not row.get("unique_name"))]
    return matches[0] if len(matches) == 1 else None


def forecast_people(client: Any, project: str, team: str, target_id: str, people: list[dict], capacity: dict,
                    types: list[str], now: datetime) -> tuple[list[dict], list[str]]:
    context = velocity_context(client, project, team, target_id, now)
    previous = context["previous"]
    if capacity["target_iteration_id"] != target_id or capacity.get("previous_iteration_id") != (previous["id"] if previous else None):
        raise planning.PlanningError("Capacity context changed. Refresh Capacity data and generate the plan again.")
    totals, history_error = [], None
    if previous:
        try:
            totals = completed_points(client, project, team, previous, types)
        except Exception as exc:
            planning.logger.warning("Historical velocity unavailable (%s)", type(exc).__name__)
            history_error = "Previous sprint-end history could not be read; automatic assignments are paused."
    else:
        history_error = "No previous completed sprint is available."
    result = []
    for person in people:
        upcoming = exact_person(capacity["upcoming_members"], person)
        old = exact_person(capacity["previous_members"], person)
        historical = exact_person(totals, person)
        days = context["upcoming_capacity"]["working_days"] if context["upcoming_capacity"] else None
        previous_days = context["previous_capacity"]["working_days"] if context["previous_capacity"] else None
        available = max(0, days - upcoming["days_off"]) if upcoming and days is not None else None
        previous_available = max(0, previous_days - old["days_off"]) if old and previous_days is not None else None
        reason = history_error
        if available is None or previous_available is None:
            reason = "Capacity-tab entry or sprint dates are missing for this person; no default is assumed."
        elif previous_available <= 0:
            reason = "Previous available days are zero; velocity cannot be calculated."
        elif old["capacity_per_day"] <= 0:
            reason = "Previous daily capacity is zero; review the Capacity tab before forecasting."
        elif not historical:
            reason = reason or "No completed-point history matched this person at the previous sprint's end."
        elif historical["missing_points"]:
            reason = "Completed work has missing points; historical velocity is incomplete."
        budget = round(historical["points"] * available / previous_available, 2) if not reason else None
        if budget is not None and upcoming["capacity_per_day"] == 0:
            budget = 0.0
        result.append({**person, "velocity_based": True, "capacity_points": budget, "working_days": days or 0,
                       "pto_days": upcoming["days_off"] if upcoming else 0,
                       "total_capacity_hours": round(available * upcoming["capacity_per_day"], 1) if available is not None else None,
                       "previous_completed_points": historical["points"] if historical else None,
                       "previous_available_days": previous_available, "forecast_status": "unavailable" if reason else "ready",
                       "forecast_note": reason})
    return result, context["notes"]

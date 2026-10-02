from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


def calculate_business_days(start_date: datetime, end_date: datetime | None = None) -> int:
    """Calculate the number of business days (Monday to Friday) elapsed between start_date and end_date."""
    if end_date is None:
        end_date = datetime.now(timezone.utc)
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)

    if start_date >= end_date:
        return 0

    business_days = 0
    cur = start_date.date()
    target = end_date.date()

    while cur < target:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
            business_days += 1

    return business_days


def calculate_remaining_work_days(finish_date: datetime | None, now: datetime | None = None) -> int | None:
    """Calculate remaining working days in a sprint up to finish_date."""
    if not finish_date:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if finish_date.tzinfo is None:
        finish_date = finish_date.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if now.date() >= finish_date.date():
        return 0

    remaining_days = 0
    cur = now.date()
    target = finish_date.date()
    while cur < target:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            remaining_days += 1
    return remaining_days


def parse_ado_date(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        clean = val.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).strip()
        if not s:
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


import html
import re

def strip_html_tags(text: str | None) -> str:
    """Clean rich text from Azure DevOps fields into readable plain text."""
    if not text:
        return ""
    clean = html.unescape(str(text))
    # Replace break and paragraph tags with newlines
    clean = re.sub(r"<(?:br|br\s*\/|\/p|\/li|\/div|tr)>", "\n", clean, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    clean = re.sub(r"<[^>]+>", "", clean)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    return "\n".join(lines)


def is_work_item_in_iteration(
    item_iter_path: Any | None = None,
    item_iter_id: int | None = None,
    iteration: Any | None = None,
    *,
    target_iteration_path: str | None = None,
    target_iteration_name: str | None = None,
    target_iteration_id: int | None = None,
) -> bool:
    """Verify whether a work item strictly belongs to the specified sprint iteration.

    Prevents cross-sprint leakage where linked items (e.g. bug 1084653 assigned to October)
    inadvertently appear on the September sprint board because of parent/child hierarchy relations.
    """
    # If first argument is a work item dict / object, extract its iteration fields
    if isinstance(item_iter_path, dict):
        fields = item_iter_path.get("fields", item_iter_path)
        extracted_path = fields.get("System.IterationPath") or fields.get("iteration_path")
        extracted_id = fields.get("System.IterationId") or fields.get("iteration_id")
        if item_iter_id is None:
            item_iter_id = extracted_id
        item_iter_path = extracted_path

    if iteration is None:
        if target_iteration_path is not None or target_iteration_name is not None or target_iteration_id is not None:
            iteration = {
                "path": target_iteration_path,
                "name": target_iteration_name,
                "id": target_iteration_id,
            }
        else:
            return True

    if isinstance(iteration, dict):
        iter_path = iteration.get("path")
        iter_name = iteration.get("name")
        iter_id = iteration.get("id")
    else:
        iter_path = getattr(iteration, "path", None)
        iter_name = getattr(iteration, "name", None)
        iter_id = getattr(iteration, "id", None)

    # If neither path nor name is provided on iteration, do not filter
    if not iter_path and not iter_name and not iter_id:
        return True

    # If work item has no iteration path at all, fallback to ID if present
    if not item_iter_path:
        if item_iter_id is not None and iter_id:
            try:
                return int(item_iter_id) == int(iter_id)
            except (ValueError, TypeError):
                pass
        return False

    norm_item = str(item_iter_path).strip().replace("/", "\\").strip("\\").lower()
    item_leaf = norm_item.split("\\")[-1].strip()

    norm_target = str(iter_path or "").strip().replace("/", "\\").strip("\\").lower()
    norm_name = str(iter_name or "").strip().replace("/", "\\").strip("\\").lower()
    target_leaf = norm_target.split("\\")[-1].strip() if norm_target else norm_name

    # 1. Exact normalized path match (e.g. "myproject\26-09" == "myproject\26-09")
    if norm_target and norm_item == norm_target:
        return True

    # 2. Exact leaf segment match (e.g. "26-09" == "26-09")
    if target_leaf and item_leaf == target_leaf:
        return True

    # 3. Iteration name exact match (e.g. "26-09" == "26-09")
    if norm_name and item_leaf == norm_name:
        return True

    # 4. Path boundary matches (e.g. norm_item ends with "\26-09")
    if target_leaf and norm_item.endswith(f"\\{target_leaf}"):
        return True
    if item_leaf and norm_target.endswith(f"\\{item_leaf}"):
        return True

    # 5. Nested iteration path match (item is UNDER iteration path)
    if norm_target and norm_item.startswith(f"{norm_target}\\"):
        return True

    # 6. Check common sprint patterns (e.g. "26-09" in "26-09 (Sep Work)" or "Sprint 1")
    # Strictly extract sprint code token so "26-09" matches "26-09 (Sep Work)",
    # but "26-10" NEVER matches "26-09"!
    item_code_match = re.search(r"(\b\d{2}-\d{2}\b|sprint\s*\d+\b)", item_leaf)
    target_code_match = re.search(r"(\b\d{2}-\d{2}\b|sprint\s*\d+\b)", target_leaf or norm_name)
    if item_code_match and target_code_match:
        return item_code_match.group(1).replace(" ", "") == target_code_match.group(1).replace(" ", "")

    # 7. Check if item_iter_id matches iteration.id
    if item_iter_id is not None and iter_id:
        try:
            if int(item_iter_id) == int(iter_id):
                return True
        except (ValueError, TypeError):
            pass

    return False


def _norm_area(path: Any) -> str:
    return str(path or "").strip().replace("/", "\\").strip("\\").lower()


def parse_team_area_scopes(field_values: dict[str, Any] | None) -> list[tuple[str, bool]]:
    """Turn Azure DevOps teamfieldvalues into [(normalized area path, includes_children)].

    A sprint (iteration) is shared across the project, so the sprint alone cannot say which team's work to show;
    the team's area paths do. An empty result means the scope is unknown and nothing should be filtered.
    """
    if not isinstance(field_values, dict):
        return []
    scopes = [
        (_norm_area(v.get("value")), bool(v.get("includeChildren")))
        for v in field_values.get("values") or []
        if isinstance(v, dict) and v.get("value")
    ]
    if not scopes and field_values.get("defaultValue"):
        scopes = [(_norm_area(field_values["defaultValue"]), False)]
    return scopes


def is_in_team_areas(area_path: Any, scopes: list[tuple[str, bool]]) -> bool:
    """True when the work item's Area Path falls under one of the team's areas (or no scope is known)."""
    if not scopes:
        return True
    area = _norm_area(area_path)
    for base, include_children in scopes:
        if area == base or (include_children and area.startswith(base + "\\")):
            return True
    return False


def evaluate_sprint_work_items(
    raw_items: list[dict[str, Any]],
    org: str,
    project: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse work items from ADO format and evaluate sprint health checks:
    1. Tasks closed but not updated the hours (strictly applicable to Tasks only; 0 is valid, flags blank only).
    2. User story in review for more than 4 working days (excluding Saturday and Sunday).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    parsed_items: list[dict[str, Any]] = []

    total_tasks = 0
    tasks_closed_count = 0
    tasks_closed_without_hours_count = 0

    total_user_stories = 0
    stories_in_review_count = 0
    stories_in_review_stale_count = 0

    flagged_item_ids: list[int] = []

    for item in raw_items:
        fields = item.get("fields") or {}
        item_id = int(item.get("id", 0) or fields.get("System.Id", 0))
        if not item_id:
            continue

        title = str(fields.get("System.Title") or f"Work Item #{item_id}")
        w_type = str(fields.get("System.WorkItemType") or "Task")
        state = str(fields.get("System.State") or "New")

        assigned_obj = fields.get("System.AssignedTo") or {}
        assigned_name = assigned_obj.get("displayName") if isinstance(assigned_obj, dict) else str(assigned_obj) if assigned_obj else None
        assigned_avatar = (
            assigned_obj.get("imageUrl") or (assigned_obj.get("_links", {}).get("avatar", {}).get("href"))
            if isinstance(assigned_obj, dict)
            else None
        )

        remaining_work = safe_float(fields.get("Microsoft.VSTS.Scheduling.RemainingWork"))
        completed_work = safe_float(fields.get("Microsoft.VSTS.Scheduling.CompletedWork"))
        original_estimate = safe_float(fields.get("Microsoft.VSTS.Scheduling.OriginalEstimate"))

        parent_id = fields.get("System.Parent")
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                parent_id = None

        state_change_raw = fields.get("Microsoft.VSTS.Common.StateChangeDate")
        changed_raw = fields.get("System.ChangedDate")
        state_change_dt = parse_ado_date(state_change_raw) or parse_ado_date(changed_raw)

        web_url = item.get("_links", {}).get("html", {}).get("href")
        if not web_url:
            web_url = f"https://dev.azure.com/{quote(org, safe='')}/{quote(project, safe='')}/_workitems/edit/{item_id}"

        # Clean description and condition of satisfaction (acceptance criteria / repro steps)
        raw_desc = fields.get("System.Description")
        raw_ac = fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")
        raw_repro = fields.get("Microsoft.VSTS.TCM.ReproSteps")
        description = strip_html_tags(raw_desc)
        acceptance_criteria = strip_html_tags(raw_ac or raw_repro)
        tags_raw = str(fields.get("System.Tags") or "")
        area_path_raw = str(fields.get("System.AreaPath") or "").strip()
        area_path_leaf = area_path_raw.rsplit("\\", 1)[-1].strip() if area_path_raw else None

        # Check 1: Tasks closed but not updated the hours (strictly applicable for Tasks only)
        # 0 hours is explicitly valid. Only blank (None / empty) completed work is flagged.
        is_task = w_type.lower() == "task"
        is_closed = state.lower() in ("closed", "done", "resolved", "completed")
        is_closed_without_hours = False

        if is_task:
            total_tasks += 1
            if is_closed:
                tasks_closed_count += 1
                # Check: strictly blank only (None / missing). 0 hours is valid!
                is_blank = completed_work is None
                if is_blank:
                    is_closed_without_hours = True
                    tasks_closed_without_hours_count += 1
                    flagged_item_ids.append(item_id)

        # Check 2: User story state in review for more than 4 working days (excluding Sat & Sun)
        is_user_story = w_type.lower() in ("user story", "product backlog item", "requirement", "story")
        is_in_review = state.lower() in ("in review", "review", "ready for review")
        is_stale_in_review = False
        business_days_in_review: int | None = None

        if is_user_story:
            total_user_stories += 1
            if is_in_review:
                stories_in_review_count += 1
                if state_change_dt:
                    business_days_in_review = calculate_business_days(state_change_dt, now)
                    if business_days_in_review > 4:
                        is_stale_in_review = True
                        stories_in_review_stale_count += 1
                        if item_id not in flagged_item_ids:
                            flagged_item_ids.append(item_id)

        # Extract severity & priority for quality gates & defect burden
        severity_raw = fields.get("Microsoft.VSTS.Common.Severity") or fields.get("Severity")
        priority_raw = fields.get("Microsoft.VSTS.Common.Priority") or fields.get("Priority")
        severity = str(severity_raw).strip() if severity_raw else None
        try:
            priority = int(priority_raw) if priority_raw is not None else None
        except (ValueError, TypeError):
            priority = None

        parsed_items.append({
            "id": item_id,
            "title": title,
            "work_item_type": w_type,
            "state": state,
            "assigned_to_name": assigned_name,
            "assigned_to_avatar": assigned_avatar,
            "remaining_work": remaining_work,
            "completed_work": completed_work,
            "original_estimate": original_estimate,
            "parent_id": parent_id,
            "state_change_date": state_change_raw,
            "changed_date": changed_raw,
            "web_url": web_url,
            "business_days_in_review": business_days_in_review,
            "is_closed_without_hours": is_closed_without_hours,
            "is_stale_in_review": is_stale_in_review,
            "description": description or None,
            "acceptance_criteria": acceptance_criteria or None,
            "tags": tags_raw,
            "area_path": area_path_leaf,
            "iteration_path": str(fields.get("System.IterationPath") or "") or None,
            "iteration_id": int(fields.get("System.IterationId")) if fields.get("System.IterationId") is not None else None,
            "severity": severity,
            "priority": priority,
        })

    checks_summary = {
        "total_tasks": total_tasks,
        "tasks_closed_count": tasks_closed_count,
        "tasks_closed_without_hours_count": tasks_closed_without_hours_count,
        "total_user_stories": total_user_stories,
        "stories_in_review_count": stories_in_review_count,
        "stories_in_review_stale_count": stories_in_review_stale_count,
        "flagged_item_ids": flagged_item_ids,
    }

    return parsed_items, checks_summary


FEATURE_PARENT_TYPES = {"feature", "epic"}
UNASSIGNED_STREAM = "Unassigned Work"


def derive_milestone_stream(item: dict[str, Any], parent_lookup: dict[int, tuple[str, str]] | None = None) -> str:
    """Name the workstream a story/bug belongs to, from the team's own backlog structure: the parent
    Feature/Epic title when one exists, otherwise the leaf segment of the Area Path. This has no built-in
    vocabulary, so it names streams the same way for any team regardless of what they actually ship.
    """
    parent_lookup = parent_lookup or {}
    parent_id = item.get("parent_id")
    if parent_id is not None:
        parent = parent_lookup.get(parent_id)
        if parent:
            parent_title, parent_type = parent
            if parent_type.strip().lower() in FEATURE_PARENT_TYPES and parent_title.strip():
                return parent_title.strip()
    area_path = item.get("area_path")
    if area_path:
        return area_path
    return UNASSIGNED_STREAM


def derive_milestone_category(item: dict[str, Any]) -> str:
    """Classify a closed item by its own work item type and tags, never by guessing from English words in
    the title - that only works for the one team whose vocabulary the guesses happened to match.
    """
    if str(item.get("work_item_type", "")).strip().lower() == "bug":
        return "Bug Fix & Quality"
    tags = {t.strip().lower() for t in str(item.get("tags") or "").split(";") if t.strip()}
    if tags & {"tech-debt", "technical-debt", "techdebt", "chore", "refactor", "infrastructure"}:
        return "Technical Enablement"
    return "Feature & Business Value"


def calculate_sprint_milestones(
    parsed_items: list[dict[str, Any]],
    parent_lookup: dict[int, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Calculate milestone achievements and a next-sprint baseline from the work items closed in a sprint.

    Workstreams come from the team's own backlog structure (parent Feature/Epic, falling back to Area Path)
    rather than a fixed vocabulary, so the same logic produces meaningful streams for any team's domain.
    `parent_lookup` maps a parent work item id to (title, work_item_type) for items outside the sprint scope.
    """
    parent_lookup = parent_lookup or {}
    closed_states = {"closed", "done", "completed", "resolved"}
    story_types = {"user story", "product backlog item", "requirement", "feature", "story", "bug"}

    # Map tasks by parent ID to calculate child contributions
    tasks_by_parent: dict[int, list[dict[str, Any]]] = {}
    for item in parsed_items:
        if str(item.get("work_item_type", "")).lower() == "task":
            pid = item.get("parent_id")
            if pid:
                tasks_by_parent.setdefault(pid, []).append(item)

    all_story_items = [
        item for item in parsed_items
        if str(item.get("work_item_type", "")).lower() in story_types
    ]

    closed_story_items = [
        item for item in all_story_items
        if str(item.get("state", "")).lower() in closed_states
    ]

    total_stories = len(all_story_items)
    closed_stories_count = len(closed_story_items)
    open_stories_count = max(0, total_stories - closed_stories_count)
    completion_rate_pct = round((closed_stories_count / total_stories) * 100, 1) if total_stories > 0 else 0.0

    features_delivered_count = 0
    bugs_resolved_count = 0
    achieved_items: list[dict[str, Any]] = []
    key_achievements: list[str] = []
    total_delivered_hours = 0.0

    for item in closed_story_items:
        item_id = item.get("id")
        title = item.get("title", "")
        w_type = str(item.get("work_item_type", "User Story"))
        state = str(item.get("state", "Done"))
        assignee = item.get("assigned_to_name")
        avatar = item.get("assigned_to_avatar")
        web_url = item.get("web_url")
        completed_date = item.get("state_change_date") or item.get("changed_date")
        desc = item.get("description") or ""
        ac = item.get("acceptance_criteria") or ""
        is_bug = w_type.lower() == "bug"

        category = derive_milestone_category(item)
        if is_bug:
            bugs_resolved_count += 1
        else:
            features_delivered_count += 1
        milestone_stream = derive_milestone_stream(item, parent_lookup)

        # Child tasks & hours
        children = tasks_by_parent.get(item_id, [])
        child_tasks_total = len(children)
        child_tasks_closed = sum(1 for c in children if str(c.get("state", "")).lower() in closed_states)

        # Calculate delivered hours for this story (story hours + child task completed hours)
        story_hours = float(item.get("completed_work") or 0.0)
        children_hours = sum(float(c.get("completed_work") or 0.0) for c in children)
        item_delivered_hours = round(story_hours + children_hours, 1)
        total_delivered_hours += item_delivered_hours

        # Issue/achievement text states only what's actually recorded on the item. A blank field is
        # reported as blank, never replaced with a plausible-sounding, domain-specific guess - a guess
        # tuned for one team's work (e.g. alerting) would misrepresent any other team's item.
        issue_summary = desc[:320].strip() if desc.strip() else f"No description was recorded on this {w_type.lower()}."
        achievement_summary = (
            f"Acceptance criteria met: {ac[:300].strip()}" if ac.strip()
            else f"Marked {state} with no acceptance criteria recorded."
        )

        achieved_items.append({
            "id": item_id,
            "title": title,
            "work_item_type": w_type,
            "state": state,
            "assigned_to_name": assignee,
            "assigned_to_avatar": avatar,
            "completed_date": completed_date,
            "web_url": web_url,
            "category": category,
            "milestone_stream": milestone_stream,
            "hours_delivered": item_delivered_hours,
            "child_tasks_total": child_tasks_total,
            "child_tasks_closed": child_tasks_closed,
            "description": desc or None,
            "acceptance_criteria": ac or None,
            "issue_summary": issue_summary,
            "achievement_summary": achievement_summary,
        })

        # Structured milestone highlight statement
        who_str = f"by {assignee}" if assignee else ""
        hours_str = f"({item_delivered_hours}h)" if item_delivered_hours > 0 else ""
        key_achievements.append(f"#{item_id} [{w_type}] {title} {who_str} {hours_str}".strip())

    # If stories had no logged hours, sum all completed tasks in sprint to give accurate sprint work delivered
    if total_delivered_hours == 0:
        all_completed_tasks_hours = sum(
            float(t.get("completed_work") or 0.0)
            for t in parsed_items
            if str(t.get("work_item_type", "")).lower() == "task" and str(t.get("state", "")).lower() in closed_states
        )
        total_delivered_hours = round(all_completed_tasks_hours, 1)

    # Build stream aggregates dynamically from whatever streams the team's own backlog actually produced -
    # never a fixed list, since the set of Features/Epics or Areas differs for every team and every sprint.
    stream_map: dict[str, dict[str, Any]] = {}

    def _stream_bucket(name: str) -> dict[str, Any]:
        return stream_map.setdefault(name, {
            "name": name,
            "total_count": 0,
            "closed_count": 0,
            "delivered_hours": 0.0,
            "completion_pct": 0.0,
            "issues_addressed_count": 0,
            "next_sprint_baseline_target": 0,
            "next_sprint_recommendation": "",
        })

    for it in all_story_items:
        _stream_bucket(derive_milestone_stream(it, parent_lookup))["total_count"] += 1

    for item in achieved_items:
        bucket = _stream_bucket(item["milestone_stream"])
        bucket["closed_count"] += 1
        bucket["delivered_hours"] += item.get("hours_delivered", 0.0)
        bucket["issues_addressed_count"] += 1

    for data in stream_map.values():
        tot, cls = data["total_count"], data["closed_count"]
        data["completion_pct"] = round((cls / tot) * 100, 1) if tot > 0 else (100.0 if cls > 0 else 0.0)
        data["delivered_hours"] = round(data["delivered_hours"], 1)

        # Baseline recommendation from this stream's own velocity: carry forward whatever is still open,
        # or hold/raise capacity if everything planned was delivered. No stream-specific scripted text.
        open_in_stream = max(0, tot - cls)
        data["next_sprint_baseline_target"] = cls if cls > 0 else open_in_stream
        if open_in_stream > 0:
            data["next_sprint_recommendation"] = f"{open_in_stream} item(s) in this stream are still open; carry forward into next sprint."
        elif cls > 0:
            data["next_sprint_recommendation"] = f"All {cls} planned item(s) in this stream were completed; hold or raise capacity next sprint."
        else:
            data["next_sprint_recommendation"] = "No activity in this stream this sprint."

    # Quality signal that works for any team: of the bugs in this sprint's scope, how many were actually
    # resolved. Replaces a metric ("alert stability") that only meant something for one team's domain.
    total_bugs_in_scope = sum(1 for it in all_story_items if str(it.get("work_item_type", "")).lower() == "bug")
    bug_resolution_rate_pct = round((bugs_resolved_count / total_bugs_in_scope) * 100, 1) if total_bugs_in_scope > 0 else 100.0

    # Recommended next-sprint capacity split: this sprint's own delivered-hours mix across streams,
    # not a split prescribed for one team's workflow.
    streams_by_hours = sorted(stream_map.values(), key=lambda d: d["delivered_hours"], reverse=True)
    hours_total = sum(d["delivered_hours"] for d in streams_by_hours)
    if hours_total > 0:
        top_streams = [d for d in streams_by_hours if d["delivered_hours"] > 0][:3]
        capacity_text = ", ".join(f"{round(d['delivered_hours'] * 100 / hours_total)}% {d['name']}" for d in top_streams)
        next_sprint_recommended_capacity = f"Based on this sprint's delivered effort: {capacity_text}."
    else:
        next_sprint_recommended_capacity = "No delivered effort was recorded this sprint to baseline a capacity split."

    # Focus areas: what is actually still open - all carry-over items, not capped at 5
    open_items = [it for it in all_story_items if str(it.get("state", "")).lower() not in closed_states]
    next_sprint_focus_areas = [
        f"Carry forward #{it['id']} [{derive_milestone_stream(it, parent_lookup)}] {it['title']}"
        for it in open_items
    ]
    if not next_sprint_focus_areas:
        next_sprint_focus_areas = ["All planned work this sprint was closed; no carry-over items."]

    graph_data = {
        "streams": list(stream_map.values()),
        "overall_reliability_baseline_pct": completion_rate_pct,
        "bug_resolution_rate_pct": bug_resolution_rate_pct,
        "next_sprint_recommended_capacity": next_sprint_recommended_capacity,
        "next_sprint_focus_areas": next_sprint_focus_areas,
    }

    return {
        "total_stories": total_stories,
        "closed_stories_count": closed_stories_count,
        "open_stories_count": open_stories_count,
        "completion_rate_pct": completion_rate_pct,
        "total_delivered_hours": round(total_delivered_hours, 1),
        "features_delivered_count": features_delivered_count,
        "bugs_resolved_count": bugs_resolved_count,
        "achieved_items": achieved_items,
        "key_achievements": key_achievements,
        "graph_data": graph_data,
    }

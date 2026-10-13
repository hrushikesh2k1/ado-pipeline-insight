"""Work Item Insights: reads a scope's work items, groups them into areas with AI, saves the result and serves it to the page.

A refresh runs in a background thread (a large backlog takes minutes) and reports its progress; the page polls it.
Only items that are new or have changed since the last refresh are sent to the AI, so a refresh stays cheap.
"""
from __future__ import annotations

import logging
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from app.core.config import get_settings
from app.repositories import work_item_insights_repository as store
from app.services.alert_inventory import parse_inventory, summarize_inventory
from app.services.work_item_classifier import (
    NOT_GROUPED,
    area_from_path,
    assign_areas,
    discover_areas,
    flag_alert_work,
)
from app.services.work_item_scope import DEFAULT_MONTHS, collect_scope_items
from core.ado_client import AzureDevOpsClient
from core.openai_client import PipelineRecommendationClient

logger = logging.getLogger(__name__)

_KEPT_FIELDS = ("id", "rev", "type", "title", "state", "state_category", "assigned_to", "created", "closed", "sprint", "area_path")
_NO_AI = ("Azure OpenAI is not configured on this server (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT, plus az login or "
          "AZURE_OPENAI_API_KEY)")

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_ai_client() -> PipelineRecommendationClient | None:
    settings = get_settings()
    if not settings.azure_openai_endpoint or not settings.azure_openai_deployment:
        return None
    try:
        return PipelineRecommendationClient(
            settings.azure_openai_endpoint, settings.azure_openai_deployment, settings.azure_openai_api_version,
            settings.azure_openai_api_key or None,
        )
    except Exception as exc:
        logger.warning("Could not initialise Azure OpenAI for work item insights: %s", exc)
        return None


def describe_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError):
        status = getattr(exc.response, "status_code", None)
        if status in (401, 203):
            return "Azure DevOps did not accept the personal access token (it must be valid and have the Work Items: Read scope)."
        if status == 403:
            return "The personal access token is not allowed to read work items in this project (it needs the Work Items: Read scope)."
        if status == 404:
            return "Azure DevOps could not find this organization or project."
        return f"Azure DevOps returned an error (HTTP {status})."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"The refresh failed unexpectedly ({type(exc).__name__}). The server log has the details."


def guess_bug_types(type_names: list[str]) -> list[str]:
    return [t for t in type_names if "bug" in t.lower() or "defect" in t.lower()]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _short_item(item: dict[str, Any]) -> str:
    return f"#{item.get('id')} {item.get('type')}: {item.get('title')} ({item.get('assigned_to') or 'Unassigned'}, {item.get('area') or NOT_GROUPED})"


def _fallback_executive_summary(scope_label: str, days: int, closed: list[dict[str, Any]], created: list[dict[str, Any]],
                                active: list[dict[str, Any]]) -> str:
    lines = [f"Executive summary for {scope_label} over the last {days} day{'s' if days != 1 else ''}."]
    if closed:
        people = sorted({i.get("assigned_to") or "Unassigned" for i in closed})
        areas = sorted({i.get("area") or NOT_GROUPED for i in closed})
        lines.append(f"The team completed {len(closed)} work item{'s' if len(closed) != 1 else ''} across {len(areas)} area{'s' if len(areas) != 1 else ''}.")
        lines.append("Completed work: " + "; ".join(_short_item(i) for i in closed[:8]) + ("." if len(closed) <= 8 else f"; plus {len(closed) - 8} more."))
        lines.append("People involved: " + ", ".join(people[:10]) + ("." if len(people) <= 10 else f", plus {len(people) - 10} more."))
    else:
        lines.append("No work items in the saved scope were closed during this window.")
    if created:
        lines.append(f"{len(created)} new work item{'s were' if len(created) != 1 else ' was'} created in the same window, including " +
                     "; ".join(_short_item(i) for i in created[:5]) + ("." if len(created) <= 5 else f"; plus {len(created) - 5} more."))
    if active:
        lines.append(f"Current attention: {len(active)} active or resolved work item{'s are' if len(active) != 1 else ' is'} still open in this scope.")
    return "\n\n".join(lines)


class WorkItemInsightsService:
    def __init__(
        self,
        ado_factory: Callable[[str, str], Any] = AzureDevOpsClient,
        ai_factory: Callable[[], Any] = build_ai_client,
    ):
        self._ado = ado_factory
        self._ai = ai_factory

    # ------------------------------------------------------------------ jobs
    @staticmethod
    def status(key: str) -> dict[str, Any]:
        with _jobs_lock:
            return dict(_jobs.get(key) or {"status": "idle", "phase": None, "done": 0, "total": 0, "message": "", "error": None})

    def start_refresh(self, organization: str, project: str, pat: str, *, team: str = "", tag: str = "",
                      months: int = DEFAULT_MONTHS, regroup: bool = False, background: bool = True) -> dict[str, Any]:
        key = store.scope_key(organization, project, team, tag)
        with _jobs_lock:
            running = _jobs.get(key)
            if running and running.get("status") == "running":
                return dict(running)
            _jobs[key] = {"status": "running", "phase": "reading", "done": 0, "total": 0, "message": "Starting",
                          "started_at": now_iso(), "finished_at": None, "error": None}
        args = (key, organization, project, pat, team, tag, months, regroup)
        if background:
            threading.Thread(target=self._run, args=args, daemon=True).start()
        else:
            self._run(*args)
        return self.status(key)

    def _update(self, key: str, **fields: Any) -> None:
        with _jobs_lock:
            if key in _jobs:
                _jobs[key].update(fields)

    def _progress(self, key: str) -> Callable[[str, int, int], None]:
        def report(phase: str, done: int, total: int) -> None:
            if phase == "reading":
                message = "Reading work items from Azure DevOps" + (f" ({done} of {total})" if total else (f" ({done} found)" if done else ""))
            else:
                message = f"Grouping work items with AI ({done} of {total})"
            self._update(key, phase=phase, done=done, total=total, message=message)
        return report

    def _run(self, key: str, organization: str, project: str, pat: str, team: str, tag: str, months: int, regroup: bool) -> None:
        try:
            notes = self.refresh(key, organization, project, pat, team, tag, months, regroup, self._progress(key))
            self._update(key, status="done", phase=None, message="Up to date", finished_at=now_iso(), notes=notes)
        except Exception as exc:
            logger.warning("Work item insights refresh failed: %s", exc, exc_info=not isinstance(exc, (ValueError, requests.HTTPError)))
            self._update(key, status="error", phase=None, message="The refresh failed", error=describe_error(exc), finished_at=now_iso())

    # --------------------------------------------------------------- refresh
    def refresh(self, key: str, organization: str, project: str, pat: str, team: str, tag: str, months: int,
                regroup: bool, progress: Callable[[str, int, int], None]) -> list[str]:
        client = self._ado(organization, pat)
        items = collect_scope_items(client, project, team=team, tag=tag, months=months, progress=progress)

        record = store.get(key) or {}
        prior = {i["id"]: i for i in record.get("items") or []}
        inventory = record.get("inventory")
        with_alert = bool(inventory and inventory.get("alerts"))
        areas: list[dict[str, str]] = record.get("areas") or []
        version = int(record.get("areas_version") or 0)
        had_ai_areas = record.get("area_source") == "ai" and bool(areas)
        notes: list[str] = []

        ai = self._ai()
        mode = "ai"  # ai: assign with the model; keep: model unavailable, keep what is saved; path: group by Area Path
        if ai is None:
            mode = "keep" if had_ai_areas else "path"
            notes.append(f"{_NO_AI}, so work items are {'left as they were grouped' if mode == 'keep' else 'grouped by their Azure DevOps Area Path'}.")
        elif (regroup or not had_ai_areas) and items:
            try:
                progress("grouping", 0, len(items))
                areas = discover_areas(ai, items)
                version += 1
            except Exception as exc:
                logger.warning("Could not discover areas: %s", exc)
                mode = "keep" if had_ai_areas else "path"
                notes.append(f"The AI could not propose areas ({type(exc).__name__}), so work items are "
                             f"{'left as they were grouped' if mode == 'keep' else 'grouped by their Azure DevOps Area Path'}.")

        final: dict[int, dict[str, Any]] = {}
        to_assign: list[dict[str, Any]] = []
        to_flag: list[dict[str, Any]] = []
        for item in items:
            record_item = {k: item[k] for k in _KEPT_FIELDS}
            old = prior.get(item["id"])
            if mode == "path":
                record_item.update(area=area_from_path(item["area_path"]), alert_work=None, areas_version=0)
            elif old and old.get("rev") == item["rev"] and old.get("areas_version") == version and old.get("area") and not old.get("recheck"):
                record_item.update(area=old["area"], alert_work=old.get("alert_work"), areas_version=version, recheck=False)
                if mode == "ai" and with_alert and old.get("alert_work") is None:
                    to_flag.append(item)
            else:
                # An item that was grouped before and has been edited keeps its group until the model answers again: if it does not (or is not
                # available), the earlier group is still the best one and the item is checked again at the next refresh.
                earlier = old if old and old.get("area") and old.get("areas_version") == version else None
                record_item.update(area=earlier["area"] if earlier else None, alert_work=earlier.get("alert_work") if earlier else None,
                                   areas_version=version, recheck=bool(earlier))
                if mode == "ai":
                    to_assign.append(item)
            final[item["id"]] = record_item

        failed = 0
        if to_assign:
            results, missing = assign_areas(ai, areas, to_assign, with_alert=with_alert, progress=progress)
            for item_id, answer in results.items():
                final[item_id].update(area=answer["area"], alert_work=answer["alert_work"], recheck=False)
            failed += len([i for i in missing if not final[i].get("recheck")])
        if to_flag:
            flags, missing = flag_alert_work(ai, to_flag, progress)
            for item_id, flag in flags.items():
                final[item_id]["alert_work"] = flag
            failed += len(missing)
        if failed:
            notes.append(f"{failed} work item(s) could not be processed because the AI did not answer for them. Refresh again to retry them.")
        kept = sum(1 for r in final.values() if r.get("recheck"))
        if kept:
            notes.append(f"{kept} changed work item(s) could not be checked again by the AI and keep their earlier group. Refresh again to check them.")

        store.save(
            key, organization=organization, project=project, team=team, tag=tag, months=months,
            areas=areas, areas_version=version, area_source="area_path" if mode == "path" else "ai",
            items=list(final.values()), notes=notes, refreshed_at=now_iso(),
        )
        return notes

    # ---------------------------------------------------------------- serving
    def snapshot(self, organization: str, project: str, team: str = "", tag: str = "") -> dict[str, Any]:
        key = store.scope_key(organization, project, team, tag)
        record = store.get(key) or {}
        items = []
        for item in record.get("items") or []:
            row = {k: item.get(k) for k in _KEPT_FIELDS if k != "rev"}
            row["area"] = item.get("area") or NOT_GROUPED
            row["alert_work"] = item.get("alert_work")
            items.append(row)
        type_counts: dict[str, int] = {}
        for item in items:
            type_counts[item["type"]] = type_counts.get(item["type"], 0) + 1
        type_names = sorted(type_counts, key=lambda t: (-type_counts[t], t))
        settings = get_settings()
        return {
            "scope": {"organization": organization, "project": project, "team": team, "tag": tag, "months": record.get("months") or DEFAULT_MONTHS},
            "has_data": bool(record.get("refreshed_at")),
            "refreshed_at": record.get("refreshed_at"),
            "area_source": record.get("area_source"),
            "areas": record.get("areas") or [],
            "items": items,
            "types": [{"name": t, "count": type_counts[t]} for t in type_names],
            "bug_types": guess_bug_types(type_names),
            "inventory": summarize_inventory(record.get("inventory")),
            "notes": record.get("notes") or [],
            "ai_configured": bool(settings.azure_openai_endpoint and settings.azure_openai_deployment),
            "job": self.status(key),
        }

    def executive_summary(self, organization: str, project: str, team: str = "", tag: str = "", days: int = 2) -> dict[str, Any]:
        key = store.scope_key(organization, project, team, tag)
        record = store.get(key) or {}
        if not record.get("refreshed_at"):
            raise ValueError("Refresh Work Item Insights first, then generate the executive summary.")

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        items = []
        for item in record.get("items") or []:
            row = {k: item.get(k) for k in _KEPT_FIELDS if k != "rev"}
            row["area"] = item.get("area") or NOT_GROUPED
            row["alert_work"] = item.get("alert_work")
            items.append(row)

        closed = [i for i in items if i.get("state_category") == "completed" and (closed_at := _parse_iso(i.get("closed"))) and closed_at >= since]
        created = [i for i in items if (created_at := _parse_iso(i.get("created"))) and created_at >= since]
        active = [i for i in items if i.get("state_category") in {"inprogress", "resolved"}]
        closed.sort(key=lambda i: i.get("closed") or "", reverse=True)
        created.sort(key=lambda i: i.get("created") or "", reverse=True)

        scope_label = team or (f"tag {tag}" if tag else project)
        fallback = _fallback_executive_summary(scope_label, days, closed, created, active)
        ai = self._ai()
        generated_by_ai = False
        summary = fallback
        if ai is not None:
            try:
                payload = {
                    "scope": {"organization": organization, "project": project, "team": team, "tag": tag},
                    "lookback_days": days,
                    "window_start_utc": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "counts": {"closed": len(closed), "created": len(created), "active_open": len(active)},
                    "closed_items": closed[:25],
                    "created_items": created[:15],
                    "active_items_sample": active[:20],
                }
                resp = ai.client.chat.completions.create(
                    model=ai.deployment,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You write concise executive summaries for Azure DevOps team work. Use only the provided work item data. "
                                "Do not invent causes, dates, people, commitments, percentages, or business impact. "
                                "Write in plain language with these short sections: What got done, New work, Attention needed. "
                                "Mention work item IDs when helpful. Keep it under 180 words."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    max_tokens=450,
                    temperature=0.2,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    summary = text
                    generated_by_ai = True
            except Exception as exc:
                logger.info("Work item executive summary AI call failed; using fallback: %s", type(exc).__name__)

        return {
            "days": days,
            "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generated_by_ai": generated_by_ai,
            "summary": summary,
            "counts": {"closed": len(closed), "created": len(created), "active_open": len(active)},
            "items": {
                "closed": [{"id": i["id"], "title": i["title"], "type": i["type"], "assigned_to": i["assigned_to"], "area": i["area"], "closed": i["closed"]} for i in closed[:10]],
                "created": [{"id": i["id"], "title": i["title"], "type": i["type"], "assigned_to": i["assigned_to"], "area": i["area"], "created": i["created"]} for i in created[:10]],
            },
        }

    # -------------------------------------------------------------- inventory
    def save_inventory(self, organization: str, project: str, team: str, tag: str, filename: str, data: bytes,
                       name_column: str | None = None, category_column: str | None = None) -> dict[str, Any]:
        inventory = parse_inventory(filename, data, name_column, category_column)
        key = store.scope_key(organization, project, team, tag)
        store.save(key, organization=organization, project=project, team=team, tag=tag, inventory=inventory)
        return summarize_inventory(inventory) or {}

    def clear_inventory(self, organization: str, project: str, team: str, tag: str) -> None:
        key = store.scope_key(organization, project, team, tag)
        if store.get(key) is not None:
            store.save(key, inventory=None)

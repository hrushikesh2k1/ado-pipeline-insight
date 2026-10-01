from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

from app.core.config import get_settings
from app.core.db import fetch_all
from app.repositories.release_repository import ReleaseRepository
from app.schemas.connection import (
    ReleaseDefinition,
    ReleaseDimension,
    ReleaseDimensionEvidenceItem,
    ReleaseScorecard,
)
from app.services.board_service import (
    calculate_business_days,
    calculate_sprint_milestones,
    derive_milestone_stream,
)
from core.ado_client import AzureDevOpsClient
from core.openai_client import PipelineRecommendationClient

logger = logging.getLogger(__name__)


def normalize_branch(branch: str | None) -> str:
    """Normalize branch ref for consistent equality comparison without regex or pattern heuristics.
    e.g. 'refs/heads/dev' and 'dev' match, 'refs/heads/release/2.3' and 'release/2.3' match.
    """
    if not branch:
        return ""
    b = str(branch).strip()
    if b.startswith("refs/heads/"):
        b = b[len("refs/heads/"):]
    return b.lower()


def is_high_or_blocker_severity(severity: str | None, priority: int | None = None) -> bool:
    """Determine if a Bug has high severity or blocker impact from Microsoft.VSTS.Common.Severity
    or Microsoft.VSTS.Common.Priority fields. Never infer severity from work item titles.
    """
    if severity:
        s = str(severity).strip().lower()
        if any(keyword in s for keyword in ("1", "critical", "blocker", "urgent", "2 - high", "high")):
            return True
    if priority == 1:
        return True
    return False


# ============================================================================
# Pure Evaluation Functions for the 4 Dimensions
# ============================================================================

def evaluate_delivery_completion(
    parsed_items: list[dict[str, Any]],
    scope_feature_title: str | None = None,
    parent_lookup: dict[int, tuple[str, str]] | None = None,
) -> ReleaseDimension:
    """Dimension 1: Delivery completion.
    Reuses calculate_sprint_milestones logic, scoped to scope_feature_title if provided.
    completion_rate_pct >= 90 -> green, 70-89 -> yellow, < 70 -> red.
    """
    parent_lookup = parent_lookup or {}

    scoped_items = parsed_items
    if scope_feature_title and scope_feature_title.strip():
        req_stream = scope_feature_title.strip().lower()
        scoped_items = [
            it for it in parsed_items
            if derive_milestone_stream(it, parent_lookup).strip().lower() == req_stream
        ]

    milestones = calculate_sprint_milestones(scoped_items, parent_lookup)
    total_stories = int(milestones.get("total_stories", 0))
    closed_stories = int(milestones.get("closed_stories_count", 0))
    completion_pct = float(milestones.get("completion_rate_pct", 0.0))
    achieved = milestones.get("achieved_items", [])

    evidence: list[ReleaseDimensionEvidenceItem] = []
    for it in achieved[:10]:
        evidence.append(ReleaseDimensionEvidenceItem(
            id=it.get("id"),
            title=it.get("title", ""),
            item_type=it.get("work_item_type", "Item"),
            status_or_result=it.get("state", "Done"),
            web_url=it.get("web_url"),
            details=f"Completed {it.get('delivered_hours', 0)} hrs in stream '{it.get('milestone_stream')}'",
        ))

    if total_stories == 0:
        status = "yellow"
        summary = "No planned stories or bugs found in sprint scope for this release."
        score_text = "0% (0 planned)"
    elif completion_pct >= 90.0:
        status = "green"
        summary = f"Delivery milestone is on track with {completion_pct}% completion ({closed_stories} of {total_stories} items closed)."
        score_text = f"{round(completion_pct)}%"
    elif completion_pct >= 70.0:
        status = "yellow"
        summary = f"Delivery progress is moderate at {completion_pct}% completion ({closed_stories} of {total_stories} items closed)."
        score_text = f"{round(completion_pct)}%"
    else:
        status = "red"
        summary = f"Delivery completion is low at {completion_pct}% ({closed_stories} of {total_stories} items closed), falling short of target threshold."
        score_text = f"{round(completion_pct)}%"

    return ReleaseDimension(
        key="delivery_completion",
        name="Delivery Completion",
        status=status,
        score_text=score_text,
        summary=summary,
        evidence_items=evidence,
        metrics={
            "total_stories": total_stories,
            "closed_stories": closed_stories,
            "completion_rate_pct": completion_pct,
            "total_delivered_hours": milestones.get("total_delivered_hours", 0.0),
        },
    )


def evaluate_defect_burden(
    parsed_items: list[dict[str, Any]],
    scope_feature_title: str | None = None,
    parent_lookup: dict[int, tuple[str, str]] | None = None,
) -> ReleaseDimension:
    """Dimension 2: Defect burden.
    Checks open Bug work items in scope.
    Any open Bug with high severity or blocker impact -> red.
    Only medium/low severity open bugs -> yellow.
    None open -> green.
    """
    parent_lookup = parent_lookup or {}
    closed_states = {"closed", "done", "completed", "resolved"}

    scoped_items = parsed_items
    if scope_feature_title and scope_feature_title.strip():
        req_stream = scope_feature_title.strip().lower()
        scoped_items = [
            it for it in parsed_items
            if derive_milestone_stream(it, parent_lookup).strip().lower() == req_stream
        ]

    open_bugs: list[dict[str, Any]] = [
        it for it in scoped_items
        if str(it.get("work_item_type", "")).strip().lower() == "bug"
        and str(it.get("state", "")).strip().lower() not in closed_states
    ]

    blocker_bugs: list[dict[str, Any]] = []
    normal_bugs: list[dict[str, Any]] = []

    for b in open_bugs:
        sev = b.get("severity") or b.get("fields", {}).get("Microsoft.VSTS.Common.Severity")
        prio = b.get("priority")
        if is_high_or_blocker_severity(sev, prio):
            blocker_bugs.append(b)
        else:
            normal_bugs.append(b)

    evidence: list[ReleaseDimensionEvidenceItem] = []
    for b in (blocker_bugs + normal_bugs)[:15]:
        sev_display = str(b.get("severity") or (f"P{b.get('priority')}" if b.get("priority") else "Unspecified"))
        evidence.append(ReleaseDimensionEvidenceItem(
            id=b.get("id"),
            title=b.get("title", ""),
            item_type="Bug",
            status_or_result=str(b.get("state", "Open")),
            severity=sev_display,
            web_url=b.get("web_url"),
            details=f"Assigned to: {b.get('assigned_to_name', 'Unassigned')} | Severity: {sev_display}",
        ))

    if blocker_bugs:
        status = "red"
        ids_str = ", ".join(f"#{b.get('id')}" for b in blocker_bugs[:3])
        summary = f"{len(blocker_bugs)} high-severity or blocker bug(s) open in scope ({ids_str})."
        score_text = f"{len(blocker_bugs)} Blocker(s)"
    elif normal_bugs:
        status = "yellow"
        summary = f"{len(normal_bugs)} open medium/low severity bug(s) remaining in scope."
        score_text = f"{len(normal_bugs)} Open Bug(s)"
    else:
        status = "green"
        summary = "Zero open defects detected in release scope."
        score_text = "0 Defects"

    return ReleaseDimension(
        key="defect_burden",
        name="Defect Burden",
        status=status,
        score_text=score_text,
        summary=summary,
        evidence_items=evidence,
        metrics={
            "total_open_bugs": len(open_bugs),
            "blocker_bugs_count": len(blocker_bugs),
            "normal_bugs_count": len(normal_bugs),
        },
    )


def evaluate_pipeline_health(
    runs: list[dict[str, Any]],
    target_branch: str,
    window_size: int = 10,
) -> ReleaseDimension:
    """Dimension 3: Pipeline health.
    Evaluates pipeline runs on the user-selected target_branch (matching branch names neutrally).
    Red if the single most recent run's result != 'succeeded'.
    Yellow if failure rate over the last window_size runs is elevated (> 15%).
    Green if latest run succeeded and pass rate is healthy.
    """
    target_norm = normalize_branch(target_branch)

    # Filter runs matching target_branch without hardcoded name assumptions
    branch_runs = [
        r for r in runs
        if normalize_branch(r.get("source_branch")) == target_norm
    ]

    evidence: list[ReleaseDimensionEvidenceItem] = []
    for r in branch_runs[:window_size]:
        evidence.append(ReleaseDimensionEvidenceItem(
            id=r.get("run_id"),
            title=f"Run #{r.get('run_id')} ({r.get('pipeline_name') or 'Pipeline'})",
            item_type="Pipeline Run",
            status_or_result=str(r.get("result") or "unknown"),
            details=f"Branch: {r.get('source_branch')} | Started: {str(r.get('start_time') or '')[:19]}",
        ))

    if not branch_runs:
        return ReleaseDimension(
            key="pipeline_health",
            name="Pipeline Health",
            status="yellow",
            score_text="No Runs",
            summary=f"No pipeline executions recorded yet for branch '{target_branch}'.",
            evidence_items=[],
            metrics={"total_runs_evaluated": 0, "failure_rate_pct": 0.0},
        )

    latest_run = branch_runs[0]
    latest_result = str(latest_run.get("result") or "").lower()
    latest_id = latest_run.get("run_id")

    recent_window = branch_runs[:window_size]
    failed_count = sum(1 for r in recent_window if str(r.get("result") or "").lower() != "succeeded")
    failure_rate = (failed_count / len(recent_window)) if recent_window else 0.0
    failure_rate_pct = round(failure_rate * 100, 1)

    if latest_result != "succeeded":
        status = "red"
        summary = f"Most recent pipeline build #{latest_id} failed or did not succeed (result: '{latest_result}')."
        score_text = f"Latest Run Failed (#{latest_id})"
    elif failure_rate > 0.15:
        status = "yellow"
        summary = (
            f"Latest build #{latest_id} passed, but recent failure rate on this branch is elevated "
            f"at {failure_rate_pct}% ({failed_count} of last {len(recent_window)} runs failed)."
        )
        score_text = f"{round(100 - failure_rate_pct)}% Pass Rate"
    else:
        status = "green"
        summary = (
            f"Pipeline is healthy on branch '{target_branch}'. Most recent run #{latest_id} succeeded, "
            f"with a {round(100 - failure_rate_pct)}% pass rate across the last {len(recent_window)} runs."
        )
        score_text = f"{round(100 - failure_rate_pct)}% Pass Rate"

    return ReleaseDimension(
        key="pipeline_health",
        name="Pipeline Health",
        status=status,
        score_text=score_text,
        summary=summary,
        evidence_items=evidence,
        metrics={
            "total_runs_evaluated": len(recent_window),
            "failed_count": failed_count,
            "failure_rate_pct": failure_rate_pct,
            "latest_run_id": latest_id,
            "latest_result": latest_result,
        },
    )


def evaluate_review_backlog(
    pull_requests: list[dict[str, Any]],
    target_branch: str,
    target_ship_date: str | None = None,
    stale_threshold_days: int = 3,
) -> ReleaseDimension:
    """Dimension 4: Review backlog.
    Checks open/draft pull requests whose target branch is target_branch.
    Red if any PR has been open beyond stale_threshold_days (default 3 business days)
    AND target ship date is close (<= 3 calendar days or overdue), or if PR is critically stale (>= 5 business days).
    Yellow if active PRs are open but not yet stale / critical.
    Green if zero PRs are open targeting this branch.
    """
    target_norm = normalize_branch(target_branch)

    matching_prs: list[dict[str, Any]] = []
    for pr in pull_requests:
        status_val = str(pr.get("status") or "").lower()
        if status_val not in ("active", "draft", "open"):
            continue
        pr_target = normalize_branch(pr.get("target_branch") or pr.get("targetRefName"))
        if pr_target == target_norm:
            matching_prs.append(pr)

    now_dt = datetime.now(timezone.utc)
    evidence: list[ReleaseDimensionEvidenceItem] = []
    stale_prs: list[dict[str, Any]] = []
    critically_stale_prs: list[dict[str, Any]] = []

    for pr in matching_prs:
        pr_id = pr.get("id") or pr.get("pullRequestId")
        title = pr.get("title") or "Untitled PR"
        created_str = pr.get("creation_date") or pr.get("creationDate")
        creator = pr.get("created_by_name") or pr.get("createdBy", {}).get("displayName") or "Unknown"
        web_url = pr.get("web_url") or pr.get("_links", {}).get("web", {}).get("href")

        days_open = 0
        if created_str:
            try:
                # Parse ISO date
                clean_dt = created_str.replace("Z", "+00:00")
                parsed_dt = datetime.fromisoformat(clean_dt)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                days_open = calculate_business_days(parsed_dt, now_dt)
            except Exception:
                days_open = 0

        pr["business_days_open"] = days_open
        if days_open >= 5:
            critically_stale_prs.append(pr)
        elif days_open >= stale_threshold_days:
            stale_prs.append(pr)

        evidence.append(ReleaseDimensionEvidenceItem(
            id=pr_id,
            title=f"PR #{pr_id}: {title}",
            item_type="Pull Request",
            status_or_result="Active",
            web_url=web_url,
            details=f"Author: {creator} | Open for {days_open} business days | Target: {pr.get('target_branch') or target_branch}",
        ))

    # Evaluate ship date proximity
    days_to_ship: int | None = None
    ship_date_close = False
    if target_ship_date:
        try:
            target_d = date.fromisoformat(target_ship_date[:10])
            today_d = datetime.now(timezone.utc).date()
            days_to_ship = (target_d - today_d).days
            if days_to_ship <= 3:
                ship_date_close = True
        except Exception:
            pass

    if not matching_prs:
        status = "green"
        score_text = "0 Open PRs"
        summary = f"No open pull requests targeting branch '{target_branch}'. Review backlog is completely clear."
    elif critically_stale_prs or (stale_prs and ship_date_close):
        status = "red"
        stale_count = len(critically_stale_prs) + len(stale_prs)
        score_text = f"{stale_count} Stale PR(s)"
        stale_ids = ", ".join(f"#{p.get('id') or p.get('pullRequestId')}" for p in (critically_stale_prs + stale_prs)[:3])
        if ship_date_close:
            summary = (
                f"{stale_count} pull request(s) open beyond {stale_threshold_days} business days ({stale_ids}) "
                f"with target ship date in {days_to_ship} day(s)."
            )
        else:
            summary = f"{len(critically_stale_prs)} pull request(s) critically stale (>5 business days) awaiting review ({stale_ids})."
    else:
        status = "yellow"
        score_text = f"{len(matching_prs)} Active PR(s)"
        summary = f"{len(matching_prs)} active pull request(s) open targeting '{target_branch}', currently within the review threshold."

    return ReleaseDimension(
        key="review_backlog",
        name="Review Backlog",
        status=status,
        score_text=score_text,
        summary=summary,
        evidence_items=evidence,
        metrics={
            "open_prs_count": len(matching_prs),
            "stale_prs_count": len(stale_prs) + len(critically_stale_prs),
            "days_to_ship": days_to_ship,
        },
    )


def compute_overall_status(dimensions: dict[str, ReleaseDimension]) -> str:
    """PRODUCT DECISION (Strict Rule):
    The overall status is the worst of the four dimensions: 'red' > 'yellow' > 'green'.
    NEVER average them. One red dimension (such as an unresolved blocker bug or failing
    pipeline build) makes the whole release RED, regardless of how good the other three
    dimensions look. Averaging would obscure critical go/no-go blockers.
    """
    for dim in dimensions.values():
        if dim.status == "red":
            return "red"
    for dim in dimensions.values():
        if dim.status == "yellow":
            return "yellow"
    return "green"


# ============================================================================
# Narrative and Recommendation Synthesis
# ============================================================================

def build_recommendations(
    release: ReleaseDefinition,
    dimensions: dict[str, ReleaseDimension],
    overall_status: str,
) -> list[str]:
    recs: list[str] = []
    deliv = dimensions.get("delivery_completion")
    defect = dimensions.get("defect_burden")
    pipe = dimensions.get("pipeline_health")
    review = dimensions.get("review_backlog")

    if defect and defect.status == "red":
        recs.append("Resolve or downgrade all high-severity blocker bugs before authorizing deployment.")
    elif defect and defect.status == "yellow":
        recs.append("Review open medium-severity bugs to verify they do not impact release stability.")

    if pipe and pipe.status == "red":
        latest_id = pipe.metrics.get("latest_run_id")
        recs.append(f"Investigate and fix build failure in pipeline run #{latest_id} on '{release.target_branch}'.")
    elif pipe and pipe.status == "yellow":
        recs.append(f"Monitor branch '{release.target_branch}' build stability; recent failure rate is elevated.")

    if review and review.status == "red":
        recs.append(f"Expedite code reviews for stale pull requests targeting '{release.target_branch}'.")
    elif review and review.status == "yellow":
        recs.append(f"Complete approvals for {review.metrics.get('open_prs_count', 0)} active PR(s) before freeze.")

    if deliv and deliv.status == "red":
        recs.append(f"Sprint completion is below target ({deliv.metrics.get('completion_rate_pct')}%) - de-scope unfinished stories or adjust ship date.")

    if release.target_ship_date:
        try:
            target_d = date.fromisoformat(release.target_ship_date[:10])
            today_d = datetime.now(timezone.utc).date()
            diff = (target_d - today_d).days
            if diff < 0:
                recs.append(f"Release target date ({release.target_ship_date}) has passed by {abs(diff)} day(s).")
            elif diff <= 2:
                recs.append(f"Ship date is imminent in {diff} day(s); immediate sign-off required.")
        except Exception:
            pass

    if overall_status == "green" and not recs:
        recs.append("All four quality dimensions satisfy release criteria. Ready for deployment.")

    return recs


def generate_deterministic_fallback_narrative(
    release: ReleaseDefinition,
    dimensions: dict[str, ReleaseDimension],
    overall_status: str,
) -> str:
    """Build a deterministic, authoritative release narrative grounded strictly
    in the 4 dimensions without external API calls.
    """
    deliv = dimensions.get("delivery_completion")
    defect = dimensions.get("defect_burden")
    pipe = dimensions.get("pipeline_health")
    review = dimensions.get("review_backlog")

    verdict_text = {
        "red": "NOT READY to ship (Status: RED)",
        "yellow": "AT RISK (Status: YELLOW)",
        "green": "READY TO SHIP (Status: GREEN)",
    }.get(overall_status, overall_status.upper())

    parts = [f"Release '{release.name}' on branch '{release.target_branch}' is {verdict_text}."]

    if overall_status == "red":
        reasons = []
        if defect and defect.status == "red":
            reasons.append(f"Defect burden has {defect.metrics.get('blocker_bugs_count', 0)} blocker bug(s) open")
        if pipe and pipe.status == "red":
            reasons.append(f"Pipeline health is failing (latest run #{pipe.metrics.get('latest_run_id')} failed)")
        if review and review.status == "red":
            reasons.append(f"Review backlog has {review.metrics.get('stale_prs_count', 0)} stale pull request(s) open")
        if deliv and deliv.status == "red":
            reasons.append(f"Delivery completion is low at {deliv.metrics.get('completion_rate_pct')}%")
        if reasons:
            parts.append("Key blockers: " + "; ".join(reasons) + ".")
    elif overall_status == "yellow":
        warnings = []
        if deliv and deliv.status == "yellow":
            warnings.append(f"delivery completion is {deliv.metrics.get('completion_rate_pct')}%")
        if defect and defect.status == "yellow":
            warnings.append(f"{defect.metrics.get('normal_bugs_count', 0)} medium/low severity bug(s) remain open")
        if pipe and pipe.status == "yellow":
            warnings.append(f"pipeline failure rate is {pipe.metrics.get('failure_rate_pct')}%")
        if review and review.status == "yellow":
            warnings.append(f"{review.metrics.get('open_prs_count', 0)} pull request(s) are awaiting review")
        if warnings:
            parts.append("Areas requiring attention: " + "; ".join(warnings) + ".")
    else:
        parts.append(
            f"All quality dimensions are healthy. Delivery completion is {deliv.metrics.get('completion_rate_pct', 100)}%, "
            f"zero blocker bugs are open, pipeline builds on '{release.target_branch}' are successful, and the PR review backlog is clear."
        )

    if release.target_ship_date:
        parts.append(f"Target ship date is {release.target_ship_date}.")

    return " ".join(parts)


def generate_scorecard_narrative(
    release: ReleaseDefinition,
    dimensions: dict[str, ReleaseDimension],
    overall_status: str,
) -> tuple[str, bool]:
    """Generate narrative using Azure OpenAI if available, with deterministic fallback.
    The system prompt strictly forbids inventing facts, percentages, or ungrounded claims.
    """
    settings = get_settings()
    fallback = generate_deterministic_fallback_narrative(release, dimensions, overall_status)

    if not settings.azure_openai_endpoint:
        return fallback, False

    try:
        client = PipelineRecommendationClient(
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key or None,
        )

        dim_summaries = []
        for k, d in dimensions.items():
            ev_list = [f"#{ev.id} ({ev.title})" for ev in d.evidence_items[:3]]
            ev_str = f" [Evidence: {', '.join(ev_list)}]" if ev_list else ""
            dim_summaries.append(f"- {d.name} ({d.status.upper()}): {d.summary}{ev_str}")

        prompt = (
            f"Release Definition:\n"
            f"- Name: {release.name}\n"
            f"- Repository: {release.repository_name or release.repository_id or 'Project Repository'}\n"
            f"- Target Branch: {release.target_branch}\n"
            f"- Target Ship Date: {release.target_ship_date or 'Not specified'}\n"
            f"- Scope Feature: {release.scope_feature_title or 'All sprint items'}\n"
            f"- Overall Status: {overall_status.upper()}\n\n"
            f"Evaluated Dimensions:\n" + "\n".join(dim_summaries) + "\n\n"
            f"Write a concise executive release readiness verdict (2-3 sentences max). "
            f"Ground every claim strictly in the dimension data provided above. "
            f"Cite specific work item IDs, pipeline run IDs, or pull request IDs for any blockers or warnings. "
            f"NEVER invent or assume any facts, SLAs, percentages, or domain names not present in the data."
        )

        resp = client.client.chat.completions.create(
            model=client.deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write authoritative, concise software release readiness verdicts strictly grounded "
                        "in the provided telemetry data. You cite literal IDs and metrics and never invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=350,
            temperature=0.2,
        )
        ai_text = resp.choices[0].message.content or ""
        if ai_text.strip():
            return ai_text.strip(), True
    except Exception as e:
        logger.debug("Azure OpenAI scorecard narrative generation failed, using fallback: %s", e)

    return fallback, False


# ============================================================================
# Main Service Class
# ============================================================================

class ReleaseService:
    def __init__(self, repo: ReleaseRepository | None = None):
        self.repo = repo or ReleaseRepository()

    def compute_scorecard(
        self,
        release: ReleaseDefinition,
        pat: str | None = None,
        ado_client: AzureDevOpsClient | None = None,
    ) -> ReleaseScorecard:
        """Fetch all three data sources and compute the live Release Readiness Scorecard."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Fetch Pipeline Telemetry from dbo.pipeline_runs
        pipeline_runs: list[dict[str, Any]] = []
        try:
            if release.pipeline_id:
                sql = """
                    SELECT run_id, pipeline_id, pipeline_name, source_branch, result, start_time, finish_time
                    FROM dbo.pipeline_runs
                    WHERE pipeline_id = ?
                    ORDER BY start_time DESC
                """
                pipeline_runs = fetch_all(sql, (release.pipeline_id,))
            else:
                sql = """
                    SELECT run_id, pipeline_id, pipeline_name, source_branch, result, start_time, finish_time
                    FROM dbo.pipeline_runs
                    WHERE LOWER(organization_name) = LOWER(?) AND LOWER(project_name) = LOWER(?)
                    ORDER BY start_time DESC
                """
                pipeline_runs = fetch_all(sql, (release.organization_name, release.project_name))
        except Exception as e:
            logger.debug("Could not query dbo.pipeline_runs for release: %s", e)

        # 2. Fetch Sprint/Work Item Data from Azure DevOps
        parsed_items: list[dict[str, Any]] = []
        parent_lookup: dict[int, tuple[str, str]] = {}
        all_prs: list[dict[str, Any]] = []

        if ado_client:
            client = ado_client
        else:
            resolved_pat = pat
            if not resolved_pat:
                try:
                    from core.config import get_ado_pat
                    resolved_pat = get_ado_pat(release.organization_name)
                except Exception:
                    resolved_pat = ""
            client = AzureDevOpsClient(release.organization_name, resolved_pat) if resolved_pat else None

        if client:
            try:
                # Get current team iteration & items
                teams = client.list_teams(release.project_name, top=5)
                if teams:
                    team_id = teams[0]["id"]
                    iterations = client.list_team_iterations(release.project_name, team_id)
                    current_iter = next((it for it in iterations if it.get("attributes", {}).get("timeFrame") == "current"), None)
                    if not current_iter and iterations:
                        current_iter = iterations[-1]
                    if current_iter:
                        raw_iter_items = client.get_iteration_work_items(
                            release.project_name, team_id, current_iter["id"]
                        )
                        wi_ids = [w["id"] for w in raw_iter_items.get("work_item_relations", []) if w.get("id")]
                        if not wi_ids:
                            wi_ids = [w["target"]["id"] for w in raw_iter_items.get("work_item_relations", []) if w.get("target", {}).get("id")]
                        if wi_ids:
                            # Batch load work items
                            work_items_raw = client.get_work_items_batch(
                                release.project_name,
                                wi_ids[:200],
                                fields=[
                                    "System.Id",
                                    "System.Title",
                                    "System.WorkItemType",
                                    "System.State",
                                    "System.AssignedTo",
                                    "Microsoft.VSTS.Common.Severity",
                                    "Microsoft.VSTS.Common.Priority",
                                    "Microsoft.VSTS.Scheduling.CompletedWork",
                                    "System.Parent",
                                    "System.AreaPath",
                                    "System.Tags",
                                ],
                            )
                            # Parse into lightweight dicts
                            for w in work_items_raw:
                                f = w.get("fields", {})
                                wid = int(w["id"])
                                parsed_items.append({
                                    "id": wid,
                                    "title": f.get("System.Title", ""),
                                    "work_item_type": f.get("System.WorkItemType", "Story"),
                                    "state": f.get("System.State", "New"),
                                    "severity": f.get("Microsoft.VSTS.Common.Severity"),
                                    "priority": f.get("Microsoft.VSTS.Common.Priority"),
                                    "assigned_to_name": f.get("System.AssignedTo", {}).get("displayName") if isinstance(f.get("System.AssignedTo"), dict) else str(f.get("System.AssignedTo") or ""),
                                    "parent_id": f.get("System.Parent"),
                                    "area_path": f.get("System.AreaPath"),
                                    "tags": f.get("System.Tags"),
                                    "completed_work": f.get("Microsoft.VSTS.Scheduling.CompletedWork", 0.0),
                                    "web_url": w.get("_links", {}).get("html", {}).get("href") or f"https://dev.azure.com/{quote(release.organization_name, safe='')}/{quote(release.project_name, safe='')}/_workitems/edit/{wid}",
                                })
            except Exception as e:
                logger.debug("Could not fetch ADO sprint items for scorecard: %s", e)

            try:
                # If repository_id is set, fetch PRs specifically for this repository
                if release.repository_id:
                    repo_prs = client.list_pull_requests(release.project_name, release.repository_id, status="active")
                    for pr in repo_prs:
                        pr_id = pr.get("pullRequestId")
                        web_url = pr.get("_links", {}).get("web", {}).get("href")
                        if not web_url and release.repository_name:
                            web_url = f"https://dev.azure.com/{quote(release.organization_name, safe='')}/{quote(release.project_name, safe='')}/_git/{quote(release.repository_name, safe='')}/pullrequest/{pr_id}"
                        all_prs.append({
                            "id": pr_id,
                            "title": pr.get("title", ""),
                            "status": pr.get("status", "active"),
                            "target_branch": pr.get("targetRefName", ""),
                            "creation_date": pr.get("creationDate"),
                            "created_by_name": pr.get("createdBy", {}).get("displayName", "Unknown"),
                            "web_url": web_url,
                        })
                else:
                    # Fetch PRs across repositories in the project
                    repos = client.list_repositories(release.project_name)
                    for repo in repos[:5]:
                        repo_id = repo.get("id")
                        if repo_id:
                            repo_prs = client.list_pull_requests(release.project_name, repo_id, status="active")
                            for pr in repo_prs:
                                pr_id = pr.get("pullRequestId")
                                web_url = pr.get("_links", {}).get("web", {}).get("href")
                                if not web_url and repo.get("name"):
                                    web_url = f"https://dev.azure.com/{quote(release.organization_name, safe='')}/{quote(release.project_name, safe='')}/_git/{quote(repo['name'], safe='')}/pullrequest/{pr_id}"
                                all_prs.append({
                                    "id": pr_id,
                                    "title": pr.get("title", ""),
                                    "status": pr.get("status", "active"),
                                    "target_branch": pr.get("targetRefName", ""),
                                    "creation_date": pr.get("creationDate"),
                                    "created_by_name": pr.get("createdBy", {}).get("displayName", "Unknown"),
                                    "web_url": web_url,
                                })
            except Exception as e:
                logger.debug("Could not fetch ADO pull requests for scorecard: %s", e)

        # 3. Evaluate the 4 Dimensions
        dim_deliv = evaluate_delivery_completion(parsed_items, release.scope_feature_title, parent_lookup)
        dim_defect = evaluate_defect_burden(parsed_items, release.scope_feature_title, parent_lookup)
        dim_pipe = evaluate_pipeline_health(pipeline_runs, release.target_branch)
        dim_review = evaluate_review_backlog(all_prs, release.target_branch, release.target_ship_date)

        dimensions: dict[str, ReleaseDimension] = {
            "delivery_completion": dim_deliv,
            "defect_burden": dim_defect,
            "pipeline_health": dim_pipe,
            "review_backlog": dim_review,
        }

        # 4. Compute overall status using Worst-Dimension-Wins rule
        overall_status = compute_overall_status(dimensions)

        # 5. Synthesize AI / Deterministic Narrative & Recommendations
        narrative, is_ai = generate_scorecard_narrative(release, dimensions, overall_status)
        recs = build_recommendations(release, dimensions, overall_status)

        # 6. Snapshot Scorecard to History table
        dimension_statuses = {k: d.status for k, d in dimensions.items()}
        self.repo.record_scorecard_history(
            release_id=release.release_id,
            overall_status=overall_status,
            dimension_statuses=dimension_statuses,
            dimension_data={
                "metrics": {k: d.metrics for k, d in dimensions.items()},
                "scores": {k: d.score_text for k, d in dimensions.items()},
            },
        )

        return ReleaseScorecard(
            release=release,
            overall_status=overall_status,
            computed_at=now_iso,
            dimensions=dimensions,
            ai_narrative=narrative,
            ai_generated=is_ai,
            recommendations=recs,
        )

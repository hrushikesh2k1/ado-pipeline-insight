"""Make every finding factual, complete and non-repetitive before it is shown.

- Severity comes from the measured rates, not from the model's mood.
- Impact states what was measured; it never promises a result ("Eliminates ~30% failures").
- "Deterministic" / "transient" is only claimed when the error text shows it.
- Every finding carries a code block to paste: a real diff, or an example labelled as such.
- The same step failing the same way in several stages (or several steps failing with one root cause) is one finding.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.failure_kind import best_error_line, classify_failure
from app.services.pipeline_yaml import (
    CATEGORY_EXAMPLES,
    DEBUG_EXAMPLE,
    RETRY_EXAMPLE,
    YamlContext,
    clean_snippets,
    ensure_fix_block,
    get_section,
    replace_sections,
    strip_unsupported_claims,
    yaml_fence,
)
from app.services.root_causes import identify_cause

HIGH_FAILURE_PCT = 15.0  # the thresholds that make a finding "high" severity
HIGH_RETRY_PCT = 20.0
MEDIUM_FAILURE_PCT = 5.0
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
_UNSUPPORTED_CLAIM = re.compile(r"deterministic|transient|intermittent|flak", re.IGNORECASE)
MAX_LISTED = 8

Stats = dict[tuple[str, str], dict[str, Any]]


def norm(text: object) -> str:
    return str(text or "").strip().lower()


def task_stats(summary: dict[str, Any]) -> Stats:
    """(stage, task) -> measured numbers and the captured error excerpt, from the telemetry summary."""
    stats: Stats = {}
    for stage in summary.get("stages") or []:
        for task in stage.get("tasks") or []:
            stats[(norm(stage.get("name")), norm(task.get("name")))] = {
                "stage": stage.get("name", "Unknown Stage"), "task": task.get("name", "Unknown Task"),
                "fail": float(task.get("failure_rate_pct", 0) or 0), "retry": float(task.get("retry_rate_pct", 0) or 0),
                "excerpt": str(task.get("error_excerpt") or ""), "avg": float(task.get("avg_duration_s", 0) or 0), "raw": task,
            }
    return stats


def find_stat(stats: Stats, finding: dict[str, Any]) -> dict[str, Any] | None:
    """The measurements a finding is about: its (stage, task), or the task alone when only one stage has that name."""
    found = stats.get((norm(finding.get("stage_name")), norm(finding.get("task_name"))))
    if found:
        return found
    same_task = [s for (_stage, task), s in stats.items() if task == norm(finding.get("task_name"))]
    return same_task[0] if len(same_task) == 1 else None


def severity_for(fail: float, retry: float) -> str:
    if fail >= HIGH_FAILURE_PCT or retry >= HIGH_RETRY_PCT:
        return "high"
    return "medium" if fail >= MEDIUM_FAILURE_PCT else "low"


def impact_kind(excerpt: str, retry: float) -> str:
    """'transient' when the error text or the retry data shows it, 'persistent' when the error text shows a real fault, else 'unknown'."""
    kind = classify_failure(excerpt)
    return "transient" if kind == "transient" or retry > 0 else kind


def measured_impact(fail: float, retry: float, kind: str) -> str:
    """What was measured. No promised reduction, and no claim about retries that the error text does not support."""
    if fail <= 0 < retry:
        return f"This step needed a retry in {retry:g}% of runs in the analysed window; retries absorb transient failures but cost time."
    if kind == "transient":
        return f"Retries can absorb transient failures; this step failed in {fail:g}% of runs in the analysed window."
    if kind == "persistent":
        return f"This step failed in {fail:g}% of runs in the analysed window; fixing the cause removes those failures (retrying would only repeat them)."
    return f"This step failed in {fail:g}% of runs in the analysed window. The captured log does not show the cause, so it is not known whether a retry would help."


def default_fix_block(finding: dict[str, Any], stat: dict[str, Any] | None) -> str:
    """A YAML block to paste when a finding has none: derived from the error for failing steps, a labelled example otherwise."""
    if finding.get("category") == "flaky_step":
        excerpt = (stat or {}).get("excerpt", "")
        cause = identify_cause(excerpt)
        if cause:
            return yaml_fence(cause.yaml_fix)
        if classify_failure(excerpt) == "transient" or (stat or {}).get("retry", 0) > 0:
            return yaml_fence(RETRY_EXAMPLE.format(task=finding.get("task_name") or "<step>"))
        return yaml_fence(DEBUG_EXAMPLE)
    return yaml_fence(CATEGORY_EXAMPLES.get(str(finding.get("category")), CATEGORY_EXAMPLES["other"]))


def adopt_known_causes(findings: list[dict[str, Any]], stats: Stats) -> list[dict[str, Any]]:
    """One cause per card. When the error text shows a cause we recognise, the diagnosis and the remediation are that cause's, not the
    model's: otherwise the model can name a different cause than the YAML block does (an authorization error whose scope holds an unset
    variable was diagnosed as 'missing RBAC role'). The model's wording is kept for causes we do not recognise, and a diff it wrote is
    left for the later check against the real files. The matching YAML block is added afterwards by `ensure_fix_block`."""
    adopted: list[dict[str, Any]] = []
    for finding in findings:
        stat = find_stat(stats, finding)
        cause = identify_cause(stat["excerpt"]) if stat and finding.get("category") == "flaky_step" else None
        text = str(finding.get("recommendation") or "")
        if not cause or "```diff" in text:
            adopted.append(finding)
            continue
        diagnosis = f"Task '{stat['task']}' failed in {stat['fail']:g}% of runs. {cause.diagnosis}" if stat else cause.diagnosis
        adopted.append({**finding, "recommendation": replace_sections(text, diagnosis=diagnosis, remediation=cause.remediation)})
    return adopted


def _unknown_cause_diagnosis(stat: dict[str, Any]) -> str:
    line = best_error_line(stat["excerpt"])
    seen = f"The captured error excerpt shows `{line}`" if line else "No error text was captured"
    return f"Task '{stat['task']}' failed in {stat['fail']:g}% of runs. {seen}; the cause is not visible in it."


def normalize_finding(finding: dict[str, Any], stats: Stats) -> dict[str, Any]:
    """Severity from the numbers, measured impact, no unsupported cause claims, and a code block to paste."""
    stat = find_stat(stats, finding)
    text = clean_snippets(str(finding.get("recommendation") or ""))
    if finding.get("category") != "flaky_step" or not stat:
        return {**finding, "recommendation": ensure_fix_block(text, default_fix_block(finding, stat))}
    kind = classify_failure(stat["excerpt"])
    sections = {"impact": measured_impact(stat["fail"], stat["retry"], impact_kind(stat["excerpt"], stat["retry"]))}
    if kind == "unknown" and stat["retry"] <= 0:
        if _UNSUPPORTED_CLAIM.search(get_section(text, "diagnosis")):
            sections["diagnosis"] = _unknown_cause_diagnosis(stat)
        remediation = get_section(text, "remediation")
        if remediation and strip_unsupported_claims(remediation) != remediation:  # "since the failure is deterministic": the error shows no such thing
            sections["remediation"] = strip_unsupported_claims(remediation)
    text = ensure_fix_block(replace_sections(text, **sections), default_fix_block(finding, stat))
    return {**finding, "severity": severity_for(stat["fail"], stat["retry"]), "recommendation": text}


def _merge_key(stat: dict[str, Any]) -> tuple[str, ...]:
    cause = identify_cause(stat["excerpt"])
    if cause:  # one root cause: merge across steps and stages
        return ("cause", cause.signature)
    line = re.sub(r"\d+", "#", best_error_line(stat["excerpt"]).lower())[:100]
    return ("task", norm(stat["task"]), line)  # no named cause: only the same step failing the same way


def _also_text(others: list[dict[str, Any]], same_step: bool) -> str:
    shown = [(f"'{s['stage']}' ({s['fail']:g}%)" if same_step else f"'{s['task']}' in '{s['stage']}' ({s['fail']:g}%)") for s in others[:MAX_LISTED]]
    more = f" and {len(others) - MAX_LISTED} more" if len(others) > MAX_LISTED else ""
    lead = "The same step fails the same way in" if same_step else "The same error also fails"
    return f"{lead}: {'; '.join(shown)}{more}."


def merge_duplicates(findings: list[dict[str, Any]], stats: Stats) -> tuple[list[dict[str, Any]], int]:
    """One finding per root cause: the worst occurrence is kept and the others are listed in it. Returns (findings, how many were folded in)."""
    groups: dict[tuple[str, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for finding in findings:
        stat = find_stat(stats, finding)
        if finding.get("category") == "flaky_step" and stat:
            groups.setdefault(_merge_key(stat), []).append((finding, stat))
    folded = 0
    replaced: dict[int, dict[str, Any] | None] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        best = max(members, key=lambda m: m[1]["fail"])
        others = [s for f, s in sorted(members, key=lambda m: -m[1]["fail"]) if f is not best[0]]
        note = _also_text(others, same_step=all(norm(s["task"]) == norm(best[1]["task"]) for s in others))
        text = str(best[0].get("recommendation") or "")
        text = replace_sections(text, diagnosis=f"{get_section(text, 'diagnosis')} {note}".strip())
        replaced[id(best[0])] = {**best[0], "recommendation": text, "evidence": f"{best[0].get('evidence', '')} | {note}".strip(" |")}
        for finding, _stat in members:
            if finding is not best[0]:
                replaced[id(finding)] = None
        folded += len(members) - 1
    merged = []
    for finding in findings:
        if id(finding) not in replaced:
            merged.append(finding)
        elif replaced[id(finding)] is not None:
            merged.append(replaced[id(finding)])
    return merged, folded


def adopt_causes(findings: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    return adopt_known_causes(findings, task_stats(summary))


def normalize_findings(findings: list[dict[str, Any]], summary: dict[str, Any], _ctx: YamlContext | None = None) -> tuple[list[dict[str, Any]], int]:
    """Normalise every finding, then merge duplicates. Returns (findings, how many duplicates were folded into another finding)."""
    stats = task_stats(summary)
    return merge_duplicates([normalize_finding(f, stats) for f in findings], stats)


def order_and_cap(findings: list[dict[str, Any]], summary: dict[str, Any], cap: int) -> tuple[list[dict[str, Any]], int]:
    """Worst first: severity, then failure rate, failing steps before other kinds. Returns (findings, how many fell outside the cap)."""
    stats = task_stats(summary)

    def order(finding: dict[str, Any]) -> tuple[int, float, int]:
        stat = find_stat(stats, finding)
        return SEVERITY_RANK.get(str(finding.get("severity")), 3), -(stat["fail"] if stat else 0.0), 0 if finding.get("category") == "flaky_step" else 1

    ordered = sorted(findings, key=order)
    return ordered[:cap], max(0, len(ordered) - cap)

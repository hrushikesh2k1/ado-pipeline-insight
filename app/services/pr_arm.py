"""ARM templates that define Azure Monitor alerts, in a pull request: what each alert means before and after the change.

A change to an alert is mostly a change to a few numbers and one long query inside a JSON string. Read as raw JSON lines, a
threshold of 3 instead of 0 or a window of 15 instead of 5 minutes looks like any other edit. So the reviewer is also given each
alert in plain words (when it fires, how often, over what window, who is notified) with its query laid out over several lines,
and a list of exactly what changed. The facts come from the same reader the IRP feature uses; nothing here is guessed.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.alert_facts import SEVERITY_NAMES, alerts_in, human_duration

ARM_LANGUAGE = "ARM template"
ARM_LINE_WIDTH = 20000  # an alert's query is one long line in the JSON (a shared query variable can pass 4,000 characters); the reviewer must see all of it
MAX_QUERY_CHARS = 12000
MAX_CONTEXT_CHARS = 40000

_SCHEMA = re.compile(r"schema\.management\.azure\.com/schemas/[^\"]*/(deploymentTemplate|deploymentParameters|subscriptionDeploymentTemplate|managementGroupDeploymentTemplate|tenantDeploymentTemplate)\.json", re.IGNORECASE)
_AZURE_TYPE = re.compile(r"\"type\"\s*:\s*\"Microsoft\.[A-Za-z]+/", re.IGNORECASE)


def is_arm_template(text: str | None) -> bool:
    """True for an ARM template or parameter file: it names the ARM schema, or has resources of Microsoft types with an apiVersion."""
    body = text or ""
    return bool(_SCHEMA.search(body) or ('"resources"' in body and '"apiVersion"' in body and _AZURE_TYPE.search(body)))


def _show(value: Any) -> str:
    if value is None or value == "":
        return "not set"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "none"
    return str(value)


def _query(alert: dict[str, Any]) -> str:
    return str(alert.get("query") or "").strip()


def _laid_out(query: str, indent: str = "      ") -> str:
    clipped = query if len(query) <= MAX_QUERY_CHARS else query[:MAX_QUERY_CHARS] + "\n... (the rest of the query is cut)"
    return "\n".join(indent + line for line in clipped.splitlines())


def _same_query(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _kind(alert: dict[str, Any]) -> str:
    if alert.get("type") == "metric":
        return "metric alert"
    if alert.get("legacy"):
        return f"log alert (older {alert.get('api_version') or '2018-04-16'} format)"
    return f"log alert (kind {alert.get('kind') or 'LogAlert'})"


def _severity(alert: dict[str, Any]) -> str:
    value = alert.get("severity")
    if value is None:
        return "severity not set"
    # Microsoft documents "0 is the most severe" for the newer format only
    return f"severity {value} ({SEVERITY_NAMES.get(value, 'unknown')})" if alert.get("legacy") else f"severity {value} ({SEVERITY_NAMES.get(value, 'unknown')}; 0 is the most severe)"


def describe(alert: dict[str, Any], number: int) -> str:
    """One alert in plain words, with its query over several lines."""
    lines = [f"{number}. \"{alert.get('name')}\": {_kind(alert)}, {_severity(alert)}, {'disabled' if alert.get('enabled') is False else 'enabled'}"]
    lines.append(f"   Fires when {alert.get('condition_sentence')}.")
    frequency, window = alert.get("evaluation_frequency"), alert.get("window_size")
    if frequency or window:
        lines.append(f"   Evaluated every {human_duration(frequency) or 'an interval that is not set'} over a window of {human_duration(window) or 'a size that is not set'}.")
    lines.append(f"   Scope: {_show(alert.get('scopes'))}")
    groups = alert.get("action_groups") or []
    lines.append("   Action groups: " + (", ".join(groups) if groups else "none are set in this template, so nobody is notified when it fires"))
    extras = [f"{label}: {_show(alert.get(key))}" for label, key in (("autoMitigate", "auto_mitigate"), ("muteActionsDuration", "mute_actions_duration"), ("overrideQueryTimeRange", "override_query_time_range"), ("throttlingInMin", "throttle_minutes")) if alert.get(key) is not None]
    if extras:
        lines.append("   " + "; ".join(extras))
    if _query(alert):
        lines += ["   Query:", _laid_out(_query(alert))]
    return "\n".join(lines)


def _fields(alert: dict[str, Any]) -> dict[str, str]:
    return {
        "enabled": _show(alert.get("enabled")), "severity": _show(alert.get("severity")),
        "evaluation frequency": _show(alert.get("evaluation_frequency")), "window size": _show(alert.get("window_size")),
        "condition": _show(alert.get("condition_sentence")), "scope": _show(alert.get("scopes")),
        "action groups": _show(alert.get("action_groups")), "autoMitigate": _show(alert.get("auto_mitigate")),
        "muteActionsDuration": _show(alert.get("mute_actions_duration")), "overrideQueryTimeRange": _show(alert.get("override_query_time_range")),
        "throttlingInMin": _show(alert.get("throttle_minutes")),
    }


def _key(alert: dict[str, Any]) -> str:
    return str(alert.get("resource_name") or alert.get("name") or "")


def _changes(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[str]:
    before = {_key(a): a for a in old}
    after = {_key(a): a for a in new}
    lines: list[str] = []
    for key, alert in after.items():
        previous = before.get(key)
        if previous is None:
            lines.append(f"- New alert \"{alert.get('name')}\" (added by this change).")
            continue
        was, now = _fields(previous), _fields(alert)
        changed = [f"{name}: {was[name]} -> {now[name]}" for name in now if was[name] != now[name]]
        query_changed = not _same_query(_query(previous), _query(alert))
        if query_changed:
            changed.append("the query changed (the query before the change is shown below)")
        if changed:
            lines.append(f"- \"{alert.get('name')}\": " + "; ".join(changed) + ".")
        if query_changed and _query(previous):
            lines += ["  Query before the change:", _laid_out(_query(previous))]
    lines += [f"- Alert \"{alert.get('name')}\" was removed by this change." for key, alert in before.items() if key not in after]
    return lines or ["- No alert rule changed: only other parts of the template changed."]


def arm_context(old_text: str | None, new_text: str) -> str:
    """The alerts in a changed template, in plain words, and what changed in them. Empty text when there is nothing to add."""
    new_alerts, problem = alerts_in(new_text)
    if problem:
        return f"The template is {problem} after this change, so it cannot be deployed as it is."
    old_alerts, old_problem = alerts_in(old_text) if (old_text or "").strip() else ([], None)
    if not new_alerts and not old_alerts:
        return "No Azure Monitor alert rule (scheduledQueryRules or metricAlerts) is defined in this template."

    parts: list[str] = []
    if new_alerts:
        parts.append("ALERT RULES IN THIS TEMPLATE AFTER THE CHANGE (read from the template; <name> means the template gives no value):\n" + "\n".join(describe(a, n) for n, a in enumerate(new_alerts, 1)))
    if old_problem:
        parts.append("The earlier version of the template could not be read, so what changed in the alerts is not listed.")
    elif (old_text or "").strip():
        parts.append("WHAT CHANGED IN THE ALERT RULES:\n" + "\n".join(_changes(old_alerts, new_alerts)))
    else:
        parts.append("This template is new: every alert in it is new.")
    text = "\n\n".join(parts)
    return text if len(text) <= MAX_CONTEXT_CHARS else text[:MAX_CONTEXT_CHARS] + "\n... (the rest is cut)"

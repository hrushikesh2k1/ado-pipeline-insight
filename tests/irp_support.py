"""A pretend model for the case-by-case IRP writer, plus the data it is given."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from app.services.alert_facts import read_alert

FIXTURES = Path(__file__).parent / "fixtures" / "irp"

EXAMPLE = """# VPN - Tunnel disconnected

# Alert Details

| **Alert** | VPN - Tunnel disconnected |
| --- | --- |
| **Description** | *This alert is designed to trigger when/if a tunnel drops, deployed in Production.* |
| **Severity** | Critical |
| **Source** | Log |
| **Root Cause** | - **Case 1 : ** PSK mismatch |
| **Product** | Common |

# Prerequisites

- Reader role on the resource group

# Remediation Steps

| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |
| --- | --- | --- |
| Check the connection status | Run in Azure Cloud Shell: `az network vpn-connection list -g "rg" -o table` | Status is **Connected** |

# Post-Incident Analysis

- not wanted
"""

SINGLE_PASS = """# VPN - Tunnel disconnected

# Alert Details

| **Alert** | VPN - Tunnel disconnected |
| --- | --- |
| **Severity** | Critical |

# Prerequisites

- Reader role

# Remediation Steps

| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |
| --- | --- | --- |
| Check status | Run: `az network vpn-connection list` | Connected |
"""

CASES = [
    {"name": "IPsec Phase 2 tunnel dropped", "signal": "Message mentions Phase 2 for the connection"},
    {"name": "VPN connection deleted", "signal": "the connection resource is missing"},
    {"name": "Shared key (PSK) mismatch", "signal": "IKE authentication failures"},
]


def alert_data(**over: Any) -> dict[str, Any]:
    data = {
        "alert_name": "VPN - Tunnel disconnected", "cvrd": "", "alert_output_columns": "", "arm_template_context": "", "alert_details": "",
        "target_resource": "<ResourceName>", "severity": "Sev0 (Critical)", "trigger_condition": "Metric threshold breached for > 5 minutes",
        "owning_team": "Cloud Network Operations", "environment": "Production", "irp_template": "", "irp_example": "", "additional_notes": "",
    }
    data.update(over)
    return data


def vpn_facts() -> dict[str, Any]:
    return read_alert((FIXTURES / "vpn_log_alert.arm.json").read_text(encoding="utf-8"))


def action(kind: str, text: str, command: str = "", where: str = "Azure Cloud Shell", changes: bool = False) -> dict[str, Any]:
    return {"kind": kind, "text": text, "command": command, "where": where, "changes_something": changes}


def good_case_row(name: str, fix_command: str = "az network vpn-connection shared-key update --connection-name <ConnectionName> --resource-group <ResourceGroup> --value <NewKey>") -> dict[str, Any]:
    return {
        "step": "ignored",
        "actions": [
            action("diagnose", f"Confirm {name}", "AzureDiagnostics | where Category == \"TunnelDiagnosticLog\" | where Message has \"Phase 2\"", "Log Analytics"),
            action("fix", "Restore the setting", fix_command, changes=True),
            action("verify", "Check the tunnel is up", "az network vpn-connection show --name <ConnectionName> --resource-group <ResourceGroup> --query connectionStatus"),
            action("fallback", "If it stays down, repeat the change on the on-premises device", "", "the on-premises device"),
        ],
        "outcome": "Connection status is Connected",
    }


FRAME = {
    "alert_details": [
        {"label": "Alert", "value": "model value"}, {"label": "Description", "value": "*This alert is designed to trigger when/if a tunnel disconnects, deployed in Production.*"},
        {"label": "Severity", "value": "Warning"}, {"label": "Source", "value": "Metric"}, {"label": "Root Cause", "value": "model root cause"},
        {"label": "Product", "value": "Microsoft.Network/virtualNetworkGateways"},
    ],
    "prerequisites": ["Network Contributor role on the resource group", "Azure Cloud Shell"],
    "triage_rows": [
        {"step": "Check the connection status", "actions": [action("diagnose", "List connections", "az network vpn-connection list --resource-group <ResourceGroup> -o table")], "outcome": "Status is Connected"},
        {"step": "Find the case", "actions": [action("diagnose", "Run the alert query for the last hour", "AzureDiagnostics | where Category == \"TunnelDiagnosticLog\" | take 20", "Log Analytics")], "outcome": "Go to the case row that matches the message"},
    ],
    "closing_rows": [
        {"step": "Confirm the alert stops", "actions": [action("verify", "Watch the alert rule in Azure Monitor", "", "Azure Portal")], "outcome": "The alert is resolved"},
        {"step": "Escalate if it persists", "actions": [action("escalate", "Page the Cloud Network Operations on-call", "", "")], "outcome": "The team has the query results"},
    ],
}


class FakeIrpModel:
    """Answers the three kinds of prompt the writer sends. Override `cases`, `frame` or `case_row` to make it misbehave."""

    def __init__(self, cases=None, frame=None, case_row: Callable[[str, int], Any] | None = None, single_pass: str | None = None,
                 review: Callable[[int, int], Any] | None = None):
        self.deployment = "fake"
        # review(number of cases, how many reviews so far) -> the answer; by default every fix is found to change what the alert measures
        self.review = review or (lambda cases, nth: {"cases": [{"number": n, "fixes_the_alert": True, "reason": "ok"} for n in range(1, cases + 1)], "overlaps": [], "symptom_cases": []})
        self._reviews = 0
        self.single_pass = single_pass if single_pass is not None else SINGLE_PASS
        self.cases = CASES if cases is None else cases
        self.frame = FRAME if frame is None else frame
        self.case_row = case_row or (lambda name, attempt: good_case_row(name))
        self.calls: list[tuple[str, str]] = []
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    def _create(self, model: str, messages: list[dict[str, str]], temperature: float = 0, response_format: Any = None) -> Any:
        system, user = messages[0]["content"], messages[1]["content"]
        with self._lock:
            self.calls.append((system, user))
        if system.startswith("You are a Principal Site Reliability Engineer. You are given the facts"):
            body: Any = {"cases": self.cases}
        elif system.startswith("You write the frame"):
            body = self.frame
        elif system.startswith("You review the root-cause rows"):
            import re as _re
            with self._lock:
                self._reviews += 1
                nth = self._reviews
            body = self.review(len(_re.findall(r"^Case \d+:", user, _re.M)), nth)
            if isinstance(body, Exception):
                raise body
        elif system.startswith("You are a Principal Cloud Site Reliability Engineer writing an Incident Response Plan"):
            body = self.single_pass  # the older, one-call writer
        else:
            name = re.search(r"### WRITE THE ROW FOR THIS CASE:\n(.+)", user).group(1).strip()
            with self._lock:
                self._attempts[name] = self._attempts.get(name, 0) + 1
                attempt = self._attempts[name]
            body = self.case_row(name, attempt)
            if isinstance(body, Exception):
                raise body
        text = body if isinstance(body, str) else json.dumps(body)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def calls_of(self, kind: str) -> list[tuple[str, str]]:
        marks = {"cases": "You are a Principal Site Reliability Engineer. You are given the facts", "frame": "You write the frame", "case": "You write ONE row", "review": "You review the root-cause rows"}
        return [c for c in self.calls if c[0].startswith(marks[kind])]

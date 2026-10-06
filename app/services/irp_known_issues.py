"""Commands and queries that are known to be wrong, checked in every generated IRP.

Each rule is a problem somebody verified, with the documentation that shows it. The list is meant to grow: when QA finds a command that
does not work, add a rule here and no IRP can ship with it again. Rules are matched against the text of each command or query.
"""
from __future__ import annotations

import re
from typing import Any

# severity: "fail" = the command is wrong; "warn" = it needs a check by whoever tests it.
KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "id": "vpn-log-category",
        "pattern": r"VpnGatewayDiagnosticLog",
        "severity": "fail",
        "message": "VpnGatewayDiagnosticLog is not a log category of VPN Gateway. Microsoft documents GatewayDiagnosticLog, IKEDiagnosticLog, "
                   "RouteDiagnosticLog and TunnelDiagnosticLog (TunnelDiagnosticLog holds tunnel connect and disconnect events).",
        "doc": "https://learn.microsoft.com/en-us/azure/vpn-gateway/monitor-vpn-gateway-reference",
    },
    {
        "id": "vpn-shared-key-show",
        "pattern": r"az\s+network\s+vpn-connection\s+show\b[^|\n]*sharedKey",
        "severity": "warn",
        "message": "Microsoft documents `az network vpn-connection shared-key show --connection-name <name> --resource-group <group>` for reading a "
                   "connection's shared key (and `shared-key update --value` to change it). Check that `vpn-connection show` returns it.",
        "doc": "https://learn.microsoft.com/en-us/cli/azure/network/vpn-connection/shared-key",
    },
]

_COMPILED = [(rule, re.compile(rule["pattern"], re.IGNORECASE)) for rule in KNOWN_ISSUES]


def check_known_issues(text: str) -> list[dict[str, Any]]:
    """The rules that match this command or query."""
    return [
        {"id": rule["id"], "severity": rule["severity"], "message": rule["message"], "doc": rule["doc"]}
        for rule, pattern in _COMPILED
        if pattern.search(text or "")
    ]

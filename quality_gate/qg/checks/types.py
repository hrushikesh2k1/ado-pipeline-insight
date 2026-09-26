from __future__ import annotations

import re

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP, WARN
from qg.util import GATE_DIR, existing, module_available, py, rel

ID, NAME, CATEGORY = "types", "Type checking (mypy)", "Code quality"
WHAT = "Verifies type hints are consistent, catching None-handling and wrong-argument bugs before they reach production."


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT, blocking=cfg["types"]["blocking"])
    if not module_available("mypy"):
        res.status, res.summary = SKIP, "mypy is not installed (pip install -r quality_gate/requirements.txt)"
        return res
    targets = existing(["app", "core"])
    r = py("-m", "mypy", *targets, "--ignore-missing-imports", "--no-error-summary", "--show-error-codes",
           "--no-color-output", "--cache-dir", str(GATE_DIR / "reports" / "raw" / ".mypy_cache"), timeout=600)
    for line in r.stdout.splitlines():
        m = re.match(r"(.+?):(\d+): (error|note): (.+)", line)
        if m and m.group(3) == "error":
            res.findings.append(Finding("low", m.group(4), f"{rel(m.group(1))}:{m.group(2)}", "", "mypy"))
    res.metrics = {"type errors": len(res.findings)}
    if res.findings:
        res.status = FAIL if res.blocking else WARN
        res.summary = f"{len(res.findings)} type error(s)"
    else:
        res.status, res.summary = PASS, "no type errors"
    return res

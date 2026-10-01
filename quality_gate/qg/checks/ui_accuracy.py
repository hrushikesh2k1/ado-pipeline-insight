from __future__ import annotations

import json
import os
import shutil

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP
from qg.util import REPO_ROOT, WORK_DIR, parse_json, run

ID, NAME, CATEGORY = "ui_accuracy", "Dashboard accuracy in a real browser (Playwright)", "Reliability"
WHAT = ("Opens the deployed dashboard in headless Chromium and checks that every summary card, the trend tab counts, the Recent Runs "
        "rows (order, build number, pipeline, result, duration) and the run detail drawer show exactly what the API returned to the page.")


def _walk(suite: dict, path: str = ""):
    title = f"{path} > {suite['title']}".strip(" >") if suite.get("title") else path
    for spec in suite.get("specs", []):
        yield f"{title} > {spec['title']}".strip(" >"), spec
    for child in suite.get("suites", []):
        yield from _walk(child, title)


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    frontend = REPO_ROOT / "frontend"
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    base = os.environ.get("QG_BASE_URL") or cfg["functional"].get("base_url", "")
    if not base:
        res.status, res.summary = SKIP, "no base_url configured in quality_gate.toml [functional]"
        return res
    if not npx or not (frontend / "node_modules" / "@playwright").exists():
        res.status, res.summary = SKIP, "Node/Playwright not installed (cd frontend && npm ci && npx playwright install chromium)"
        return res
    r = run([npx, "playwright", "test", "accuracy.spec.ts", "--reporter=json"], cwd=frontend, timeout=900,
            env={"PLAYWRIGHT_BASE_URL": base, "CI": ""})
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "ui_accuracy.json").write_text(r.stdout or "", encoding="utf-8")
    data = parse_json(r.stdout, None)
    if not data:
        res.status, res.summary = FAIL, f"Playwright produced no results: {(r.stderr or r.stdout)[-300:]}"
        return res

    rows, failed, skipped = [], 0, 0
    for title, spec in (item for s in data.get("suites", []) for item in _walk(s)):
        tests = spec.get("tests", [])
        result = tests[0]["results"][-1] if tests and tests[0].get("results") else {}
        status = result.get("status", "skipped")
        state = {"passed": "pass", "skipped": "not run"}.get(status, "FAIL")
        rows.append({"result": state, "severity": "high", "scenario": spec["title"], "area": "Dashboard UI", "duration s": round(result.get("duration", 0) / 1000, 1)})
        if state == "FAIL":
            failed += 1
            message = (result.get("error", {}).get("message") or "").splitlines()
            res.findings.append(Finding("high", spec["title"], "frontend/playwright/tests/accuracy.spec.ts", " ".join(message[:2])[:400], "ui-accuracy",
                                        "The screen shows something different from the API response; check frontend/src/App.tsx."))
        skipped += state == "not run"
    res.tables["Every dashboard scenario"] = rows
    res.metrics = {"scenarios": len(rows), "passed": len(rows) - failed - skipped, "failed": failed}
    if failed:
        res.status, res.summary = FAIL, f"{failed} of {len(rows)} dashboard scenarios show data that differs from the API"
    elif not rows or skipped == len(rows):
        res.status, res.summary = SKIP, "no dashboard scenario ran"
    else:
        res.status, res.summary = PASS, f"all {len(rows)} dashboard scenarios match the API responses"
    return res

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP, WARN
from qg.util import GATE_DIR, REPO_ROOT, WORK_DIR, module_available, parse_json, py, rel

ID, NAME, CATEGORY = "tests", "Unit tests and code coverage", "Reliability"
WHAT = ("Runs the project's own test suite and measures which lines and branches of production code the tests actually execute. "
        "Untested code is where regressions and security bugs hide.")

COVERAGE_RC = GATE_DIR / "coveragerc"


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not (module_available("pytest") and module_available("pytest_cov")):
        res.status, res.summary = SKIP, "pytest / pytest-cov not installed (pip install -r quality_gate/requirements.txt)"
        return res
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    junit, cov_json = WORK_DIR / "unit.xml", WORK_DIR / "coverage.json"
    for p in (junit, cov_json):
        p.unlink(missing_ok=True)

    cov_args = [f"--cov={s}" for s in cfg["coverage"]["sources"] if (REPO_ROOT / s).exists() or (REPO_ROOT / f"{s}.py").exists()]
    ignores = [f"--ignore={p}" for p in cfg["scope"]["unit_tests_ignore"]]
    unit_data, security_data, merged = WORK_DIR / ".coverage.unit", WORK_DIR / ".coverage.security", WORK_DIR / ".coverage.all"
    unit_data.unlink(missing_ok=True)
    r = py("-m", "pytest", cfg["scope"]["unit_tests"], *ignores, *cov_args, "--cov-branch", f"--cov-config={COVERAGE_RC}",
           "--cov-report=", f"--junitxml={junit}", "-q", "-p", "no:cacheprovider", timeout=1200, env={"COVERAGE_FILE": str(unit_data)})
    merged.unlink(missing_ok=True)
    inputs = [str(x) for x in (unit_data, security_data) if x.exists()]
    if inputs:
        py("-m", "coverage", "combine", "--keep", f"--data-file={merged}", f"--rcfile={COVERAGE_RC}", *inputs)
        py("-m", "coverage", "json", f"--data-file={merged}", f"--rcfile={COVERAGE_RC}", "-o", str(cov_json))

    passed = failed = skipped = 0
    if junit.exists():
        root = ET.parse(junit).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is not None:
            total = int(suite.get("tests", 0))
            failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
            skipped = int(suite.get("skipped", 0))
            passed = total - failed - skipped
        for case in root.iter("testcase"):
            bad = case.find("failure") if case.find("failure") is not None else case.find("error")
            if bad is not None:
                res.findings.append(Finding("high", f"Test failed: {case.get('name')}", case.get("classname", "").replace(".", "/") + ".py",
                                            (bad.get("message") or "")[:300], "unit-test", "Fix the code or the test; a red test blocks the gate."))
    else:
        res.status, res.summary = FAIL, f"pytest did not produce results: {(r.stderr or r.stdout)[-300:]}"
        return res

    cov = parse_json(cov_json.read_text(encoding="utf-8") if cov_json.exists() else "", {}) or {}
    totals = cov.get("totals", {})
    pct = round(totals.get("percent_covered", 0.0), 1)
    rows = []
    for path, info in cov.get("files", {}).items():
        s = info["summary"]
        rows.append({"file": rel(path), "statements": s["num_statements"], "missed": s["missing_lines"],
                     "coverage %": round(s["percent_covered"], 1), "uncovered lines": _ranges(info.get("missing_lines", []))})
    rows.sort(key=lambda x: x["coverage %"])
    res.tables["Coverage by file (lowest first)"] = rows
    res.metrics = {"tests passed": passed, "tests failed": failed, "tests skipped": skipped, "coverage % (unit + attack tests)": pct,
                   "statements": totals.get("num_statements", 0), "branches": totals.get("num_branches", 0)}
    fail_under, warn_under = cfg["coverage"]["fail_under"], cfg["coverage"]["warn_under"]
    if failed:
        res.status, res.summary = FAIL, f"{failed} test(s) failing, {passed} passing, coverage {pct}%"
    elif pct < fail_under:
        res.status, res.summary = FAIL, f"coverage {pct}% is below the {fail_under}% minimum ({passed} tests passing)"
        res.findings.append(Finding("medium", f"Coverage {pct}% < required {fail_under}%", "", "", "coverage", "Add tests for the lowest-covered files below."))
    elif pct < warn_under:
        res.status, res.summary = WARN, f"{passed} tests passing; coverage {pct}% (target {warn_under}%)"
    else:
        res.status, res.summary = PASS, f"{passed} tests passing; coverage {pct}%"
    return res


def _ranges(nums: list[int]) -> str:
    if not nums:
        return ""
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n != prev + 1:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = n
        prev = n
    out.append(f"{start}-{prev}" if start != prev else str(start))
    text = ", ".join(out)
    return text if len(text) < 90 else text[:87] + "..."

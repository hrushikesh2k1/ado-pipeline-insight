from __future__ import annotations

import xml.etree.ElementTree as ET

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP
from qg.util import GATE_DIR, REPO_ROOT, WORK_DIR, module_available, py

ID, NAME, CATEGORY = "api_security", "Application security tests (attack simulation)", "Security"
WHAT = ("Starts the real API in-process and attacks it the way a hostile client would: SQL-injection payloads, path/URL "
        "injection in organization/project names, oversized and malformed input, error messages that leak secrets, missing "
        "security headers, permissive CORS and exposed API docs. It proves the code's own defences work; whether the deployed site requires "
        "a login is a live Azure setting and is verified by the Azure check, not here.")


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not module_available("pytest") or not module_available("fastapi"):
        res.status, res.summary = SKIP, "pytest/fastapi missing; install requirements.txt and quality_gate/requirements.txt"
        return res
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    junit = WORK_DIR / "security_tests.xml"
    junit.unlink(missing_ok=True)
    sources = [s for s in cfg["coverage"]["sources"] if (REPO_ROOT / s).exists() or (REPO_ROOT / f"{s}.py").exists()]
    cov_file = WORK_DIR / ".coverage.security"
    cov_file.unlink(missing_ok=True)
    r = py("-m", "pytest", str(GATE_DIR / "security_tests"), f"--junitxml={junit}", "-q", "-p", "no:cacheprovider",
           "--rootdir", str(GATE_DIR), *[f"--cov={s}" for s in sources], "--cov-branch", f"--cov-config={GATE_DIR / 'coveragerc'}",
           "--cov-report=", timeout=600, env={"COVERAGE_FILE": str(cov_file)})
    if not junit.exists():
        res.status, res.summary = FAIL, f"security tests could not run: {(r.stderr or r.stdout)[-400:]}"
        return res

    groups: dict[str, dict] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        props = {p.get("name"): p.get("value") for p in case.iter("property")}
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        if bad is None and case.find("skipped") is not None:
            continue
        title = props.get("title") or case.get("name", "").split("[")[0]
        g = groups.setdefault(title, {"severity": props.get("severity", "medium"), "area": props.get("area", "api"), "fix": props.get("fix", ""),
                                      "cases": 0, "failed": 0, "first": "", "where": ""})
        g["cases"] += 1
        if bad is not None:
            g["failed"] += 1
            if not g["first"]:
                msg = (bad.get("message") or "").strip().splitlines()
                g["first"] = (msg[0] if msg else "")[:300]
                g["where"] = case.get("classname", "").split(".")[-1] + "::" + case.get("name", "")

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    rows = []
    for title, g in groups.items():
        rows.append({"result": "FAIL" if g["failed"] else "pass", "severity": g["severity"], "attack scenario": title,
                     "area": g["area"], "cases run": g["cases"], "cases that succeeded": g["failed"]})
        if g["failed"]:
            res.findings.append(Finding(g["severity"], title, g["where"], f"{g['failed']} of {g['cases']} attack cases succeeded. First: {g['first']}",
                                        g["area"], g["fix"]))
    res.findings.sort(key=lambda f: order.get(f.severity, 5))
    rows.sort(key=lambda x: (x["result"] != "FAIL", order.get(x["severity"], 5), x["area"]))
    res.tables["Every attack scenario executed"] = rows
    vulnerable = sum(1 for g in groups.values() if g["failed"])
    res.metrics = {"attack scenarios": len(groups), "resisted": len(groups) - vulnerable, "vulnerable": vulnerable,
                   "individual attack cases": sum(g["cases"] for g in groups.values())}
    if vulnerable:
        res.status, res.summary = FAIL, f"{vulnerable} of {len(groups)} attack scenarios succeeded against the API"
    else:
        res.status, res.summary = PASS, f"all {len(groups)} attack scenarios were resisted"
    return res

from __future__ import annotations

from qg.checks._junit import summarize
from qg.model import CheckResult, FAIL, PASS, SKIP
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

    groups = summarize(junit, res, "Every attack scenario executed")
    vulnerable = sum(1 for g in groups.values() if g["failed"])
    res.metrics = {"attack scenarios": len(groups), "resisted": len(groups) - vulnerable, "vulnerable": vulnerable,
                   "individual attack cases": sum(g["cases"] for g in groups.values())}
    if vulnerable:
        res.status, res.summary = FAIL, f"{vulnerable} of {len(groups)} attack scenarios succeeded against the API"
    else:
        res.status, res.summary = PASS, f"all {len(groups)} attack scenarios were resisted"
    return res

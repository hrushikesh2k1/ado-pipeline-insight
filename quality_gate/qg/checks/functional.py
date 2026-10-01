from __future__ import annotations

import os

from qg.checks import azure_posture
from qg.checks._junit import summarize
from qg.model import CheckResult, FAIL, PASS, SKIP, WARN
from qg.util import GATE_DIR, WORK_DIR, module_available, py

ID, NAME, CATEGORY = "functional", "Functional accuracy (live data vs. source)", "Reliability"
WHAT = ("Reads the deployed dashboard's own API and proves the numbers are right: summary cards equal the runs behind them, "
        "recent runs are newest-first with correct durations and paging, the build-duration and daily trends reconcile with the runs, "
        "run detail matches its stages/jobs/tasks, and the deployed site is hardened. With database access it also reconciles every figure "
        "against independent SQL and checks data integrity. Read-only: nothing is written anywhere.")


def _discover_key_vault(cfg: dict) -> str:
    """The Key Vault URL is an app setting (not a secret); look it up so database reconciliation needs no configuration."""
    if cfg["functional"].get("key_vault_url") or os.environ.get("QG_KEY_VAULT_URL") or os.environ.get("KEY_VAULT_URL"):
        return ""
    app = (cfg["azure"].get("webapps") or [None])[0]
    if not app:
        return ""
    settings = azure_posture._az("webapp", "config", "appsettings", "list", "-g", app["resource_group"], "-n", app["name"]) or []
    return next((s["value"] for s in settings if s.get("name") == "KEY_VAULT_URL" and str(s.get("value", "")).startswith("https://")), "")


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    base = os.environ.get("QG_BASE_URL") or cfg["functional"].get("base_url", "")
    if not base:
        res.status, res.summary = SKIP, "no base_url configured in quality_gate.toml [functional]"
        return res
    if not (module_available("pytest") and module_available("requests")):
        res.status, res.summary = SKIP, "pytest/requests not installed"
        return res
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    junit = WORK_DIR / "functional.xml"
    junit.unlink(missing_ok=True)
    env = {}
    vault = _discover_key_vault(cfg)
    if vault:
        env["QG_KEY_VAULT_URL"] = vault
    r = py("-m", "pytest", str(GATE_DIR / "functional_tests"), f"--junitxml={junit}", "-q", "-p", "no:cacheprovider", "--rootdir", str(GATE_DIR),
           timeout=1500, env=env)
    if not junit.exists():
        res.status, res.summary = FAIL, f"functional tests could not run: {(r.stderr or r.stdout)[-400:]}"
        return res

    groups = summarize(junit, res, "Every functional scenario")
    ran = [g for g in groups.values() if g["skipped"] < g["cases"]]
    failed = sum(1 for g in groups.values() if g["failed"])
    not_run = {g["skip_reason"] for g in groups.values() if g["skipped"] == g["cases"] and g["skip_reason"]}
    res.metrics = {"scenarios": len(groups), "verified": len(ran) - failed, "wrong data / broken": failed,
                   "not run": len(groups) - len(ran), "individual checks": sum(g["cases"] for g in groups.values())}
    if failed:
        res.status, res.summary = FAIL, f"{failed} of {len(groups)} functional scenarios found wrong or inconsistent data"
    elif not ran:
        res.status, res.summary = SKIP, "; ".join(sorted(not_run)) or "nothing ran"
    elif len(ran) < len(groups):
        res.status = WARN
        res.summary = f"{len(ran)} scenarios verified, {len(groups) - len(ran)} NOT run: " + "; ".join(sorted(not_run))[:300]
    else:
        res.status, res.summary = PASS, f"all {len(groups)} functional scenarios verified against live data"
    return res

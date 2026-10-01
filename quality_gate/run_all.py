#!/usr/bin/env python
"""Run the whole quality gate and write an HTML report.

    python quality_gate/run_all.py              # everything; inspects the live Azure apps too when `az login` is active
    python quality_gate/run_all.py --no-azure   # code-only run (skips the live deployment inspection)
    python quality_gate/run_all.py --ci         # strict: skipped checks count as failures; exit code 1 on FAIL
    python quality_gate/run_all.py --only sast,deps

Exit code: 0 = PASS or PASS-with-warnings, 1 = at least one blocking check failed.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
import tomllib
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qg import report  # noqa: E402
from qg.checks import api_security, azure_posture, config_audit, deps, functional, lint, sast, secrets, smells, tests_cov, types, ui_accuracy  # noqa: E402
from qg.model import CheckResult, ERROR, FAIL, PASS, SKIP  # noqa: E402
from qg.util import GATE_DIR, REPORTS_DIR, REPO_ROOT, git, tool_version  # noqa: E402

CHECKS = {
    "sast": sast.run_check,
    "deps": deps.run_check,
    "secrets": secrets.run_check,
    "api_security": api_security.run_check,
    "functional": functional.run_check,
    "ui_accuracy": ui_accuracy.run_check,
    "config": config_audit.run_check,
    "lint": lint.run_check,
    "smells": smells.run_check,
    "types": types.run_check,
    "tests": tests_cov.run_check,
    "azure": None,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-live", action="store_true", help="skip the live functional and browser accuracy tests against the deployed site")
    ap.add_argument("--no-azure", action="store_true", help="skip the read-only inspection of the live Azure deployment")
    ap.add_argument("--ci", action="store_true", help="strict mode for pipelines: skipped checks fail the gate")
    ap.add_argument("--only", help="comma-separated check ids: " + ",".join(CHECKS))
    ap.add_argument("--skip", help="comma-separated check ids to skip")
    ap.add_argument("--open", action="store_true", help="open the HTML report in the default browser when finished")
    ap.add_argument("--config", default=str(GATE_DIR / "quality_gate.toml"))
    args = ap.parse_args()

    with open(args.config, "rb") as fh:
        cfg = tomllib.load(fh)
    skipped_ids = (args.skip or "").split(",") + (["functional", "ui_accuracy"] if args.no_live else [])
    selected = [c for c in CHECKS if (not args.only or c in args.only.split(",")) and c not in skipped_ids]

    os.chdir(REPO_ROOT)
    print(f"Quality gate: {len(selected)} checks on {REPO_ROOT.name}\n")
    results: list[CheckResult] = []
    for cid in selected:
        started = time.time()
        print(f"  [{cid:<12}] running...", end="", flush=True)
        try:
            res = azure_posture.run_check(cfg, not args.no_azure) if cid == "azure" else CHECKS[cid](cfg)
        except Exception as exc:
            traceback.print_exc()
            res = CheckResult(cid, cid, "Internal", "The check crashed.", ERROR, f"check crashed: {exc!r}")
        res.duration = time.time() - started
        results.append(res)
        print(f"\r  [{cid:<12}] {res.status:<5} {res.duration:5.1f}s  {res.summary}")

    env = {
        "Commit": (git("rev-parse", "--short", "HEAD") or "n/a") + (" (uncommitted changes)" if git("status", "--porcelain") else ""),
        "Branch": git("rev-parse", "--abbrev-ref", "HEAD") or "n/a",
        "Python": sys.version.split()[0],
        "Mode": "CI (strict)" if args.ci else "local",
        "Bandit": tool_version("bandit").replace("bandit ", ""),
        "Ruff": tool_version("ruff").replace("ruff ", ""),
    }
    verdict = report.overall(results, args.ci)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_text = report.render(results, env, args.ci)
    latest, stamped = REPORTS_DIR / "report.html", REPORTS_DIR / f"report-{stamp}.html"
    for path in (latest, stamped):
        path.write_text(html_text, encoding="utf-8")
    (REPORTS_DIR / "report.json").write_text(json.dumps({
        "verdict": verdict, "environment": env,
        "checks": [{**dataclasses.asdict(r), "counts": r.counts} for r in results],
    }, indent=2, default=str), encoding="utf-8")

    print(f"\nVERDICT: {verdict}")
    print(f"Report : {latest}")
    if args.open:
        webbrowser.open(latest.as_uri())
    return 1 if verdict == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

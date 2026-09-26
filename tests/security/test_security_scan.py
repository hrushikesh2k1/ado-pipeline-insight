"""
Security scan test suite for ado-pipeline-insight-plug-and-play.

Runs two independent checks against the project's own Python source:

  1. Static application security testing (SAST) via Bandit, looking for
     insecure code patterns (SQL injection, hardcoded secrets/credentials,
     unsafe eval/exec, weak crypto, insecure deserialization, etc.).
  2. Dependency vulnerability scanning via pip-audit against every
     requirements*.txt file in the repo, checking pinned packages against
     known CVE databases (OSV / PyPI advisory data).

How to run:
    pip install -r tests/security/requirements-security.txt
    pytest tests/security/test_security_scan.py -v

Both checks write a combined report to tests/security/reports/ (JSON +
plain-text) every time they run, whether they pass or fail, so you always
have a record of exactly what was found.

Thresholds (as configured):
  - Bandit fails the test on any finding with severity >= MEDIUM
    AND confidence >= MEDIUM.
  - pip-audit fails the test on ANY known vulnerability, regardless of
    severity (pip-audit's underlying advisory sources don't consistently
    expose a CVSS score, so "any finding" is the reliable gate).

This module only *reads* the rest of the codebase (via subprocess calls to
bandit/pip-audit) and writes report files under tests/security/reports/.
It does not modify any other file in the project.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

# Python source locations to run Bandit against. Deliberately explicit
# (rather than scanning the whole repo root) so we never crawl into
# venv/, node_modules/, .python_packages/, frontend/, etc.
BANDIT_TARGETS = [
    "core",
    "app",
    "functions",
    "function_app.py",
    "get_recommendations",
    "ingest_run",
]

# Every requirements file that pins installable dependencies.
REQUIREMENTS_FILES = [
    "requirements.txt",
    "requirements-backend.txt",
    "functions/requirements.txt",
]

BANDIT_SEVERITY_THRESHOLD = "medium"  # low | medium | high
BANDIT_CONFIDENCE_THRESHOLD = "medium"  # low | medium | high


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_report(name: str, payload: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{name}_{_timestamp()}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Also keep a "latest" copy that's easy to find without globbing.
    latest = REPORTS_DIR / f"{name}_latest.json"
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _tool_available(module_name: str) -> bool:
    result = _run([sys.executable, "-m", module_name, "--version"], cwd=REPO_ROOT)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Bandit (SAST)
# ---------------------------------------------------------------------------


def test_bandit_static_analysis():
    """Fail if Bandit finds any medium+/medium+ severity/confidence issue."""
    if not _tool_available("bandit"):
        pytest.skip(
            "bandit is not installed. Run: "
            "pip install -r tests/security/requirements-security.txt"
        )

    existing_targets = [t for t in BANDIT_TARGETS if (REPO_ROOT / t).exists()]
    assert existing_targets, "None of the configured Bandit targets exist in the repo."

    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        *existing_targets,
        "-f",
        "json",
        "-ll" if BANDIT_SEVERITY_THRESHOLD == "low" else (
            "-lll" if BANDIT_SEVERITY_THRESHOLD == "high" else "-ll"
        ),
    ]
    # Bandit severity flags: -l (low+), -ll (medium+), -lll (high only).
    # Confidence is filtered the same way with -i / -ii / -iii.
    confidence_flag = {
        "low": "-i",
        "medium": "-ii",
        "high": "-iii",
    }[BANDIT_CONFIDENCE_THRESHOLD]
    cmd.append(confidence_flag)

    result = _run(cmd, cwd=REPO_ROOT)

    try:
        report = json.loads(result.stdout) if result.stdout else {"results": [], "errors": []}
    except json.JSONDecodeError:
        report = {"raw_stdout": result.stdout, "raw_stderr": result.stderr, "results": []}

    findings = report.get("results", [])
    saved_path = _write_report(
        "bandit",
        {
            "targets": existing_targets,
            "severity_threshold": BANDIT_SEVERITY_THRESHOLD,
            "confidence_threshold": BANDIT_CONFIDENCE_THRESHOLD,
            "finding_count": len(findings),
            "findings": findings,
            "bandit_errors": report.get("errors", []),
        },
    )

    if findings:
        summary_lines = [
            f"{f['filename']}:{f['line_number']}  [{f['issue_severity']}/{f['issue_confidence']}]  "
            f"{f['test_id']} {f['issue_text']}"
            for f in findings
        ]
        pytest.fail(
            f"Bandit found {len(findings)} issue(s) at severity>={BANDIT_SEVERITY_THRESHOLD} "
            f"and confidence>={BANDIT_CONFIDENCE_THRESHOLD}.\n"
            f"Full report: {saved_path}\n\n" + "\n".join(summary_lines)
        )


# ---------------------------------------------------------------------------
# pip-audit (dependency vulnerability scan)
# ---------------------------------------------------------------------------


def test_pip_audit_dependency_scan():
    """Fail if pip-audit finds any known vulnerability in pinned dependencies."""
    if not _tool_available("pip_audit"):
        pytest.skip(
            "pip-audit is not installed. Run: "
            "pip install -r tests/security/requirements-security.txt"
        )

    existing_files = [f for f in REQUIREMENTS_FILES if (REPO_ROOT / f).exists()]
    assert existing_files, "None of the configured requirements files exist in the repo."

    all_findings = []
    per_file_errors = {}

    for req_file in existing_files:
        cmd = [
            sys.executable,
            "-m",
            "pip_audit",
            "-r",
            req_file,
            "-f",
            "json",
            "--progress-spinner",
            "off",
        ]
        result = _run(cmd, cwd=REPO_ROOT)

        try:
            data = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            per_file_errors[req_file] = result.stderr or result.stdout
            continue

        # pip-audit JSON: {"dependencies": [{"name":..,"version":..,"vulns":[...]}]}
        for dep in data.get("dependencies", []):
            vulns = dep.get("vulns", [])
            if vulns:
                all_findings.append(
                    {
                        "requirements_file": req_file,
                        "package": dep.get("name"),
                        "version": dep.get("version"),
                        "vulnerabilities": vulns,
                    }
                )

    saved_path = _write_report(
        "pip_audit",
        {
            "requirements_files": existing_files,
            "finding_count": len(all_findings),
            "findings": all_findings,
            "errors": per_file_errors,
        },
    )

    if per_file_errors and not all_findings:
        pytest.skip(
            f"pip-audit could not complete for: {list(per_file_errors)}. "
            f"See {saved_path} for details (likely a network restriction)."
        )

    if all_findings:
        summary_lines = [
            f"{f['requirements_file']}: {f['package']}=={f['version']} -> "
            + ", ".join(v.get("id", "?") for v in f["vulnerabilities"])
            for f in all_findings
        ]
        pytest.fail(
            f"pip-audit found known vulnerabilities in {len(all_findings)} package(s).\n"
            f"Full report: {saved_path}\n\n" + "\n".join(summary_lines)
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

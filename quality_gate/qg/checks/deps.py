from __future__ import annotations

import shutil
from datetime import date

from qg.model import CheckResult, Finding, FAIL, PASS, SEVERITY_RANK, SKIP, WARN
from qg.util import REPO_ROOT, existing, module_available, parse_json, py, run

ID, NAME, CATEGORY = "deps", "Dependency vulnerabilities (pip-audit, npm audit)", "Security"
WHAT = ("Checks every pinned library against public vulnerability databases (OSV / PyPA advisories, npm advisories). "
        "A vulnerable library is exploitable even when your own code is perfect.")


def _ignored(cfg: dict) -> set[str]:
    keep = set()
    for entry in cfg["dependencies"].get("ignore", []):
        if date.fromisoformat(str(entry["expires"])) >= date.today():
            keep.add(entry["id"])
    return keep


def _only_includes(path) -> bool:
    lines = [ln.split("#")[0].strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln]
    return bool(lines) and all(ln.startswith("-r ") for ln in lines)


def _audit_python(cfg: dict, res: CheckResult) -> tuple[dict, list[str], int, int]:
    ignored = _ignored(cfg)
    files = [f for f in existing(cfg["scope"]["requirements"]) if not _only_includes(REPO_ROOT / f)]
    seen: dict[tuple[str, str, str], Finding] = {}
    errors: list[str] = []
    checked = 0
    for req in files:
        r = py("-m", "pip_audit", "-r", req, "-f", "json", "--progress-spinner", "off", timeout=900)
        data = parse_json(r.stdout, None)
        if data is None:
            errors.append(f"{req}: {(r.stderr or '').strip()[-200:]}")
            continue
        for dep in data.get("dependencies", []):
            checked += 1
            for v in dep.get("vulns", []):
                if v["id"] in ignored or any(a in ignored for a in v.get("aliases", [])):
                    continue
                key = (dep["name"].lower(), dep["version"], v["id"])
                if key in seen:
                    if req not in seen[key].location:
                        seen[key].location += f", {req}"
                    continue
                fixes = ", ".join(v.get("fix_versions") or []) or "no fix released"
                seen[key] = Finding(
                    severity="high", title=f"{dep['name']}=={dep['version']} has known vulnerability {v['id']}",
                    location=req, detail=(v.get("description") or "").strip()[:300] or ", ".join(v.get("aliases", [])),
                    rule=v["id"], fix=f"Upgrade to: {fixes}")
    return seen, errors, checked, len(files)


def _audit_npm(cfg: dict, res: CheckResult) -> bool:
    frontend = REPO_ROOT / "frontend"
    npm = shutil.which("npm")
    if not (npm and (frontend / "package-lock.json").exists()):
        res.metrics["npm audit"] = "skipped (npm or package-lock.json not found)"
        return False
    r = run([npm, "audit", "--json", "--omit=dev"], cwd=frontend, timeout=300)
    data = parse_json(r.stdout, None)
    if not data or "vulnerabilities" not in data:
        res.metrics["npm audit"] = "could not reach registry"
        return False
    fail_rank = SEVERITY_RANK[cfg["dependencies"]["npm_fail_severity"]]
    blocking = False
    for name, v in data["vulnerabilities"].items():
        sev = {"moderate": "medium"}.get(v.get("severity", "low"), v.get("severity", "low"))
        via = ", ".join(x if isinstance(x, str) else x.get("title", "") for x in v.get("via", []))[:250]
        res.findings.append(Finding(sev, f"npm: {name} ({sev})", "frontend/package-lock.json", f"via {via}", "npm-audit",
                                    "npm audit fix" if v.get("fixAvailable") else "no automatic fix"))
        blocking = blocking or SEVERITY_RANK[sev] <= fail_rank
    res.metrics["npm vulnerabilities (runtime deps)"] = len(data["vulnerabilities"])
    return blocking


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not module_available("pip_audit"):
        res.status, res.summary = SKIP, "pip-audit is not installed (pip install -r quality_gate/requirements.txt)"
        return res
    seen, errors, checked, nfiles = _audit_python(cfg, res)
    res.findings.extend(seen.values())
    res.metrics = {"requirement files": nfiles, "pinned packages checked": checked, "python vulnerabilities": len(seen)}
    npm_blocking = _audit_npm(cfg, res)
    res.findings.sort(key=lambda f: SEVERITY_RANK[f.severity])

    py_blocking = bool(seen) and cfg["dependencies"]["fail_on_any_python_vuln"]
    if errors and not res.findings:
        res.status, res.summary = FAIL, "pip-audit could not complete (network?): " + "; ".join(errors)
    elif py_blocking or npm_blocking:
        res.status, res.summary = FAIL, f"{len(res.findings)} vulnerable dependency finding(s)"
    elif res.findings:
        res.status, res.summary = WARN, f"{len(res.findings)} non-blocking dependency finding(s)"
    else:
        res.status, res.summary = PASS, f"{checked} pinned packages checked, no known vulnerabilities"
    if errors and res.status in (PASS, WARN):
        res.status = WARN
        res.summary += f" (partial: {len(errors)} requirements file(s) could not be audited)"
    return res

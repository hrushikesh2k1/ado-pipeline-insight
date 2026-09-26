from __future__ import annotations

from qg.model import CheckResult, Finding, FAIL, PASS, SEVERITY_RANK, SKIP, WARN
from qg.util import WORK_DIR, existing, module_available, parse_json, py, rel

ID, NAME, CATEGORY = "sast", "Static security analysis (Bandit)", "Security"
WHAT = ("Reads the source without running it and looks for insecure patterns: SQL built from strings, hard-coded "
        "passwords, unsafe eval/pickle/subprocess, weak crypto, binding to all interfaces, swallowed exceptions.")


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not module_available("bandit"):
        res.status, res.summary = SKIP, "bandit is not installed (pip install -r quality_gate/requirements.txt)"
        return res
    targets = existing(cfg["scope"]["production"] + cfg["scope"]["extra"])
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    out = WORK_DIR / "bandit.json"
    out.unlink(missing_ok=True)
    r = py("-m", "bandit", "-r", *targets, "-f", "json", "-o", str(out), "-q", "--exclude", "**/node_modules,**/__pycache__")
    data = parse_json(out.read_text(encoding="utf-8") if out.exists() else "", None)
    if data is None:
        res.status, res.summary = FAIL, f"bandit produced no usable output: {(r.stderr or r.stdout)[:300]}"
        return res

    fail_at = SEVERITY_RANK[cfg["sast"]["fail_severity"]]
    warn_at = SEVERITY_RANK[cfg["sast"]["warn_severity"]]
    blocking = advisory = 0
    for item in data.get("results", []):
        sev = item["issue_severity"].lower()
        rank = SEVERITY_RANK[sev]
        if rank > warn_at:
            continue
        is_block = rank <= fail_at
        blocking += is_block
        advisory += not is_block
        res.findings.append(Finding(
            severity=sev, title=item["issue_text"], location=f"{rel(item['filename'])}:{item['line_number']}",
            detail=f"confidence={item['issue_confidence'].lower()}  CWE-{item.get('issue_cwe', {}).get('id', '?')}",
            rule=f"{item['test_id']} {item['test_name']}", fix=item.get("more_info", ""),
        ))
    res.findings.sort(key=lambda f: SEVERITY_RANK[f.severity])
    totals = data.get("metrics", {}).get("_totals", {})
    res.metrics = {
        "files scanned": len(data.get("metrics", {})) - 1,
        "lines of code": int(totals.get("loc", 0)),
        "suppressed with nosec": int(totals.get("nosec", 0)),
        "blocking findings": blocking,
        "advisory findings": advisory,
    }
    if blocking:
        res.status, res.summary = FAIL, f"{blocking} finding(s) at {cfg['sast']['fail_severity']} severity or higher"
    elif advisory:
        res.status, res.summary = WARN, f"no blocking findings, {advisory} low-severity finding(s)"
    else:
        res.status, res.summary = PASS, "no findings"
    return res

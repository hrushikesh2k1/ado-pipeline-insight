from __future__ import annotations

from collections import Counter

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP, WARN
from qg.util import GATE_DIR, existing, module_available, parse_json, py, rel

ID, NAME, CATEGORY = "lint", "Linting (Ruff)", "Code quality"
WHAT = ("Style and correctness linter. Blocking rules catch real bugs (undefined names, bare excepts, mutable defaults, "
        "insecure calls). Advisory rules track readability debt such as long lines and multi-statement lines.")


def _ruff(select: list[str], targets: list[str], ignore: list[str] | None = None) -> list[dict]:
    r = py("-m", "ruff", "check", *targets, "--select", ",".join(select), *(["--ignore", ",".join(ignore)] if ignore else []),
           "--config", str(GATE_DIR / "ruff.toml"), "--output-format", "json", "--no-cache")
    return parse_json(r.stdout, []) or []


def _key(d: dict) -> tuple:
    return (d["filename"], d["location"]["row"], d["code"])


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not module_available("ruff"):
        res.status, res.summary = SKIP, "ruff is not installed (pip install -r quality_gate/requirements.txt)"
        return res
    targets = existing(cfg["scope"]["production"] + cfg["scope"]["extra"] + [cfg["scope"]["unit_tests"]])
    blocking = _ruff(cfg["lint"]["blocking"], targets, cfg["lint"].get("blocking_ignore"))
    block_keys = {_key(d) for d in blocking}
    advisory = [d for d in _ruff(cfg["lint"]["advisory"], targets) if _key(d) not in block_keys]

    for d in blocking:
        sev = "medium"
        res.findings.append(Finding(sev, d["message"], f"{rel(d['filename'])}:{d['location']['row']}", "", d["code"],
                                    (d.get("fix") or {}).get("message", "")))
    res.tables["Advisory issues by rule"] = [{"rule": k, "count": v} for k, v in Counter(d["code"] for d in advisory).most_common(15)]
    res.tables["Files with most advisory issues"] = [{"file": k, "count": v} for k, v in Counter(rel(d["filename"]) for d in advisory).most_common(10)]
    res.metrics = {"blocking issues": len(blocking), "advisory issues": len(advisory)}
    if blocking:
        res.status, res.summary = FAIL, f"{len(blocking)} blocking lint issue(s), {len(advisory)} advisory"
    elif advisory:
        res.status, res.summary = WARN, f"no blocking issues, {len(advisory)} advisory style issue(s)"
    else:
        res.status, res.summary = PASS, "clean"
    return res

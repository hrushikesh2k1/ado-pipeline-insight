from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from qg.model import CheckResult, Finding, FAIL, PASS, SKIP, WARN
from qg.util import REPO_ROOT, existing, module_available, parse_json, py, rel

ID, NAME, CATEGORY = "smells", "Code smells (complexity, dead code, duplication)", "Code quality"
WHAT = ("Finds code that is hard to test and easy to break: functions with too many branches (cyclomatic complexity), "
        "very long functions/files, low maintainability index, unused code, and copy-pasted blocks.")

DUP_WINDOW = 8


def _complexity(cfg: dict, res: CheckResult, targets: list[str]) -> tuple[int, int]:
    c = cfg["complexity"]
    data = parse_json(py("-m", "radon", "cc", "-s", "-j", *targets).stdout, {}) or {}
    rows, failed, warned = [], 0, 0
    for path, blocks in data.items():
        if isinstance(blocks, dict):
            continue
        for b in blocks:
            length = b.get("endline", b["lineno"]) - b["lineno"] + 1
            rows.append({"function": f"{rel(path)}:{b['lineno']} {b['name']}", "complexity": b["complexity"], "rank": b["rank"], "lines": length})
            loc = f"{rel(path)}:{b['lineno']}"
            if b["complexity"] >= c["fail_cc"]:
                failed += 1
                res.findings.append(Finding("high", f"{b['name']} is too complex (cyclomatic complexity {b['complexity']})", loc, "", "CC-fail",
                                            "Split into smaller functions; each branch is a path that needs a test."))
            elif b["complexity"] >= c["warn_cc"]:
                warned += 1
                res.findings.append(Finding("low", f"{b['name']} is complex (cyclomatic complexity {b['complexity']})", loc, "", "CC-warn",
                                            "Consider extracting helpers."))
            if length >= c["warn_function_lines"]:
                warned += 1
                res.findings.append(Finding("low", f"{b['name']} is {length} lines long", loc, "", "LONG-FUNC", "Split into smaller units."))
    rows.sort(key=lambda r: -r["complexity"])
    res.tables["Most complex functions"] = rows[:12]
    res.metrics["functions analysed"] = len(rows)
    res.metrics["average complexity"] = round(sum(r["complexity"] for r in rows) / len(rows), 1) if rows else 0
    return failed, warned


def _maintainability(cfg: dict, res: CheckResult, targets: list[str]) -> int:
    data = parse_json(py("-m", "radon", "mi", "-s", "-j", *targets).stdout, {}) or {}
    warned = 0
    rows = []
    for path, info in data.items():
        if not isinstance(info, dict) or "mi" not in info:
            continue
        rows.append({"file": rel(path), "maintainability index": round(info["mi"], 1), "rank": info["rank"]})
        if info["mi"] < cfg["complexity"]["maintainability_warn"]:
            warned += 1
            res.findings.append(Finding("low", f"Low maintainability index ({info['mi']:.1f}/100)", rel(path), "", "MI",
                                        "Large, dense modules are risky to change; split by responsibility."))
    rows.sort(key=lambda r: r["maintainability index"])
    res.tables["Least maintainable files"] = rows[:8]
    return warned


def _file_size(cfg: dict, res: CheckResult, files: list[str]) -> int:
    warned = 0
    for f in files:
        n = sum(1 for _ in (REPO_ROOT / f).open(encoding="utf-8", errors="ignore"))
        if n >= cfg["complexity"]["warn_file_lines"]:
            warned += 1
            res.findings.append(Finding("low", f"File is {n} lines long", f, "", "LONG-FILE", "Split into cohesive modules."))
    return warned


def _dead_code(cfg: dict, res: CheckResult, targets: list[str]) -> int:
    if not module_available("vulture"):
        return 0
    r = py("-m", "vulture", *targets, "--min-confidence", str(cfg["complexity"]["dead_code_confidence"]), "--ignore-names", "cls")
    n = 0
    for line in r.stdout.splitlines():
        m = re.match(r"(.+?):(\d+): (.+) \((\d+)% confidence\)", line)
        if m:
            n += 1
            res.findings.append(Finding("low", m.group(3), f"{rel(m.group(1))}:{m.group(2)}", f"{m.group(4)}% confidence", "DEAD-CODE",
                                        "Remove it or use it."))
    return n


def _duplication(res: CheckResult, files: list[str]) -> int:
    seen: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for f in files:
        lines = [ln.strip() for ln in (REPO_ROOT / f).read_text(encoding="utf-8", errors="ignore").splitlines()]
        code = [(i + 1, ln) for i, ln in enumerate(lines) if ln and not ln.startswith(("#", "import ", "from ")) and len(ln) > 3]
        for i in range(len(code) - DUP_WINDOW + 1):
            block = "\n".join(ln for _, ln in code[i:i + DUP_WINDOW])
            if sum(len(ln) for _, ln in code[i:i + DUP_WINDOW]) < 200:
                continue
            seen[hashlib.md5(block.encode(), usedforsecurity=False).hexdigest()].append((f, code[i][0]))
    reported: set[tuple[str, str]] = set()
    n = 0
    for spots in seen.values():
        files_hit = {s[0] for s in spots}
        if len(spots) < 2:
            continue
        a, b = spots[0], spots[1]
        pair = (a[0], b[0])
        if a[0] == b[0] and abs(a[1] - b[1]) < DUP_WINDOW:
            continue
        if pair in reported and len(files_hit) <= 2:
            continue
        reported.add(pair)
        n += 1
        res.findings.append(Finding("low", f"Duplicated {DUP_WINDOW}+ line block", f"{a[0]}:{a[1]}", f"also at {b[0]}:{b[1]}", "DUPLICATE",
                                    "Extract shared logic into one function."))
    return n


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    if not module_available("radon"):
        res.status, res.summary = SKIP, "radon is not installed (pip install -r quality_gate/requirements.txt)"
        return res
    targets = existing(cfg["scope"]["production"])
    py_files = sorted({rel(p) for t in targets for p in ([REPO_ROOT / t] if t.endswith(".py") else (REPO_ROOT / t).rglob("*.py"))
                       if "__pycache__" not in str(p)})
    failed, warned = _complexity(cfg, res, targets)
    warned += _maintainability(cfg, res, targets)
    warned += _file_size(cfg, res, py_files)
    dead = _dead_code(cfg, res, targets)
    dup = _duplication(res, py_files)
    res.metrics.update({"files analysed": len(py_files), "dead-code hints": dead, "duplicated blocks": dup})
    res.findings.sort(key=lambda f: ("high", "medium", "low", "info").index(f.severity if f.severity in ("high", "medium", "low") else "info"))
    if failed:
        res.status, res.summary = FAIL, f"{failed} function(s) above the complexity limit ({cfg['complexity']['fail_cc']})"
    elif res.findings:
        res.status, res.summary = WARN, f"{len(res.findings)} smell(s): complexity/length {warned}, dead code {dead}, duplication {dup}"
    else:
        res.status, res.summary = PASS, "no code smells above thresholds"
    return res

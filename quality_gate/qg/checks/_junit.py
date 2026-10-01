"""Turn a junit file from a `@pytest.mark.<marker>(severity, area, title, fix)` test suite into report rows and findings."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from qg.model import CheckResult, Finding

ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def summarize(junit_path, res: CheckResult, table_title: str) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        props = {p.get("name"): p.get("value") for p in case.iter("property")}
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        skipped = case.find("skipped")
        title = props.get("title") or case.get("name", "").split("[")[0]
        g = groups.setdefault(title, {"severity": props.get("severity", "medium"), "area": props.get("area", "general"), "fix": props.get("fix", ""),
                                      "cases": 0, "failed": 0, "skipped": 0, "first": "", "where": "", "skip_reason": ""})
        g["cases"] += 1
        if skipped is not None:
            g["skipped"] += 1
            g["skip_reason"] = g["skip_reason"] or (skipped.get("message") or "")[:200]
        elif bad is not None:
            g["failed"] += 1
            if not g["first"]:
                msg = (bad.get("message") or "").strip().splitlines()
                g["first"] = (msg[0] if msg else "")[:400]
                g["where"] = case.get("classname", "").split(".")[-1] + "::" + case.get("name", "")

    rows = []
    for title, g in groups.items():
        state = "FAIL" if g["failed"] else ("not run" if g["skipped"] == g["cases"] else "pass")
        rows.append({"result": state, "severity": g["severity"], "scenario": title, "area": g["area"], "cases": g["cases"],
                     "failed": g["failed"], "skipped": g["skipped"]})
        if g["failed"]:
            res.findings.append(Finding(g["severity"], title, g["where"], f"{g['failed']} of {g['cases']} cases failed. First: {g['first']}",
                                        g["area"], g["fix"]))
    res.findings.sort(key=lambda f: ORDER.get(f.severity, 5))
    rows.sort(key=lambda x: ({"FAIL": 0, "not run": 1, "pass": 2}[x["result"]], ORDER.get(x["severity"], 5), x["area"]))
    res.tables[table_title] = rows
    return groups

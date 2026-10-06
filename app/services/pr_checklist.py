"""The checklist in a pull request description, checked against what the pull request really contains.

A ticked box is a claim. Where the pull request itself can confirm or contradict it (a changelog file changed, test files
changed, a work item linked, the run linked in the description is the newest one) the claim is checked; every other item is
listed as something this review cannot verify. Nothing here guesses.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.pr_diff import is_changelog_path, is_test_path

_BOX = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s+(.*\S)\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\s*\([^)]*\)")
_CHANGELOG = re.compile(r"change-?\s?log|release notes?", re.IGNORECASE)
_TESTS_ADDED = re.compile(r"\btests?\b.*\b(created|added|written)\b|\badded tests?\b|\btests? that prove\b", re.IGNORECASE)
_WORK_ITEM = re.compile(r"work\s?items?", re.IGNORECASE)
_BUILD_LINK = re.compile(r"buildId=(\d+)", re.IGNORECASE)

OK, MISMATCH, OPEN, UNVERIFIABLE = "ok", "mismatch", "open", "unverifiable"


def parse_checklist(description: str) -> list[dict[str, Any]]:
    items = []
    for line in (description or "").splitlines():
        match = _BOX.match(line)
        if match:
            # a link is shown as its words: "[Alert Inventory wiki](https://...)" -> "Alert Inventory wiki"
            text = " ".join(_LINK.sub(r"\1", match.group(2)).split())
            items.append({"text": text, "checked": match.group(1) in "xX"})
    return items


def linked_build_ids(description: str) -> list[int]:
    return sorted({int(n) for n in _BUILD_LINK.findall(description or "")})


_PLACEHOLDER = re.compile(r"\[(?:insert|add|enter|paste|put|provide|todo|tbd|link to|your)\b[^\]\n]{0,60}\](?!\s*\()|<(?:insert|add|enter|paste)\b[^>\n]{0,60}>", re.IGNORECASE)


def placeholder_checks(description: str) -> list[dict[str, Any]]:
    """Template text the author left in the description, such as "[Insert Pipeline Link]": a link or a value that was never filled in."""
    found = list(dict.fromkeys(m.group(0) for m in _PLACEHOLDER.finditer(description or "")))
    if not found:
        return []
    shown = ", ".join(f'"{p}"' for p in found[:3]) + (f" and {len(found) - 3} more" if len(found) > 3 else "")
    return [{"item": "Template text left in the description", "checked": None, "status": OPEN, "evidence": f"not filled in: {shown}"}]


def _verdict(checked: bool, found: bool, found_text: str, missing_text: str) -> tuple[str, str]:
    if found:
        return OK, found_text + ("" if checked else " (the box is not ticked)")
    return (MISMATCH if checked else OPEN), missing_text


def evaluate_checklist(items: list[dict[str, Any]], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Each checklist item with a status (ok, mismatch, open, unverifiable) and the evidence behind it.

    `evidence`: changed_paths (list of paths), work_items (list of ids, or None when they could not be read) and build_check
    (None when the description links no run; otherwise {"error": True} or {"linked_id", "pipeline", "newer_id", "newer_result"}).
    """
    paths = evidence.get("changed_paths") or []
    changelogs = [p for p in paths if is_changelog_path(p)]
    tests = [p for p in paths if is_test_path(p)]
    work_items = evidence.get("work_items")
    results: list[dict[str, Any]] = []

    for item in items:
        text, checked = item["text"], item["checked"]
        if _CHANGELOG.search(text):
            status, why = _verdict(checked, bool(changelogs), f"{changelogs[0].rsplit('/', 1)[-1]} is changed in this pull request" if changelogs else "",
                                   "no changelog file is changed in this pull request")
        elif _TESTS_ADDED.search(text):
            status, why = _verdict(checked, bool(tests), f"{len(tests)} test file(s) changed, for example {tests[0].rsplit('/', 1)[-1]}" if tests else "",
                                   "no test file is changed in this pull request (by file name)")
        elif _WORK_ITEM.search(text):
            if work_items is None:
                status, why = UNVERIFIABLE, "the linked work items could not be read (the token may lack the Work Items read scope)"
            else:
                status, why = _verdict(checked, bool(work_items), f"{len(work_items)} work item(s) linked: {', '.join('#' + w for w in work_items[:3])}",
                                       "no work item is linked to this pull request")
        else:
            status, why = UNVERIFIABLE, "cannot be checked from the pull request"
        results.append({"item": text, "checked": checked, "status": status, "evidence": why})

    build = evidence.get("build_check")
    if build:
        label = "The run linked in the description is the newest run of that pipeline"
        if build.get("error"):
            results.append({"item": label, "checked": None, "status": UNVERIFIABLE, "evidence": "the builds of the source branch could not be read (the token may lack the Build read scope)"})
        elif build.get("newer_id"):
            result = f" ({build['newer_result']})" if build.get("newer_result") else ""
            results.append({"item": label, "checked": None, "status": MISMATCH,
                            "evidence": f"the description links run {build['linked_id']}, but a newer run of {build.get('pipeline') or 'the same pipeline'} exists on this branch: {build['newer_id']}{result}"})
        else:
            results.append({"item": label, "checked": None, "status": OK, "evidence": f"run {build['linked_id']} is the newest run of {build.get('pipeline') or 'its pipeline'} on this branch"})
    return results

"""A pretend Azure DevOps and a pretend model for the pull request review. The code in these files is made up."""
from __future__ import annotations

import json
import re
import threading
from types import SimpleNamespace
from typing import Any, Callable

PY_OLD = """import json


def load(path):
    with open(path) as handle:
        return json.load(handle)


def to_bytes(text):
    if "GB" in text:
        return int(text.strip("GB")) * 10**9
    return int(text.strip("B"))
"""

PY_NEW = """import json
from typing import Any  # noqa: F401


def load(path) -> dict:
    with open(path) as handle:
        return json.load(handle)


def to_bytes(text):
    if "GB" in text:
        return int(text.strip("GB")) * 10**9
    return int(text.strip("B"))


def average(values):
    return sum(values) / len(values)
"""

PS_NEW = """function Get-Totals {
    param($Items)
    $result = @()
    foreach ($item in $Items) {
        $result += $item.Total
    }
    Write-Host "done"
    return $result
}
"""

DESCRIPTION = """Adds a report.

Checklist:
- [x] Changelog updated
- [x] Unit tests have been created
- [x] WorkItem is associated to the PR
- [ ] Spell check performed
- [x] Coding standards are followed

Regression results: https://dev.azure.com/org/proj/_build/results?buildId=100&view=results
"""


def decoded(text: str, has_bom: bool = False, bad_line: int | None = None, bad_count: int = 0):
    """File text as the client reads it, with what decoding showed (see core.ado_client.DecodedText)."""
    from core.ado_client import DecodedText
    value = DecodedText(text)
    value.has_bom, value.bad_byte_line, value.bad_byte_count = has_bom, bad_line, bad_count
    return value


CSPROJ = "<Project Sdk=\"Microsoft.NET.Sdk.Web\">\n  <PropertyGroup>\n    <TargetFramework>{tfm}</TargetFramework>\n  </PropertyGroup>\n</Project>\n"


def change(path: str, kind: str = "edit", new_id: str | None = None, old_id: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": path, "objectId": new_id or f"new-{path}"}
    if kind != "add":
        item["originalObjectId"] = old_id or f"old-{path}"
    return {"changeId": 1, "changeTrackingId": 1, "changeType": kind, "item": item}


class FakeAdo:
    """The few calls the review makes. `blobs` maps an object id to its text; `fail` names calls that raise."""

    def __init__(self, changes=None, blobs=None, threads=None, work_items=None, builds=None, description=DESCRIPTION, fail=(), iterations=1, repo_files=None, tree_unreadable=False):
        self.description = description
        self.repo_files = repo_files if repo_files is not None else {}  # the rest of the repository, for lookups
        self.tree_unreadable = tree_unreadable
        self.item_calls: list[str] = []
        self.changes = changes if changes is not None else [
            change("/scripts/report.py"), change("/scripts/totals.ps1", "add"), change("/CHANGELOG.md"), change("/tests/test_report.py", "add"),
        ]
        self.blobs = blobs if blobs is not None else {
            "new-/scripts/report.py": PY_NEW, "old-/scripts/report.py": PY_OLD, "new-/scripts/totals.ps1": PS_NEW,
            "new-/CHANGELOG.md": "# Changelog\n", "old-/CHANGELOG.md": "", "new-/tests/test_report.py": "def test_x():\n    assert True\n",
        }
        self.threads = threads if threads is not None else []
        self.work_items = work_items if work_items is not None else [{"id": "55"}]
        self.builds = builds if builds is not None else [{"id": 120, "result": "failed", "definition": {"id": 7, "name": "Regression"}}, {"id": 100, "result": "succeeded", "definition": {"id": 7, "name": "Regression"}}]
        self.fail = set(fail)
        self.iterations = iterations
        self.blob_calls: list[str] = []

    def _maybe(self, name: str) -> None:
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    def get_pull_request(self, project, repo, pr_id):
        self._maybe("get_pull_request")
        return {"title": "Add the report", "description": self.description, "sourceRefName": "refs/heads/feature", "targetRefName": "refs/heads/dev"}

    def get_pull_request_iterations(self, project, repo, pr_id):
        return [{"id": n, "sourceRefCommit": {"commitId": "a" * 40}, "commonRefCommit": {"commitId": "b" * 40}} for n in range(1, self.iterations + 1)]

    def get_all_pull_request_iteration_changes(self, project, repo, pr_id, iteration_id):
        return self.changes

    def get_pull_request_threads(self, project, repo, pr_id):
        self._maybe("threads")
        return self.threads

    def get_pull_request_work_items(self, project, repo, pr_id):
        self._maybe("work_items")
        return self.work_items

    def get_build(self, project, build_id):
        self._maybe("builds")
        return {"id": build_id, "definition": {"id": 7, "name": "Regression"}}

    def list_builds_for_branch(self, project, branch, top=10):
        self._maybe("builds")
        return self.builds

    def get_blob_text(self, project, repo, object_id, max_bytes=200_000):
        self.blob_calls.append(object_id)
        if object_id not in self.blobs:
            return None, "unreadable"
        value = self.blobs[object_id]
        return (None, value["reason"]) if isinstance(value, dict) else (value, None)  # {"reason": "too_large"} stands for a file that cannot be read

    def get_item_text(self, project, repo, path, commit, max_bytes=200_000):
        """A file of the repository at a commit: `repo_files` maps a path (no leading slash) to its text, or to {"reason": ...} for a file that cannot be read."""
        self.item_calls.append(path)
        value = self.repo_files.get(path.lstrip("/"))
        if value is None:
            return None, "unreadable"
        return (None, value["reason"]) if isinstance(value, dict) else (value, None)

    def list_repository_files(self, project, repo, commit_id, max_items=30000):
        self._maybe("list_files")
        return None if self.repo_files is None or self.tree_unreadable else ["/" + p for p in self.repo_files]


def thread(path: str | None, line: int | None, text: str, status: str = "fixed", author: str = "Sam Reviewer", system: bool = False, replies=()) -> dict[str, Any]:
    """A comment thread. `replies` is a list of (author, text). A path with no line is a comment on the whole file; no path, on the whole pull request."""
    if path and line is not None:
        context = {"filePath": "/" + path, "rightFileStart": {"line": line, "offset": 1}, "rightFileEnd": {"line": line, "offset": 5}}
    else:
        context = {"filePath": "/" + path} if path else None
    comments = [{"id": 1, "content": text, "commentType": "system" if system else "text", "author": {"displayName": author}}]
    comments += [{"id": n, "parentCommentId": 1, "content": said, "commentType": "text", "author": {"displayName": who}} for n, (who, said) in enumerate(replies, 2)]
    return {"id": 1, "status": status, "isDeleted": False, "threadContext": context, "comments": comments}


def finding(line: int, title: str = "Problem", severity: str = "warning", **over: Any) -> dict[str, Any]:
    """What a well-behaved model returns for a finding. `evidence` is left out on purpose: FakePrModel quotes the code on the line, as a good model does;
    pass evidence= to say something else (or "" for none)."""
    body = {"line": line, "end_line": None, "category": "correctness", "severity": severity, "title": title,
            "comment": f"{title}: it fails for the input '10GBps' and returns the wrong value. Anchor the check.",
            "failing_case": "For the input '10GBps' the function returns the wrong size.", "suggestion_code": None}
    body.update(over)
    return body


def evidence_at(text: str, line: int) -> str:
    """The code on a line of a file (the next non-blank line if it is blank): what a model quotes as the code it relies on."""
    for candidate in text.splitlines()[max(line, 1) - 1:max(line, 1) + 9]:
        if candidate.strip():
            return candidate.strip()
    return ""


_ROW = re.compile(r"^[+ ] +(\d+) \| (.*)$", re.MULTILINE)
SILENT = object()  # for FakePrModel(holds=...): the second check does not answer for that finding


class FakePrModel:
    """Answers the three kinds of prompt. `findings` maps a file path to what the first call says about it (a list, or an
    Exception to raise); `holds` says which finding numbers survive the second check (default: all)."""

    def __init__(self, findings: dict[str, Any] | None = None, holds: Callable[[str, list[int]], dict[int, Any]] | None = None, gaps: Any = None, purposes: dict[str, str] | None = None,
                 lookups: dict[str, list[tuple[str, dict[str, Any]]]] | None = None, decide: Callable[[str, list[int], list[str]], dict[int, Any]] | None = None,
                 refutes: dict[str, Any] | None = None, team_checks: Any = None):
        """`lookups` maps a file path to the tool calls the second check makes before it answers (a list of (tool name, arguments)); `decide(path, numbers,
        tool results)` then says which findings hold, in place of `holds`. `refutes` maps a file path to {finding number: (why it is wrong, code that shows it)}
        for the refutation call (or to an Exception to raise); `team_checks` is {check number: (breaks, why, quote)} for the team's checks about the pull request
        (or an Exception)."""
        self.refutes = refutes or {}
        self.team_checks = team_checks if team_checks is not None else {}
        self.deployment = "fake"
        self.findings = findings if findings is not None else {}
        self.holds = holds
        self.gaps = [] if gaps is None else gaps
        self.purposes = purposes or {}
        self.lookups = lookups or {}
        self.decide = decide
        self.calls: list[tuple[str, str]] = []
        self.tools_offered: list[bool] = []  # for each second check: were the lookup tools offered?
        self.tool_results: list[str] = []
        self._lock = threading.Lock()
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    MARKERS = {"file": "You review one changed file", "verify": "You check findings", "description": "You compare the description",
               "refute": "You are a sceptical senior engineer", "team": "You check a pull request against checks"}

    def calls_of(self, kind: str) -> list[str]:
        return [user for system, user in self.calls if system.startswith(self.MARKERS[kind])]

    def system_of(self, kind: str) -> list[str]:
        return [system for system, user in self.calls if system.startswith(self.MARKERS[kind])]

    def _create(self, model, messages, temperature=0, response_format=None, tools=None, tool_choice=None):
        system, user = messages[0]["content"], messages[1]["content"]
        results = [m["content"] for m in messages if m.get("role") == "tool"]
        with self._lock:
            if not results:
                self.calls.append((system, user))
                if system.startswith("You check findings"):
                    self.tools_offered.append(bool(tools))
        if system.startswith("You review one changed file"):
            path = re.search(r"^File: (.+)$", user, re.M).group(1).strip()
            said = self.findings.get(path, [])
            if isinstance(said, Exception):
                raise said
            rows = {int(n): text for n, text in _ROW.findall(user)}
            ordered = sorted(rows)
            filled = []
            for item in said:
                item = dict(item) if isinstance(item, dict) else item
                if isinstance(item, dict) and "evidence" not in item:  # quote the code on the line, or the next line that has any
                    start = int(item.get("line") or 0)
                    item["evidence"] = next((rows[n].strip() for n in ordered if n >= start and rows[n].strip()), "")
                filled.append(item)
            body: Any = {"purpose": self.purposes.get(path, f"changes {path}"), "findings": filled}
        elif system.startswith("You check findings"):
            path = re.search(r"^File: (\S+)", user, re.M).group(1)
            numbers = [int(n) for n in re.findall(r"^(\d+)\. line", user, re.M)]
            wanted = self.lookups.get(path) if tools else None
            if wanted and not results:  # the second check looks things up first
                calls = [SimpleNamespace(id=f"call{n}", function=SimpleNamespace(name=name, arguments=json.dumps(args))) for n, (name, args) in enumerate(wanted, 1)]
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=calls))])
            if results:
                with self._lock:
                    self.tool_results.extend(results)
            decided = self.decide(path, numbers, results) if (self.decide and results) else (self.holds(path, numbers) if self.holds else {})
            if isinstance(decided, Exception):
                raise decided
            def answer(n: int) -> dict[str, Any]:
                said = decided.get(n, True)  # True, False, (False, "why"), or {"holds": ..., "reason": ..., "duplicate_of": 1, "already_raised_by": "E2"}
                if isinstance(said, dict):
                    return {"holds": said.get("holds", True), "reason": said.get("reason", "ok"), "duplicate_of": said.get("duplicate_of"), "already_raised_by": said.get("already_raised_by"),
                            "already_found_by_code": said.get("already_found_by_code")}
                holds, reason = (said[0], said[1]) if isinstance(said, tuple) else (bool(said), "ok")
                return {"holds": holds, "reason": reason, "duplicate_of": None, "already_raised_by": None, "already_found_by_code": None}

            body = {"findings": [{"number": n, **answer(n)} for n in numbers if not (isinstance(decided, dict) and decided.get(n) is SILENT)]}  # SILENT: the check says nothing about it
        elif system.startswith(self.MARKERS["refute"]):
            path = re.search(r"^File: (\S+)", user, re.M).group(1)
            said = self.refutes.get(path, {})
            if isinstance(said, Exception):
                raise said
            numbers = [int(n) for n in re.findall(r"^(\d+)\. line", user, re.M)]
            body = {"findings": [{"number": n, "wrong": n in said, "because": said[n][0] if n in said else "", "quote": said[n][1] if n in said else ""} for n in numbers]}
        elif system.startswith(self.MARKERS["team"]):
            if isinstance(self.team_checks, Exception):
                raise self.team_checks
            body = {"checks": [{"number": n, "breaks": v[0], "because": v[1], "quote": v[2]} for n, v in self.team_checks.items()]}
        else:
            if isinstance(self.gaps, Exception):
                raise self.gaps
            body = {"missing_from_description": self.gaps}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))])

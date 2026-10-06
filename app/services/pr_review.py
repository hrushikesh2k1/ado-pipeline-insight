"""AI review of a pull request: the real changes, file by file, with every comment checked before it is shown.

For each changed file the reviewer is given the diff (see pr_diff), the comments people already made on that file, and review
guidance for its language. Every finding is then checked in code (the file and line must be part of the pull request) and by a
second, sceptical model call. The verdict, the scorecard and the summary are worked out from the findings that remain, never
written by the model. If the model is not available there is no review: nothing is made up in its place.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.core.config import get_settings
from app.services.llm_util import chat_json, with_retry
from app.services.pr_checklist import evaluate_checklist, linked_build_ids, parse_checklist
from app.services.pr_diff import FileView, build_view, classify, priority, suggestable
from core.openai_client import PipelineRecommendationClient

logger = logging.getLogger(__name__)

MAX_FILES = 20
MAX_FINDINGS_PER_FILE = 8
MAX_SPAN = 40
WORKERS = 5
MAX_FILE_BYTES = 200_000
REVIEW_BUDGET_SECONDS = 170  # Azure App Service ends a request after 230 s: a slow model gives a partial review, not a timeout
CATEGORIES = ("correctness", "security", "performance", "maintainability", "test_coverage")
SEVERITIES = ("critical", "warning", "suggestion")
RESOLVED = {"fixed", "closed", "wontFix", "byDesign"}
STATUS_WORDS = {"active": "open", "pending": "pending", "fixed": "resolved", "closed": "closed", "wontFix": "won't fix", "byDesign": "by design"}

SCOPE_NOTE = ("This review reads the code changes only. It cannot judge how the result looks or behaves when it runs: "
              "run it and look at the output yourself.")

COMMON_GUIDE = "Look for correctness, security and error-handling problems in the changed lines."
PYTHON_GUIDE = (
    "Python: look for these when the changed code has them. Loops that search a list for each item of another list (quadratic: use a dict or a set). "
    "Fixed sets of strings used as statuses (use an Enum). Return types narrower than what is returned (json.load returns any JSON type, not only a dict). "
    "Substring tests used to parse values (\"GB\" in size also matches \"GBps\"). Averages of averages (weight them by count). Mutable default arguments. "
    "A bare except, or one that swallows errors. subprocess with shell=True and input that is not fixed. requests calls without a timeout. "
    "SQL built by string formatting. HTML built by string formatting from data (escape it with html.escape). Unused names, imports or functions. "
    "New functions without a docstring or header comment when the rest of the file has them."
)
POWERSHELL_GUIDE = (
    "PowerShell: look for these when the changed code has them (the names are PSScriptAnalyzer rules). Invoke-Expression on anything that is not fixed (AvoidUsingInvokeExpression). "
    "Passwords or secrets in plain text, ConvertTo-SecureString with -AsPlainText, parameters named Password or UserName instead of a PSCredential "
    "(AvoidUsingPlainTextForPassword, AvoidUsingConvertToSecureStringWithPlainText, AvoidUsingUsernameAndPasswordParams). Empty catch blocks (AvoidUsingEmptyCatchBlock), "
    "and commands inside try that do not use -ErrorAction Stop, so the catch never runs. Hard-coded computer names (AvoidUsingComputerNameHardcoded). "
    "Write-Host for output a caller may need: return objects instead (AvoidUsingWriteHost). Functions that change state without SupportsShouldProcess "
    "(UseShouldProcessForStateChangingFunctions). Unapproved verbs in function names (UseApprovedVerbs). Aliases and positional parameters in scripts "
    "(AvoidUsingCmdletAliases, AvoidUsingPositionalParameters). $null on the right-hand side of a comparison (PossibleIncorrectComparisonWithNull). "
    "Global variables (AvoidGlobalVars). Variables assigned and never used (UseDeclaredVarsMoreThanAssignments). "
    "Slow patterns: += on an array or a string inside a loop (use a List or -join), Where-Object over a large collection inside a loop (use a hashtable lookup), "
    "Export-Csv -Append inside ForEach-Object. New functions without comment-based help (ProvideCommentHelp)."
)
GUIDES = {"Python": PYTHON_GUIDE, "PowerShell": POWERSHELL_GUIDE}

FILE_SYSTEM = """You review one changed file of an Azure DevOps pull request. The file is shown as a diff: every line has its line number in the new version, a "+" marks a line this pull request added or changed, a "-" marks a line it removed, and unmarked lines are unchanged context.

Report only problems in the lines marked "+" (or that a removed line causes). Each finding must be something you can point to in the code shown. Do not report what you cannot see, style preferences, or anything already said in the existing comments.

Write each finding the way a good human reviewer does, in one to three sentences: what the code does wrong, the exact input or situation where it goes wrong and what happens, then what to change. Example: "`if 'GB' in size` also matches '10GBps' and treats it as a size. Match the whole unit, for example with a regular expression, and reject what is not a size."

Rules:
- "line" is the line number in the new version (the number at the start of a "+" line), the first changed line of the code you mean. "end_line" is the last line when the finding covers several lines, otherwise null.
- "severity": "critical" = a defect, security hole or data loss that will happen; "warning" = a likely bug or a real risk with a concrete failing case; "suggestion" = an improvement worth making. Never write praise.
- "category": correctness | security | performance | maintainability | test_coverage.
- "suggestion_code": only when you can give the exact replacement for lines "line" to "end_line": the code that should replace them, complete and valid for the file's language, without diff markers or line numbers. Otherwise null.
- Returning no findings is fine, and often right. Do not invent findings to fill space.

{guide}

Answer with JSON only: {{"purpose": "one sentence: what this change does in this file", "findings": [{{"line": 12, "end_line": null, "category": "correctness", "severity": "warning", "title": "short title", "comment": "the finding", "suggestion_code": null}}]}}"""

VERIFY_SYSTEM = """You check findings that another reviewer made about a changed file. The file is shown as a diff with line numbers ("+" = added or changed, "-" = removed). For each numbered finding decide whether it is really true of the code shown.

Set holds to false when: the code does not do what the finding says; the finding depends on code that is not shown; it is a preference rather than a defect with a concrete failing case; or the suggested replacement would not do what the finding says or would break the code. Be strict: a finding that cannot be shown from the code in front of you does not hold.

Answer with JSON only: {"findings": [{"number": 1, "holds": true, "reason": "one short sentence"}]}"""

DESCRIPTION_SYSTEM = """You compare the description of a pull request with what the pull request changes. You get the description and, for each changed file, one sentence about what changed in it.

List the substantial changes that the description does not mention at all. Leave a change out if the description covers it in any form, even briefly. Do not list formatting or small changes. If the description covers everything, or you are not sure, return an empty list. At most 3 items, each one sentence.

Answer with JSON only: {"missing_from_description": ["..."]}"""


class AiUnavailable(Exception):
    """The model is not configured or could not be started: there is no review to give."""


class ReviewFailed(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def get_model_client() -> PipelineRecommendationClient:
    settings = get_settings()
    endpoint = getattr(settings, "azure_openai_endpoint", None)
    deployment = getattr(settings, "azure_openai_deployment", None)
    if not endpoint or not deployment:
        raise AiUnavailable("Azure OpenAI is not configured (its endpoint and deployment are missing), so the AI review is unavailable. Nothing was reviewed.")
    try:
        return PipelineRecommendationClient(endpoint, deployment, getattr(settings, "azure_openai_api_version", "2024-02-01"), getattr(settings, "azure_openai_api_key", None) or None)
    except Exception as exc:
        logger.warning("Could not start the Azure OpenAI client for the PR review: %s", exc)
        raise AiUnavailable("The Azure OpenAI client could not be started, so the AI review is unavailable. Nothing was reviewed.") from exc


# ---------------------------------------------------------------- small helpers

def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _strip_fences(code: Any) -> str:
    body = str(code or "").strip("\n")
    body = re.sub(r"^```[\w+-]*\n", "", body)
    body = re.sub(r"\n```\s*$", "", body)
    return body.rstrip()


def _holds(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


# ---------------------------------------------------------------- existing comments

def thread_summaries(threads: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The comments people already made: what, where, by whom, and whether it is resolved. System messages are left out."""
    found = []
    for thread in threads or []:
        if thread.get("isDeleted"):
            continue
        comments = [c for c in thread.get("comments") or [] if c.get("commentType") != "system" and not c.get("isDeleted") and (c.get("content") or "").strip()]
        if not comments:
            continue
        context = thread.get("threadContext") or {}
        start = context.get("rightFileStart") or context.get("leftFileStart") or {}
        end = context.get("rightFileEnd") or context.get("leftFileEnd") or start
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", comments[0].get("content") or "")
        found.append({
            "path": (context.get("filePath") or "").lstrip("/"),
            "line": _int(start.get("line")), "end": _int(end.get("line")) or _int(start.get("line")),
            "status": thread.get("status") or "active",
            "author": ((comments[0].get("author") or {}).get("displayName") or "a reviewer"),
            "text": _text(text, 300),
        })
    return found


def _threads_for(summaries: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    return [t for t in summaries if t["path"] == path and t["line"] is not None]


def _existing_for(finding: dict[str, Any], threads: list[dict[str, Any]]) -> dict[str, Any] | None:
    first, last = finding["line_number"], finding["end_line"] or finding["line_number"]
    for thread in threads:
        if thread["line"] <= last + 2 and (thread["end"] or thread["line"]) >= first - 2:
            return thread
    return None


# ---------------------------------------------------------------- checking the findings

def clean_findings(raw: Any, view: FileView) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Keep the findings that point at lines this pull request changed. Returns (kept, [(title, why a finding was removed)])."""
    kept: list[dict[str, Any]] = []
    removed: list[tuple[str, str]] = []
    allowed = view.added | view.removed_at
    seen: set[tuple[int, str]] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 120) or "Review finding"
        severity = _text(item.get("severity"), 20).lower()
        if severity == "praise":
            continue
        body = _text(item.get("comment"), 900)
        if not body:
            removed.append((title, "it had no explanation"))
            continue
        line = _int(item.get("line"))
        if line is None or not 1 <= line <= view.new_line_count:
            removed.append((title, "it did not point at a line of the file"))
            continue
        end = _int(item.get("end_line")) or line
        end = line if end < line else min(end, view.new_line_count, line + MAX_SPAN - 1)
        if not any(n in allowed for n in range(line, end + 1)):
            removed.append((title, "it pointed at lines this pull request did not change"))
            continue
        key = (line, title.lower())
        if key in seen:
            continue
        seen.add(key)
        suggestion = _strip_fences(item.get("suggestion_code")) or None
        if suggestion and (not suggestable(view, line, end) or suggestion.strip() == "\n".join(view.new_lines[line - 1:end]).strip()):
            suggestion = None
        category = _text(item.get("category"), 30).lower()
        kept.append({
            "category": category if category in CATEGORIES else "maintainability",
            "severity": severity if severity in SEVERITIES else "suggestion",
            "title": title, "comment": body, "file_path": view.path, "language": view.language,
            "line_number": line, "end_line": end if end > line else None, "suggestion_code": suggestion,
            "existing_thread": None, "existing_status": None, "verified": None,
        })
    kept.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return kept, removed


def verify_findings(model: Any, view: FileView, findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """A second, sceptical read of each finding against the code. Findings it cannot confirm are removed; if the check cannot run they stay, marked unchecked."""
    if not findings:
        return findings, []
    lines = []
    for number, f in enumerate(findings, 1):
        where = f"line {f['line_number']}" + (f"-{f['end_line']}" if f["end_line"] else "")
        lines.append(f"{number}. {where}: {f['title']}. {f['comment']}" + (f"\n   Suggested replacement:\n{f['suggestion_code']}" if f["suggestion_code"] else ""))
    user = f"File: {view.path} ({view.language})\n\nFindings to check:\n" + "\n".join(lines) + f"\n\nThe file:\n\n{view.shown}"
    try:
        answer = with_retry(lambda: chat_json(model, VERIFY_SYSTEM, user, temperature=0))
    except Exception as exc:
        logger.warning("Second check of the findings in %s failed: %s", view.path, type(exc).__name__)
        return findings, []
    verdicts: dict[int, tuple[bool, str]] = {}
    for entry in answer.get("findings") if isinstance(answer.get("findings"), list) else []:
        if isinstance(entry, dict) and _int(entry.get("number")) is not None:
            verdicts[_int(entry["number"])] = (_holds(entry.get("holds")), _text(entry.get("reason"), 200))
    kept, removed = [], []
    for number, f in enumerate(findings, 1):
        verdict = verdicts.get(number)
        if verdict is None:
            kept.append(f)
        elif verdict[0]:
            f["verified"] = True
            kept.append(f)
        else:
            removed.append((f["title"], "it did not hold on a second check" + (f": {verdict[1]}" if verdict[1] else "")))
    return kept, removed


def file_prompt(view: FileView, pr: dict[str, Any], existing: list[dict[str, Any]]) -> str:
    if view.whole_file:
        shown = "the whole file"
    else:
        shown = "only the changed parts, with the lines around them" + ("; some changed parts are left out because the file is large" if view.omitted_hunks else "")
    comments = "\n".join(f"- line {t['line']} [{STATUS_WORDS.get(t['status'], t['status'])}] {t['author']}: {t['text']}" for t in existing[:12]) or "(none)"
    return (f"File: {view.path}\nLanguage: {view.language}\nChange: {view.change_type} (+{view.added_count} -{view.removed_count})\n"
            f"Pull request title: {pr['title']}\nPull request description (start): {pr['description'][:1200] or '(none)'}\n\n"
            f"Existing comments on this file (do not repeat them):\n{comments}\n\nThe file is shown as {shown}:\n\n{view.shown}")


def review_file(model: Any, view: FileView, pr: dict[str, Any], threads: list[dict[str, Any]]) -> dict[str, Any]:
    """Review one file: ask, check each finding in code, check again with a second call, and note what people already said."""
    existing = _threads_for(threads, view.path)
    system = FILE_SYSTEM.format(guide=GUIDES.get(view.language, COMMON_GUIDE))
    answer = with_retry(lambda: chat_json(model, system, file_prompt(view, pr, existing), temperature=0.1))
    findings, removed = clean_findings(answer.get("findings"), view)
    overflow = max(0, len(findings) - MAX_FINDINGS_PER_FILE)
    findings = findings[:MAX_FINDINGS_PER_FILE]
    findings, rejected = verify_findings(model, view, findings)
    for finding in findings:
        thread = _existing_for(finding, existing)
        if thread:
            finding["existing_status"] = thread["status"]
            finding["existing_thread"] = f"Already raised by {thread['author']} ({STATUS_WORDS.get(thread['status'], thread['status'])})"
    return {"purpose": _text(answer.get("purpose"), 200), "findings": findings, "removed": removed, "rejected": rejected, "overflow": overflow}


# ---------------------------------------------------------------- verdict, scorecard, summary

def judge(comments: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """The verdict and the scorecard, from the findings that are still open. A finding people already resolved does not count."""
    live = [c for c in comments if c.get("existing_status") not in RESOLVED]
    verdict = "CHANGES_REQUESTED" if any(c["severity"] == "critical" for c in live) else "APPROVED_WITH_SUGGESTIONS" if live else "APPROVED"
    scorecard = {}
    for category in CATEGORIES:
        severities = {c["severity"] for c in live if c["category"] == category}
        scorecard[category] = "CONCERNING" if "critical" in severities else "NEEDS_IMPROVEMENT" if "warning" in severities else "GOOD" if severities else "NO_FINDINGS"
    return verdict, scorecard


def summarize(files: list[dict[str, Any]], comments: list[dict[str, Any]], commit: str, iteration: int, iterations: int) -> str:
    reviewed = [f for f in files if f["status"] == "reviewed"]
    languages: dict[str, int] = {}
    for f in reviewed:
        languages[f["language"]] = languages.get(f["language"], 0) + 1
    where = f"commit {commit[:8]}" if commit else "the latest push"
    text = f"Reviewed {len(reviewed)} of {len(files)} changed files ({', '.join(f'{n} {k}' for k, n in sorted(languages.items())) or 'none'}) at {where}, push {iteration} of {iterations}."
    if not reviewed:
        return text + " Nothing could be reviewed; see the file list."
    if comments:
        counts = {s: sum(1 for c in comments if c["severity"] == s) for s in SEVERITIES}
        parts = [f"{n} {name}" for name, n in (("critical", counts["critical"]), ("warning" if counts["warning"] == 1 else "warnings", counts["warning"]), ("suggestion" if counts["suggestion"] == 1 else "suggestions", counts["suggestion"])) if n]
        text += f" {len(comments)} finding{'s' if len(comments) != 1 else ''}: {', '.join(parts)}."
        known = sum(1 for c in comments if c.get("existing_thread"))
        if known:
            text += f" {known} of them {'was' if known == 1 else 'were'} already raised in the pull request comments."
    else:
        text += " No findings in the files reviewed."
    skipped = len(files) - len(reviewed)
    if skipped:
        text += f" {skipped} file{'s were' if skipped != 1 else ' was'} not reviewed."
    return text


# ---------------------------------------------------------------- the service

class PullRequestReviewService:
    def __init__(self, ado: Any, model: Any):
        self.ado = ado
        self.model = model

    def _optional(self, notes: list[str], what: str, call: Callable[[], Any]) -> Any:
        try:
            return call()
        except Exception as exc:
            logger.info("PR review: %s could not be read (%s)", what, type(exc).__name__)
            notes.append(f"{what} could not be read, so it was not used. The token may lack the matching read scope.")
            return None

    def _texts(self, project: str, repo: str, entry: dict[str, Any], refs: dict[str, str]) -> tuple[str | None, str | None, str | None]:
        """(old text, new text, reason it cannot be read) for one change."""
        item = entry.get("item") or {}
        path = item.get("path") or ""
        change = str(entry.get("changeType") or "").lower()
        new_id, old_id = item.get("objectId"), item.get("originalObjectId")
        if new_id:
            new, why = self.ado.get_blob_text(project, repo, new_id, MAX_FILE_BYTES)
        else:
            new, why = self.ado.get_item_text(project, repo, path, refs["source"], MAX_FILE_BYTES) if refs.get("source") else (None, "unreadable")
        if new is None:
            return None, None, why or "unreadable"
        if "add" in change and not old_id:
            return "", new, None
        if old_id:
            old, why = self.ado.get_blob_text(project, repo, old_id, MAX_FILE_BYTES)
        else:
            old, why = self.ado.get_item_text(project, repo, item.get("path") or path, refs["common"], MAX_FILE_BYTES) if refs.get("common") else (None, "unreadable")
        if old is None:
            return None, None, "the earlier version could not be read"
        return old, new, None

    def review(self, project: str, repository_id: str, pull_request_id: int) -> dict[str, Any]:
        notes: list[str] = []
        pr = self.ado.get_pull_request(project, repository_id, pull_request_id)
        iterations = self.ado.get_pull_request_iterations(project, repository_id, pull_request_id)
        if not iterations:
            raise ReviewFailed("This pull request has no pushes to review yet.", 422)
        last = iterations[-1]
        refs = {"source": (last.get("sourceRefCommit") or {}).get("commitId") or "", "common": (last.get("commonRefCommit") or {}).get("commitId") or ""}
        entries = self.ado.get_all_pull_request_iteration_changes(project, repository_id, pull_request_id, last.get("id"))
        entries = [e for e in entries if (e.get("item") or {}).get("path") and not (e.get("item") or {}).get("isFolder")]
        if not entries:
            raise ReviewFailed("This pull request has no file changes to review.", 422)

        description = pr.get("description") or ""
        context = {"title": pr.get("title") or f"Pull request {pull_request_id}", "description": description}
        threads = thread_summaries(self._optional(notes, "The existing comments", lambda: self.ado.get_pull_request_threads(project, repository_id, pull_request_id)))
        work_items = self._optional(notes, "The linked work items", lambda: [str(w.get("id")) for w in self.ado.get_pull_request_work_items(project, repository_id, pull_request_id)])
        build_check = self._build_check(project, pr, description)

        files, views = self._plan(project, repository_id, entries, refs)
        results, failures = self._review_all(views, context, threads)
        for path, reason in failures.items():
            self._mark(files, path, "skipped", reason)
        if views and not results:
            raise ReviewFailed("The AI could not review any file: " + (next(iter(failures.values()), "unknown error")) + ". Nothing was reviewed.", 502)

        comments: list[dict[str, Any]] = []
        removed_total: dict[str, int] = {}
        rejected: list[str] = []
        for view in views:
            result = results.get(view.path)
            if not result:
                continue
            row = next(f for f in files if f["path"] == view.path)
            row.update(status="reviewed", findings=len(result["findings"]), purpose=result["purpose"] or None)
            comments.extend(result["findings"])
            for _, reason in result["removed"] + result["rejected"]:
                key = "pointed at lines this pull request did not change" if "did not change" in reason else "did not hold on a second check" if "second check" in reason else "were malformed"
                removed_total[key] = removed_total.get(key, 0) + 1
            for title, reason in result["rejected"]:
                detail = reason.split(": ", 1)[1] if ": " in reason else ""
                rejected.append(f"{view.path}: {title}" + (f" ({detail})" if detail else ""))
            if result["overflow"]:
                notes.append(f"{result['overflow']} lower-priority finding(s) in {view.path} are not shown (limit {MAX_FINDINGS_PER_FILE} per file).")
            if view.omitted_hunks:
                notes.append(f"{view.path} is large: {view.omitted_hunks} changed part(s) at the end were not reviewed.")
        for number, comment in enumerate(comments, 1):
            comment["id"] = f"pr-{pull_request_id}-{number}"
        if removed_total:
            notes.append("Removed before showing: " + "; ".join(f"{n} finding(s) {why}" for why, n in removed_total.items()) + ".")
        notes.extend(f"Removed on a second check: {line}" for line in rejected[:5])
        if sum(1 for c in comments if c["verified"] is None):
            notes.append("The second check could not run for some findings; they are marked as not double-checked.")

        clarifications = self._description_gaps(files, description)
        evidence = {"changed_paths": [f["path"] for f in files], "work_items": work_items, "build_check": build_check}
        checklist = evaluate_checklist(parse_checklist(description), evidence)
        verdict, scorecard = judge(comments)
        if not any(f["status"] == "reviewed" for f in files):
            verdict = "NOT_REVIEWED"
        return {
            "pull_request_id": pull_request_id, "verdict": verdict, "summary": summarize(files, comments, refs["source"], int(last.get("id") or len(iterations)), len(iterations)),
            "scorecard": scorecard, "comments": comments, "clarifications": clarifications, "posted_to_ado": False,
            "method": "diff-per-file", "source_commit": refs["source"] or None, "iterations": len(iterations),
            "files": files, "checklist": checklist, "notes": notes, "scope_note": SCOPE_NOTE,
        }

    # ------------------------------------------------------------ steps

    def _build_check(self, project: str, pr: dict[str, Any], description: str) -> dict[str, Any] | None:
        linked = linked_build_ids(description)
        if not linked:
            return None
        try:
            newest_linked = max(linked)
            build = self.ado.get_build(project, newest_linked)
            definition = build.get("definition") or {}
            runs = self.ado.list_builds_for_branch(project, pr.get("sourceRefName") or "", 30)
            newer = next((r for r in runs if (r.get("definition") or {}).get("id") == definition.get("id") and int(r.get("id") or 0) > newest_linked), None)
            return {"linked_id": newest_linked, "pipeline": definition.get("name"), "newer_id": newer.get("id") if newer else None, "newer_result": (newer or {}).get("result")}
        except Exception as exc:
            logger.info("PR review: the linked run could not be compared (%s)", type(exc).__name__)
            return {"error": True}

    def _plan(self, project: str, repo: str, entries: list[dict[str, Any]], refs: dict[str, str]) -> tuple[list[dict[str, Any]], list[FileView]]:
        files: list[dict[str, Any]] = []
        candidates: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for entry in entries:
            path = (entry.get("item") or {}).get("path", "").lstrip("/")
            change = str(entry.get("changeType") or "edit")
            language, reason = classify(path, change)
            row = {"path": path, "language": language, "change_type": change.split(",")[0].strip().lower() or "edit", "status": "skipped", "reason": reason, "findings": 0, "purpose": None}
            files.append(row)
            if language:
                candidates.append((row, entry, language))
        candidates.sort(key=lambda c: priority(c[2], c[0]["path"]))
        views: list[FileView] = []
        for number, (row, entry, language) in enumerate(candidates):
            if number >= MAX_FILES:
                row["reason"] = f"over the limit of {MAX_FILES} files reviewed in one go"
                continue
            old, new, why = self._texts(project, repo, entry, refs)
            if new is None:
                row["reason"] = {"too_large": f"larger than {MAX_FILE_BYTES // 1000} KB", "binary": "not a text file"}.get(why or "", why or "could not be read")
                continue
            try:
                view = build_view(row["path"], language, row["change_type"], old, new)
            except ValueError as exc:
                row["reason"] = f"too long to compare ({exc})"
                continue
            if not view.has_changes:
                row["reason"] = "no change in the content"
                continue
            row["reason"] = None
            views.append(view)
        return files, views

    def _review_all(self, views: list[FileView], context: dict[str, Any], threads: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        results: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        if not views:
            return results, failures

        deadline = time.monotonic() + REVIEW_BUDGET_SECONDS

        def one(view: FileView) -> tuple[str, dict[str, Any] | None, str]:
            if time.monotonic() > deadline:
                return view.path, None, "not reached in the time allowed"
            try:
                return view.path, review_file(self.model, view, context, threads), ""
            except Exception as exc:
                logger.warning("PR review: the AI call for %s failed (%s)", view.path, type(exc).__name__)
                return view.path, None, "the AI call failed"

        with ThreadPoolExecutor(max_workers=min(WORKERS, len(views))) as pool:
            for path, result, reason in pool.map(one, views):
                if result is not None:
                    results[path] = result
                else:
                    failures[path] = reason
        return results, failures

    @staticmethod
    def _mark(files: list[dict[str, Any]], path: str, status: str, reason: str) -> None:
        for row in files:
            if row["path"] == path:
                row["status"], row["reason"] = status, reason

    def _description_gaps(self, files: list[dict[str, Any]], description: str) -> list[str]:
        purposes = [f"{f['path']}: {f['purpose']}" for f in files if f["status"] == "reviewed" and f["purpose"]]
        if not description.strip() or not purposes:
            return []
        user = f"Pull request description:\n{description[:3000]}\n\nChanged files:\n" + "\n".join(purposes)
        try:
            answer = with_retry(lambda: chat_json(self.model, DESCRIPTION_SYSTEM, user, temperature=0))
        except Exception as exc:
            logger.info("PR review: the description check failed (%s)", type(exc).__name__)
            return []
        gaps = answer.get("missing_from_description")
        return [f"The description does not mention: {_text(g, 200)}" for g in (gaps if isinstance(gaps, list) else [])[:3] if _text(g, 200)]

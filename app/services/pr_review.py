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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from app.core.config import get_settings
from app.services.llm_util import chat_json, chat_json_with_tools, with_retry
from app.services.pr_arm import ARM_LANGUAGE, ARM_LINE_WIDTH, arm_context, is_arm_template
from app.services.pr_checklist import evaluate_checklist, linked_build_ids, parse_checklist, placeholder_checks
from app.services import pr_knowledge
from app.services.pr_diff import LINE_WIDTH, FileView, build_view, classify, priority, suggestable
from app.services.pr_lookup import TOOLS, RepoReader, ToolBelt, csharp_facts
from app.services.pr_static import static_findings
from core.openai_client import PipelineRecommendationClient

logger = logging.getLogger(__name__)

MAX_FILES = 50
MAX_FINDINGS_PER_FILE = 8
EVIDENCE_SHOWN_CHARS = 360  # of the quoted code shown with a finding (the whole quote is checked against the file first)
MAX_SPAN = 40
WORKERS = 5
MAX_FILE_BYTES = 1_000_000
MAX_EXAMINED = 150  # files looked at in one review, whether or not they turn out to be reviewable
MAX_VERIFY_TURNS = 6  # model calls in one second check (lookups included); the last one must answer
MAX_OTHER_FILES = 40  # names of the pull request's other changed files that the reviewer is told about
MAX_DESCRIPTION_CHARS = 8000  # of the pull request description, after the checklist lines are taken out
MAX_FILE_COMMENTS = 12  # existing comments on a file that the reviewer is told about
MAX_GENERAL_COMMENTS = 10  # existing comments on the pull request as a whole
MIN_CASE_CHARS = 20  # a concrete case is at least a short sentence
MIN_EVIDENCE_CHARS = 6  # of quoted code, ignoring spaces, for a piece of evidence to count
REVIEW_BUDGET_SECONDS = 170  # a review answered inside one web request: Azure App Service ends a request after 230 s, so a slow model gives a partial review, not a timeout
BACKGROUND_BUDGET_SECONDS = 600  # a review that runs in the background (see pr_review_jobs) has no request to keep alive
CATEGORIES = ("correctness", "security", "performance", "maintainability", "test_coverage")
SOFT_CATEGORIES = ("maintainability", "test_coverage")  # findings here are capped at "suggestion"
SEVERITIES = ("critical", "warning", "suggestion")
RESOLVED = {"fixed", "closed", "wontFix", "byDesign"}
STATUS_WORDS = {"active": "open", "pending": "pending", "fixed": "resolved", "closed": "closed", "wontFix": "won't fix", "byDesign": "by design"}

SCOPE_NOTE = ("This review reads the code changes only. It cannot judge how the result looks or behaves when it runs: "
              "run it and look at the output yourself.")

COMMON_GUIDE = "Look for correctness, security and error-handling problems in the changed lines."
CSHARP_GUIDE = (
    "C#: look for these when the changed code has them. An empty catch, or a catch of Exception that hides the cause. async code that blocks with .Result or .Wait() (it can deadlock), "
    "async void outside an event handler, a Task that is not awaited. IDisposable objects (streams, connections, an HttpClient created for each call) that are not disposed. "
    "SQL built by string concatenation instead of parameters. Secrets or connection strings written in the code. DateTime.Now where UTC is needed. "
    "A query or loop over database results with no limit. lock on this or on a public object. Mutable static state shared between requests. "
    "Use the project facts you are given: syntax that the project's C# version supports is valid, so never call it invalid."
)
MARKDOWN_GUIDE = (
    "Markdown: look for content this change removed that the rest of the document still depends on (a heading that other text or a link points to, a table row, a step that later steps need), "
    "instructions or commands that no longer match each other, links to files or anchors this change broke, and a code block that is opened and never closed. "
    "Do not comment on wording, spelling or style."
)
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
ARM_GUIDE = (
    "Azure Monitor alerts in an ARM template: you are also given each alert in plain words and what changed in it. Look for these when the changed lines touch them, "
    "and say what now fires or stops firing for a concrete case. A changed threshold, operator, windowSize, evaluationFrequency, failingPeriods or query that changes when the alert fires. "
    "minFailingPeriodsToAlert larger than numberOfEvaluationPeriods (it must be smaller or equal). overrideQueryTimeRange, which replaces the default query time range "
    "(windowSize times numberOfEvaluationPeriods). An alert runs again and again: every evaluationFrequency it reads the last windowSize of data. "
    "A time filter inside the query that is shorter than the time between runs can skip events that fall between two runs. A window that is shorter than what the query looks back over hides the part beyond the window. "
    "A time filter that is shorter than the window is normal: it reports each event on the runs where the event passes the filter, and an event that is outside the filter on a later run was already seen by an earlier run, so that is not a missed alert. "
    "Use the timing facts you are given for each alert; do not work the timing out yourself. "
    "A log alert meant to detect a lack of data: Microsoft says logs are more latent than metrics and recommends a metric alert for that. "
    "A severity that does not match what the alert is for (0 is the most severe, 4 the least). enabled set to false, no action group (nobody is notified), "
    "muteActionsDuration that hides repeats, autoMitigate set to false so the alert never resolves by itself, skipQueryValidation set to true. "
    "A resource group scope with targetResourceTypes (one alert per resource of that type). A metric alert with several conditions fires only when all of them are true. "
    "Query mistakes: a table or column the query does not have, a filter that can never match, a count compared with a threshold meant for a measure column. "
    "Secrets: a parameter that holds a password or key must be securestring, and a secure value set on a property that does not expect one (a tag, for example) is stored as plain text; "
    "secure values must not be outputs. Other ARM templates: the same secrets rule, and hard-coded subscription or resource ids that tie the template to one environment. "
    "Facts from Microsoft's documentation, which are true and must not be reported as mistakes: in the older 2018-04-16 format of a log alert (a resource of type Microsoft.Insights/scheduledQueryRules with a source and a schedule), "
    "the value of source.queryType is ResultCount; timeWindowInMinutes must be greater than or equal to frequencyInMinutes; and autoMitigate is false unless it is set (in the newer format it is true unless it is set)."
)
KQL_GUIDE = (
    "KQL: look for a missing or misplaced time filter, a join that multiplies rows, a column or table the query does not have, a filter that can never match, "
    "results that are not bounded, and a summarize or threshold that does not measure what its name says."
)
SQL_GUIDE = (
    "SQL: look for these when the changed code has them. A column or alias that is labeled differently from the same column in other parts of the same query (the other branches of a UNION, the other rows or buckets): "
    "before you say a value is mislabeled, find how the rest of the query labels the same thing and follow that convention. UPDATE or DELETE without a WHERE. A function applied to a column in a WHERE clause, "
    "which stops an index from being used. Dynamic SQL built by joining strings instead of parameters. Local time (GETDATE) where UTC is meant, or the reverse. "
    "A header comment that contradicts the code beside it (a name, a parameter, or a last-modified date earlier than the created date). Do not report formatting."
)
GUIDES = {"Python": PYTHON_GUIDE, "PowerShell": POWERSHELL_GUIDE, ARM_LANGUAGE: ARM_GUIDE, "KQL": KQL_GUIDE, "C#": CSHARP_GUIDE, "Markdown": MARKDOWN_GUIDE, "SQL": SQL_GUIDE}

FILE_SYSTEM = """You review one changed file of an Azure DevOps pull request. The file is shown as a diff: every line has its line number in the new version, a "+" marks a line this pull request added or changed, a "-" marks a line it removed, and unmarked lines are unchanged context.

Report only problems in the lines marked "+" (or that a removed line causes). Each finding must be something you can point to in the code shown. Do not report what you cannot see, style preferences, or anything already said in the existing comments.

Write each finding the way a good human reviewer does, in one to three sentences: what the code does wrong, the exact input or situation where it goes wrong and what happens, then what to change. Example: "`if 'GB' in size` also matches '10GBps' and treats it as a size. Match the whole unit, for example with a regular expression, and reject what is not a size."

Rules:
- "line" is the line number in the new version (the number at the start of a "+" line), the first changed line of the code you mean. "end_line" is the last line when the finding covers several lines, otherwise null.
- "severity": "critical" = a defect, security hole or data loss that will happen; "warning" = a likely bug or a real risk with a concrete failing case; "suggestion" = an improvement worth making. Never write praise.
- "category": correctness | security | performance | maintainability | test_coverage.
- "suggestion_code": only when you can give the exact replacement for lines "line" to "end_line": the code that should replace them, complete and valid for the file's language, without diff markers or line numbers. Otherwise null.
- "failing_case" (required): one sentence with the concrete input or situation and the wrong result it produces. A guess is not a case: do not use "may", "might", "could", "possibly" or "if these differ". If you cannot state a case, leave the finding out.
- "evidence" (required): the exact code your finding relies on, copied character for character from the file shown, without the line numbers and the + or - marks. Use ... between separate pieces. If you cannot quote it, leave the finding out.
- Do not ask the author to verify or confirm something. State a defect you can show, or leave the finding out.
- If the pull request description, a comment in the code, a name in the code or the alert's own description says a behaviour is intended, do not report it unless you can show a concrete case where it gives a wrong result.
- Report each problem once. If the same problem appears on several lines, write one finding (use end_line, or name the other lines in the text), not one per line.
- You see this one file only. Do not report what might be wrong in other files, a name you cannot see defined, or code you cannot see: the other files of this pull request are listed only so you know they exist.
- Do not report that code will not compile or has a syntax error: the build checks that. Believe the project facts and today's date you are given: a date on or before today is not in the future, and syntax that the project's language version supports is valid.
- Before you say a name, label, order or value is wrong, find how the rest of the file does the same thing, and follow the file's own convention. Do not report a difference from your own preference.
- If the description says some code was only moved, renamed or brought into the repository and its logic is unchanged, do not report problems in that logic; report only what the move or rename broke.
- Never write that there is no failing case: a finding without one is left out.
- Returning no findings is fine, and often right. Do not invent findings to fill space.

{guide}

Answer with JSON only: {{"purpose": "one sentence: what this change does in this file", "findings": [{{"line": 12, "end_line": null, "category": "correctness", "severity": "warning", "title": "short title", "comment": "the finding", "failing_case": "the concrete input or situation and the wrong result", "evidence": "the exact code it relies on", "suggestion_code": null, "kb": null}}]}}
("kb" is the number of the team's check a finding comes from, only when the message lists the team's checks; otherwise null.)"""

VERIFY_SYSTEM = """You check findings that another reviewer made about a changed file. The file is shown as a diff with line numbers ("+" = added or changed, "-" = removed). For each numbered finding decide whether it is really true of the code shown.

You are also given the author's description of the change and the comments people already made. Use them.

Each finding comes with the concrete case it claims and the code it quotes. Trace the case through the code yourself before you agree: follow the values it depends on (for example which columns each step of a query outputs, which rows a filter keeps, or how often the rule runs compared with the window it reads) and see whether the case really happens.

Set holds to false when: the code does not do what the finding says; the case it gives does not happen when you trace it through the code; the finding depends on code that is not shown; it is a preference rather than a defect with a concrete failing case; the suggested replacement would not do what the finding says or would break the code; the finding only says that something could, may or might go wrong, without showing a concrete input or situation in the code; or the description, a comment in the code or the alert's own description says the behaviour is intended and the finding does not show a case where it gives a wrong result. Be strict: a finding that cannot be shown from the code in front of you does not hold.

Also set duplicate_of to the number of an EARLIER finding that describes the same problem (even on a different line), otherwise null. Set already_raised_by to the E-number (for example "E2") of an existing comment that already makes the same point, whatever line it is on, otherwise null.

Believe the project facts and today's date you are given. A finding that says code will not compile or has a syntax error does not hold unless the project facts show the syntax is newer than the project's language version.

Some findings come from "Team check" lines: a check the team wrote because it matters to them. Such a finding holds when the changed code really breaks the stated check and the case shows where; it does not hold when the code does not break it. The team's check does not excuse a finding that the code contradicts.

You may also be given findings already made by exact checks in code (S1, S2, ...). Set already_found_by_code to the S-number when a finding describes the same defect as one of them, otherwise null.

Answer with JSON only: {"findings": [{"number": 1, "holds": true, "reason": "one short sentence", "duplicate_of": null, "already_raised_by": null, "already_found_by_code": null}]}"""

REFUTE_SYSTEM = """You are a sceptical senior engineer. Reviewers made the numbered findings below about a changed file. A first check already agreed with them. Your job is the opposite: for each finding, assume it is WRONG and try to prove that from what is in front of you.

Look at how the rest of the file handles the same thing (other parts of a query or class, neighbouring rows, other branches, the same column or name elsewhere), at the facts you are given (today's date, the project's language version, the alert timing facts) and at what a lookup returns. Think about when the code runs and what ran before. A comment, a name or the author's description shows what the author INTENDED, not what the code does: never use one of them as the reason a finding is wrong. To show a finding is wrong, quote code (or a lookup result) that makes its concrete case impossible. Argue from the code, never from opinion.

If you cannot find anything that shows it is wrong, say so: wrong is false.

Answer with JSON only: {"findings": [{"number": 1, "wrong": false, "because": "one short sentence", "quote": "the exact code that makes the finding's case impossible, or empty"}]}"""

KB_PR_SYSTEM = """You check a pull request against checks the team wrote about pull requests themselves (not about code). You get the numbered checks, the pull request description, the list of changed files and the comments people already made.

For each check decide whether this pull request breaks it, using only what you are given. If it cannot be judged from that, breaks is null. If it breaks the check, quote the exact words of the description, or the exact path of a changed file, that show it. Do not guess and do not ask the author to confirm anything.

Answer with JSON only: {"checks": [{"number": 1, "breaks": false, "because": "one short sentence", "quote": "exact words or path, or empty"}]}"""

VERIFY_TOOLS = """

You can look things up before you decide, with the tools find_files, read_file and search_code. They read the whole repository at the commit being reviewed, not only this pull request's files. Use them for what a finding depends on that the file shown does not settle: the project's target framework, whether a setting or a name is defined or used elsewhere, what another file of this pull request really contains. Do not use them for what the file already shows. Look first, then answer; at most a few lookups are needed.

A finding that depends on code you cannot see, and that your lookups did not confirm, does not hold. A search tells you how many files it searched: when it did not search them all, finding nothing does not prove the text is absent. Never agree with a finding only because it sounds plausible."""

DESCRIPTION_SYSTEM = """You compare the description of a pull request with what the pull request changes. You get the description and, for each changed file, one sentence about what changed in it.

List the substantial changes that the description does not mention at all. Leave a change out if the description covers it in any form, even briefly (a rename of a file also covers the references that were updated for it). Do not list formatting or small changes. If the description covers everything, or you are not sure, return an empty list. At most 3 items, each one sentence.

For each change, look for the sentence of the description that covers it. If there is one, copy it exactly into "description_mentions"; if there is none, write null.

Answer with JSON only: {"missing_from_description": [{"change": "one sentence", "description_mentions": null}]}"""


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


# ---------------------------------------------------------------- the author's explanation

_CHECKBOX_LINE = re.compile(r"^[ \t]*[-*][ \t]*\[[ xX]\].*$", re.MULTILINE)


def clean_description(text: str | None, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """The author's explanation of the change. The checklist lines (which the code reads itself), images and HTML comments are taken out so
    that the words that explain the change fit; what is still too long is cut at the end and says so."""
    body = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = _CHECKBOX_LINE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body if len(body) <= limit else body[:limit].rstrip() + "\n... (the rest of the description is cut)"


# ---------------------------------------------------------------- existing comments

def _plain(content: Any) -> str:
    return _text(re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", str(content or "")), 300)


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
        reply = comments[-1] if len(comments) > 1 else None  # the last word in the discussion, for example "will be done in a later work item"
        found.append({
            "path": (context.get("filePath") or "").lstrip("/"),
            "line": _int(start.get("line")), "end": _int(end.get("line")) or _int(start.get("line")),
            "status": thread.get("status") or "active",
            "author": ((comments[0].get("author") or {}).get("displayName") or "a reviewer"),
            "text": _plain(comments[0].get("content")),
            "reply": _plain(reply.get("content"))[:200] if reply else "",
            "reply_author": ((reply.get("author") or {}).get("displayName") or "someone") if reply else "",
        })
    return found


def context_threads(summaries: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    """What the reviewer is told people already said: the comments on this file, then the comments on the pull request as a whole."""
    on_file = [{**t, "general": False} for t in summaries if t["path"] == path][:MAX_FILE_COMMENTS]
    general = [{**t, "general": True} for t in summaries if not t["path"]][:MAX_GENERAL_COMMENTS]
    return on_file + general


def comments_block(existing: list[dict[str, Any]]) -> str:
    """The existing comments as numbered lines (E1, E2, ...) so the second check can say which one a finding repeats."""
    lines = []
    for number, t in enumerate(existing, 1):
        where = "(on the pull request as a whole)" if t["general"] else f"line {t['line']}" if t["line"] else "(on the file)"
        reply = f" | last reply from {t['reply_author']}: {t['reply']}" if t.get("reply") else ""
        lines.append(f"E{number}: {where} [{STATUS_WORDS.get(t['status'], t['status'])}] {t['author']}: {t['text']}{reply}")
    return "\n".join(lines) or "(none)"


def _existing_for(finding: dict[str, Any], threads: list[dict[str, Any]]) -> dict[str, Any] | None:
    first, last = finding["line_number"], finding["end_line"] or finding["line_number"]
    for thread in threads:
        if thread["general"] or thread["line"] is None:
            continue
        if thread["line"] <= last + 2 and (thread["end"] or thread["line"]) >= first - 2:
            return thread
    return None


def _mark_existing(finding: dict[str, Any], thread: dict[str, Any]) -> None:
    finding["existing_status"] = thread["status"]
    finding["existing_thread"] = f"Already raised by {thread['author']} ({STATUS_WORDS.get(thread['status'], thread['status'])})"


# ---------------------------------------------------------------- checking the findings

_HEDGE = re.compile(r"\b(may|might|could|potentially|possibly|perhaps|probably)\b", re.IGNORECASE)
_ASK = re.compile(r"\b(?:verify|confirm|double[- ]check)\s+(?:that|whether|if|the|this|these|it)\b|\b(?:make|be) sure (?:that|this|it)\b|\bis (?:this|that|it) (?:intended|expected|deliberate)\b|\bplease (?:confirm|verify|check)\b", re.IGNORECASE)
_LINE_MARKS = re.compile(r"^[ \t]*(?:[+\-]?[ \t]*\d+|-)[ \t]*\|[ \t]?", re.MULTILINE)  # "+  17 | code", "   17 | code" or, for a removed line, "-      | code"
# The review cannot compile anything (the build does), and a model that has not seen newer syntax calls it invalid.
_COMPILE = re.compile(r"\b(?:will|would|does|do|did|can|could)(?:\s+not|n't)\s+compile\b|\bcompil(?:e|ation)[- ](?:time )?(?:error|fail\w*)\b|\bsyntax error\b|\b(?:not valid|invalid) (?:C#|(?:Python|PowerShell|syntax)\b)|"
                      r"\bCS\d{4}\b|\bfails? to (?:compile|build|parse)\b", re.IGNORECASE)
# A case that only exists if code in another file is wrong ("if X is not defined elsewhere") cannot be shown from this file: a lookup has to confirm it.
# (A dot inside a name, as in appsettings.json, does not end the sentence.)
# A finding whose own "case" says it has none (it was written to fill space).
_NO_CASE = re.compile(r"^\s*(?:none|n/?a|not applicable)\b|\bno (?:failing|concrete|specific|real|actual) (?:case|input|scenario|example)\b|\bthere is no (?:failing|concrete|specific|real|actual)\b", re.IGNORECASE)
_CONDITIONAL = re.compile(r"\bif\b(?:[^.;]|\.(?=\w)){0,120}?\b(?:not (?:been )?(?:defined|declared|imported|registered|updated|renamed)|still (?:uses?|used|refers?|references?|calls?|expects?)|elsewhere|differs?|differing|mismatch\w*|"
                          r"(?:other|another|different) (?:files?|places?|projects?|modules?|classes|usages?))\b", re.IGNORECASE)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _quoted(value: Any) -> str:
    """The evidence as text, without the line numbers and marks of the diff view if the model copied them."""
    raw = " ... ".join(str(v) for v in value) if isinstance(value, list) else str(value or "")
    return _text(_LINE_MARKS.sub("", raw), 900)


def _grounded(evidence: str, haystack: str) -> bool | None:
    """True when every piece of the quoted code (pieces are separated by ...) is in the file, ignoring spaces; None when there is nothing to check."""
    pieces = [p for p in (_compact(p) for p in re.split(r"\.\.\.|…", evidence)) if len(p) >= MIN_EVIDENCE_CHARS]
    return all(p in haystack for p in pieces) if pieces else None


def _touches_change(evidence: str, changed: str) -> bool:
    """True when at least one piece of the quoted code is a line this pull request added, changed or removed."""
    pieces = [p for p in (_compact(p) for p in re.split(r"\.\.\.|…", evidence)) if len(p) >= MIN_EVIDENCE_CHARS]
    return any(p in changed for p in pieces)


def unfounded(title: str, body: str, case: str, evidence: str, haystack: str, changed: str | None = None) -> str | None:
    """Why a finding is only a guess, or None. A finding must show a concrete case, quote the code it relies on, and state a defect rather than
    ask the author to confirm something. This is enforced here because asking the model to do it in a prompt was not enough. `changed` is the
    compact text of the lines this pull request changed: a finding has to rest on at least one of them."""
    if len(case) < MIN_CASE_CHARS or _NO_CASE.search(case):
        return "it showed no concrete case"
    guess = _HEDGE.search(case)
    if guess:
        return f"its case was a guess ('{guess.group(1).lower()}')"
    if _COMPILE.search(f"{title} {body} {case}"):
        return "it claimed a compile or syntax error, which only the build can show"
    if _ASK.search(title) or _ASK.search(body):
        return "it asked the author to confirm something instead of showing a defect"
    found = _grounded(evidence, haystack)
    if found is None:
        return "it did not quote the code it relies on"
    if not found:
        return "the code it quoted is not in the file"
    if changed is not None and not _touches_change(evidence, changed):
        return "all the code it quoted is unchanged context"
    return None


def _shorten(text: str, limit: int = EVIDENCE_SHOWN_CHARS) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def clean_findings(raw: Any, view: FileView, kb: dict[int, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Keep the findings that point at lines this pull request changed and are not guesses. Returns (kept, [(title, why a finding was removed)]).
    `kb` maps the number of each team check given to the reviewer to the check; a finding may name the one it comes from."""
    kb = kb or {}
    kept: list[dict[str, Any]] = []
    removed: list[tuple[str, str]] = []
    allowed = view.added | view.removed_at
    haystack = _compact("\n".join(r.text for r in view.rows) + "\n" + view.extra)
    changed = _compact("\n".join(r.text for r in view.rows if r.kind != "keep") + "\n" + view.extra)  # the alert details count as changed: they are about the changed rule
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
        case, evidence = _text(item.get("failing_case"), 400), _quoted(item.get("evidence"))
        guess = unfounded(title, body, case, evidence, haystack, changed)
        if guess:
            removed.append((title, guess))
            continue
        key = (line, title.lower())
        if key in seen:
            continue
        seen.add(key)
        suggestion = _strip_fences(item.get("suggestion_code")) or None
        if suggestion and (not suggestable(view, line, end) or suggestion.strip() == "\n".join(view.new_lines[line - 1:end]).strip()):
            suggestion = None
        category = _text(item.get("category"), 30).lower()
        category = category if category in CATEGORIES else "maintainability"
        severity = severity if severity in SEVERITIES else "suggestion"
        if category in SOFT_CATEGORIES:  # naming, structure, style and missing tests are suggestions, never warnings or blockers
            severity = "suggestion"
        team = kb.get(_int(item.get("kb")) or 0)  # a number the reviewer was not given is ignored
        kept.append({
            "category": category, "severity": severity,
            "title": title, "comment": body, "file_path": view.path, "language": view.language,
            "line_number": line, "end_line": end if end > line else None, "suggestion_code": suggestion,
            "failing_case": case, "evidence": _shorten(evidence),
            "existing_thread": None, "existing_status": None, "verified": None, "source": "ai", "checked_with": [],
            "knowledge": team["text"] if team else None, "knowledge_number": team["number"] if team else None,
            "needs_lookup": bool(_CONDITIONAL.search(case)),
        })
    kept.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return kept, removed


REMOVAL_GROUPS = (
    ("did not change", "pointed at lines this pull request did not change"),
    ("contradicts it", "were contradicted by code the second check quoted"),
    ("exact check", "repeated a finding made by an exact check in code"),
    ("second check", "did not hold on a second check"),
    ("repeats", "repeated another finding"),
    ("no concrete case", "showed no concrete case"),
    ("was a guess", "only guessed at a case"),
    ("compile or syntax", "claimed a compile or syntax error, which only the build can show"),
    ("asked the author", "asked the author to confirm something instead of showing a defect"),
    ("unchanged context", "quoted only code this pull request did not change"),
    ("outside this file", "depended on code outside the file that no lookup confirmed"),
    ("quote", "relied on code that is not in the file"),
)
GUESS_GROUPS = {"showed no concrete case", "only guessed at a case", "claimed a compile or syntax error, which only the build can show", "asked the author to confirm something instead of showing a defect",
                "quoted only code this pull request did not change", "depended on code outside the file that no lookup confirmed", "relied on code that is not in the file"}


def removal_group(reason: str) -> str:
    return next((group for needle, group in REMOVAL_GROUPS if needle in reason), "were malformed")


NEEDS_LOOKUP = "it depended on code outside this file, and no lookup confirmed it"


def _number(value: Any) -> int | None:
    """3 for 3, "3" or "E3"; None for anything else."""
    if value is None or isinstance(value, bool) or value == "":  # not `value in (False, True)`: 1 == True
        return None
    found = re.search(r"\d+", str(value))
    return int(found.group()) if found else None


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def facts_block(view: FileView) -> str:
    """What is known for certain about the file's setting: today's date and, for a file that belongs to a project, what its project files say."""
    return f"Today's date: {today()}" + (f"\n{view.facts}" if view.facts else "")


def _finding_lines(findings: list[dict[str, Any]]) -> str:
    lines = []
    for number, f in enumerate(findings, 1):
        where = f"line {f['line_number']}" + (f"-{f['end_line']}" if f["end_line"] else "")
        lines.append(f"{number}. {where}: {f['title']}. {f['comment']}\n   Its case: {f['failing_case']}\n   The code it relies on: {f['evidence']}"
                     + (f"\n   Team check: {f['knowledge']}" if f.get("knowledge") else "")
                     + (f"\n   Suggested replacement:\n{f['suggestion_code']}" if f["suggestion_code"] else ""))
    return "\n".join(lines)


def verify_findings(model: Any, view: FileView, findings: list[dict[str, Any]], pr: dict[str, Any] | None = None,
                    existing: list[dict[str, Any]] | None = None, belt: ToolBelt | None = None,
                    exact: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """A second, sceptical read of each finding against the code, the author's description and the comments already made. With a `belt` the
    check may also look things up in the repository. Findings it cannot confirm, and findings that repeat an earlier one, are removed; one that an
    existing comment already makes is marked as such, and one that repeats a finding the exact checks in code already made (`exact`) is dropped.
    A finding that depends on code outside the file stays only if a lookup was made. If the check cannot run the findings stay, marked unchecked
    (except those that need a lookup)."""
    if not findings:
        return findings, []
    pr, existing, exact = pr or {}, existing or [], exact or []
    alerts = f"\n\nThe alert rules, read from the template:\n{view.extra}" if view.extra else ""
    why = f"Why the author made this change (the pull request title and description):\n{pr.get('title', '')}\n{pr.get('description') or '(no description)'}\n\n"
    others = f"Other files changed in this pull request: {', '.join(pr['others'])}\n\n" if pr.get("others") else ""
    by_code = ("Findings already made by exact checks in code:\n" + "\n".join(f"S{n}: line {s['line_number']}: {s['title']}" for n, s in enumerate(exact, 1)) + "\n\n") if exact else ""
    user = (f"File: {view.path} ({view.language})\n{facts_block(view)}\n\n{why}{others}Comments people already made:\n{comments_block(existing)}\n\n{by_code}"
            "Findings to check:\n" + _finding_lines(findings) + alerts + f"\n\nThe file:\n\n{view.shown}")

    def ask() -> dict[str, Any]:
        if belt is not None:
            return chat_json_with_tools(model, VERIFY_SYSTEM + VERIFY_TOOLS, user, TOOLS, belt.run, max_turns=MAX_VERIFY_TURNS)
        return chat_json(model, VERIFY_SYSTEM, user, temperature=0)

    try:
        answer = with_retry(ask)
    except Exception as exc:
        logger.warning("Second check of the findings in %s failed: %s", view.path, type(exc).__name__)
        unresolved = [f for f in findings if f.get("needs_lookup")]
        return [f for f in findings if not f.get("needs_lookup")], [(f["title"], NEEDS_LOOKUP) for f in unresolved]
    looked = list(belt.looked)[:8] if belt is not None else []
    verdicts: dict[int, dict[str, Any]] = {}
    for entry in answer.get("findings") if isinstance(answer.get("findings"), list) else []:
        if isinstance(entry, dict) and _int(entry.get("number")) is not None:
            verdicts[_int(entry["number"])] = {"holds": _holds(entry.get("holds")), "reason": _text(entry.get("reason"), 200),
                                              "duplicate_of": _number(entry.get("duplicate_of")), "raised": _number(entry.get("already_raised_by")),
                                              "by_code": _number(entry.get("already_found_by_code"))}
    kept: list[dict[str, Any]] = []
    removed: list[tuple[str, str]] = []
    kept_by_number: dict[int, dict[str, Any]] = {}
    for number, f in enumerate(findings, 1):
        verdict = verdicts.get(number)
        if verdict is None:
            if f.get("needs_lookup"):  # the check said nothing about it: nothing confirmed what it depends on
                removed.append((f["title"], NEEDS_LOOKUP))
                continue
            kept.append(f)
            kept_by_number[number] = f
            continue
        if not verdict["holds"]:
            removed.append((f["title"], "it did not hold on a second check" + (f": {verdict['reason']}" if verdict["reason"] else "")))
            continue
        original = kept_by_number.get(verdict["duplicate_of"] or 0) if (verdict["duplicate_of"] or 0) < number else None  # only an earlier finding that was kept
        if original is not None:
            removed.append((f["title"], "it repeats another finding"))
            where = f"line {f['line_number']}"
            if where not in original["comment"]:
                original["comment"] += f" The same applies at {where}."
            continue
        if verdict["by_code"] and 1 <= verdict["by_code"] <= len(exact):
            removed.append((f["title"], "it repeats a finding made by an exact check in code"))
            continue
        if f.get("needs_lookup") and not looked:
            removed.append((f["title"], NEEDS_LOOKUP))
            continue
        f["verified"] = True
        f["checked_with"] = looked
        if verdict["raised"] and 1 <= verdict["raised"] <= len(existing):
            _mark_existing(f, existing[verdict["raised"] - 1])
        kept.append(f)
        kept_by_number[number] = f
    return kept, removed


_COMMENT_START = ("--", "//", "#", "/*", "*", "<!--", "'''", '"""')


def _is_comment(line: str) -> bool:
    """True for a line that holds only a comment (SQL --, C-style //, /* and *, # in Python, PowerShell and YAML, HTML <!--)."""
    return line.lstrip().startswith(_COMMENT_START)


def refute_findings(model: Any, view: FileView, findings: list[dict[str, Any]], pr: dict[str, Any] | None = None,
                    belt: ToolBelt | None = None) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """A last, hostile read: another call is told to assume each finding is wrong and to find code that shows it. A finding is removed only
    when that code is quoted and the quote is really in the file (or in what a lookup returned): an opinion alone removes nothing. If the call
    fails the findings stay."""
    if not findings:
        return findings, []
    pr = pr or {}
    why = f"The author's description of the change:\n{pr.get('title', '')}\n{pr.get('description') or '(no description)'}\n\n"
    alerts = f"\n\nThe alert rules, read from the template:\n{view.extra}" if view.extra else ""
    user = f"File: {view.path} ({view.language})\n{facts_block(view)}\n\n{why}Findings to try to prove wrong:\n{_finding_lines(findings)}{alerts}\n\nThe file:\n\n{view.shown}"

    def ask() -> dict[str, Any]:
        if belt is not None:
            return chat_json_with_tools(model, REFUTE_SYSTEM + VERIFY_TOOLS, user, TOOLS, belt.run, max_turns=MAX_VERIFY_TURNS)
        return chat_json(model, REFUTE_SYSTEM, user, temperature=0)

    try:
        answer = with_retry(ask)
    except Exception as exc:
        logger.warning("The refutation check of the findings in %s failed: %s", view.path, type(exc).__name__)
        return findings, []
    # what may be quoted as proof: the code (not its comments), the facts worked out in code, and what a lookup returned. A comment or the description
    # says what the author meant; it cannot show what the code does, so it never removes a finding.
    proof_rows = [r.text for r in view.rows if view.language == "Markdown" or not _is_comment(r.text)]  # prose has no comments: every line of a document counts
    haystack = _compact("\n".join(proof_rows) + "\n" + view.extra + "\n" + view.facts + "\n" + "\n".join(belt.seen if belt is not None else []))
    verdicts: dict[int, tuple[str, str]] = {}
    for entry in answer.get("findings") if isinstance(answer.get("findings"), list) else []:
        number = _int(entry.get("number")) if isinstance(entry, dict) else None
        if number is not None and _holds(entry.get("wrong")) and _text(entry.get("because"), 200) and _grounded(_quoted(entry.get("quote")), haystack):
            verdicts[number] = (_text(entry.get("because"), 200), _quoted(entry.get("quote")))
    kept: list[dict[str, Any]] = []
    removed: list[tuple[str, str]] = []
    for number, f in enumerate(findings, 1):
        if number in verdicts:
            removed.append((f["title"], f"the code it was checked against contradicts it: {verdicts[number][0]}"))
        else:
            kept.append(f)
    return kept, removed


def file_prompt(view: FileView, pr: dict[str, Any], existing: list[dict[str, Any]], team: list[dict[str, Any]] | None = None,
                team_hits: list[dict[str, Any]] | None = None) -> str:
    if view.whole_file:
        shown = "the whole file"
    else:
        shown = "only the changed parts, with the lines around them" + ("; some changed parts are left out because the file is large" if view.omitted_hunks else "")
    comments = comments_block(existing)
    alerts = f"What the alert rules in this template are, and what changed in them:\n{view.extra}\n\n" if view.extra else ""
    others = [p for p in pr.get("others") or [] if p != view.path]
    listed = f"Other files changed in this pull request (you cannot see them here): {', '.join(others)}\n\n" if others else ""
    checks = pr_knowledge.block(team or [], team_hits or [])
    checks = f"{checks}\n\n" if checks else ""
    return (f"File: {view.path}\nLanguage: {view.language}\nChange: {view.change_type} (+{view.added_count} -{view.removed_count})\n{facts_block(view)}\n"
            f"Pull request title: {pr['title']}\nPull request description (the author's explanation of the change):\n{pr['description'] or '(none)'}\n\n{listed}"
            f"Comments people already made on this file and on the pull request (do not repeat them):\n{comments}\n\n{alerts}{checks}The file is shown as {shown}:\n\n{view.shown}")


def review_file(model: Any, view: FileView, pr: dict[str, Any], threads: list[dict[str, Any]], belt: ToolBelt | None = None) -> dict[str, Any]:
    """Review one file: ask, check each finding in code, check again with a second call (which may look things up), add what the static checks
    find, and note what people already said."""
    existing = context_threads(threads, view.path)
    system = FILE_SYSTEM.format(guide=GUIDES.get(view.language, COMMON_GUIDE))
    team = pr_knowledge.for_language(pr.get("knowledge") or [], view.language)  # the team's own checks that are about this kind of file
    hits = pr_knowledge.literal_hits(team, view.new_lines, view.added)
    answer = with_retry(lambda: chat_json(model, system, file_prompt(view, pr, existing, team, hits), temperature=0.1))
    proposed = len(answer.get("findings")) if isinstance(answer.get("findings"), list) else 0
    findings, removed = clean_findings(answer.get("findings"), view, {i["number"]: i for i in team})
    overflow = max(0, len(findings) - MAX_FINDINGS_PER_FILE)
    findings = findings[:MAX_FINDINGS_PER_FILE]
    exact = static_findings(view, view.old_text, view.new_text)
    findings, rejected = verify_findings(model, view, findings, pr, existing, belt, exact)
    findings, contradicted = refute_findings(model, view, findings, pr, belt)
    rejected = rejected + contradicted
    findings = sorted(findings + exact, key=lambda f: SEVERITIES.index(f["severity"]))
    for finding in findings:
        thread = _existing_for(finding, existing)  # a comment on the same lines is a match whatever the second check said
        if thread:
            _mark_existing(finding, thread)
    return {"purpose": _text(answer.get("purpose"), 200), "findings": findings, "removed": removed, "rejected": rejected, "overflow": overflow,
            "looked": list(belt.looked) if belt is not None else [], "static": len(exact), "proposed": proposed,
            "team_applied": [i["number"] for i in team], "team_hits": [{**h, "path": view.path} for h in hits]}


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
    names = ", ".join(f"{n} {k}" for k, n in sorted(languages.items()))
    text = f"Reviewed {len(reviewed)} of {len(files)} changed files{f' ({names})' if names else ''} at {where}, push {iteration} of {iterations}."
    if not reviewed:
        why = "; ".join(f"{f['path']} ({f.get('reason') or 'not reviewed'})" for f in files[:3]) + (f"; and {len(files) - 3} more" if len(files) > 3 else "")
        return text + f" Nothing could be reviewed: {why}."
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


def team_report(team: list[dict[str, Any]], files: list[dict[str, Any]], results: dict[str, dict[str, Any]], comments: list[dict[str, Any]],
                pr_notes: dict[int, str], pr_checked: bool) -> list[dict[str, Any]]:
    """For each of the team's own checks, what happened to it in this review: raised (a finding came from it), nothing reported (the AI was given it for
    that many files and reported no problem), not applicable (no reviewed file is of the kind the check names) or could not check. `hits` are the places
    in the changed lines where a term the team put in backticks appears."""
    report: list[dict[str, Any]] = []
    for item in team:
        number = item["number"]
        if item["pr_level"]:
            status = "raised" if number in pr_notes else "nothing_reported" if pr_checked else "could_not_check"
            checked, raised, hits = 0, int(number in pr_notes), []
        else:
            checked = sum(1 for r in results.values() if number in r.get("team_applied", []))
            raised = sum(1 for c in comments if c.get("knowledge_number") == number)
            hits = [h for r in results.values() for h in r.get("team_hits", []) if h["item"] == number][:pr_knowledge.MAX_HITS_PER_ITEM * 2]
            status = "raised" if raised else "nothing_reported" if checked else "not_applicable"
        report.append({"number": number, "text": item["text"], "scope": pr_knowledge.scope_label(item), "status": status, "files": checked, "findings": raised, "hits": hits})
    return report


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

    def _texts(self, project: str, repo: str, entry: dict[str, Any], refs: dict[str, str], language: str = "") -> tuple[str | None, str | None, str | None]:
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
        if language == ARM_LANGUAGE and not is_arm_template(new):
            return None, None, "not_arm"
        if "add" in change and not old_id:
            return "", new, None
        if old_id:
            old, why = self.ado.get_blob_text(project, repo, old_id, MAX_FILE_BYTES)
        else:
            old, why = self.ado.get_item_text(project, repo, item.get("path") or path, refs["common"], MAX_FILE_BYTES) if refs.get("common") else (None, "unreadable")
        if old is None:
            return None, None, "the earlier version could not be read"
        return old, new, None

    def review(self, project: str, repository_id: str, pull_request_id: int, progress: Callable[[int, int, str], None] | None = None,
               budget: float = REVIEW_BUDGET_SECONDS, knowledge: str = "") -> dict[str, Any]:
        """The review of one pull request. `progress(done, total, message)` is told how far it has got; `budget` is the seconds the model calls may take;
        `knowledge` is the team's own checks, as the user wrote them (see pr_knowledge)."""
        tell = progress or (lambda done, total, message: None)
        notes: list[str] = []
        tell(0, 0, "Reading the pull request")
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
        team = pr_knowledge.parse(knowledge)
        context = {"title": pr.get("title") or f"Pull request {pull_request_id}", "description": clean_description(description), "knowledge": team}
        threads = thread_summaries(self._optional(notes, "The existing comments", lambda: self.ado.get_pull_request_threads(project, repository_id, pull_request_id)))
        work_items = self._optional(notes, "The linked work items", lambda: [str(w.get("id")) for w in self.ado.get_pull_request_work_items(project, repository_id, pull_request_id)])
        build_check = self._build_check(project, pr, description)

        tell(0, 0, "Reading the changed files")
        reader = RepoReader(self.ado, project, repository_id, refs["source"], [(e.get("item") or {}).get("path", "") for e in entries]) if refs["source"] else None
        files, views = self._plan(project, repository_id, entries, refs, reader)
        context["others"] = [f["path"] for f in files][:MAX_OTHER_FILES]
        results, failures = self._review_all(views, context, threads, reader, budget, tell)
        for path, reason in failures.items():
            self._mark(files, path, "skipped", reason)
        if views and not results:
            raise ReviewFailed("The AI could not review any file: " + (next(iter(failures.values()), "unknown error")) + ". Nothing was reviewed.", 502)

        comments: list[dict[str, Any]] = []
        removed_total: dict[str, int] = {}
        rejected: list[str] = []
        guessed: list[str] = []
        for view in views:
            result = results.get(view.path)
            if not result:
                continue
            row = next(f for f in files if f["path"] == view.path)
            row.update(status="reviewed", findings=len(result["findings"]), purpose=result["purpose"] or None)
            comments.extend(result["findings"])
            for title, reason in result["removed"] + result["rejected"]:
                key = removal_group(reason)
                removed_total[key] = removed_total.get(key, 0) + 1
                if key in GUESS_GROUPS:
                    guessed.append(f"{view.path}: {title} ({reason.removeprefix('it ')})")
            for title, reason in result["rejected"]:
                if removal_group(reason) in GUESS_GROUPS:  # already listed above, with the other findings that rested on a guess
                    continue
                detail = reason.split(": ", 1)[1] if ": " in reason else ""
                rejected.append(f"{view.path}: {title}" + (f" ({detail})" if detail else ""))
            if result["overflow"]:
                notes.append(f"{result['overflow']} lower-priority finding(s) in {view.path} are not shown (limit {MAX_FINDINGS_PER_FILE} per file).")
            if view.omitted_hunks:
                notes.append(f"{view.path} is large: {view.omitted_hunks} changed part(s) at the end were not reviewed.")
        for number, comment in enumerate(comments, 1):
            comment["id"] = f"pr-{pull_request_id}-{number}"
            comment.pop("needs_lookup", None)
        exact = sum(r["static"] for r in results.values())
        if exact:
            notes.append(f"{exact} finding(s) come from static checks made in code, without the AI (marked \"static check\").")
        read = sorted({item for r in results.values() for item in r["looked"] if item.startswith("read ")})
        if read:
            notes.append(f"While checking findings, the second check read {len(read)} file(s) of the repository: " + ", ".join(i.removeprefix("read ") for i in read[:6]) + (", ..." if len(read) > 6 else "") + ".")
        if removed_total:
            notes.append("Removed before showing: " + "; ".join(f"{n} finding(s) {why}" for why, n in removed_total.items()) + ".")
        notes.extend(f"Removed as a guess: {line}" for line in guessed[:6])
        if len(guessed) > 6:
            notes.append(f"{len(guessed) - 6} more findings were removed as guesses.")
        notes.extend(f"Removed on a second check: {line}" for line in rejected[:5])
        if sum(1 for c in comments if c["verified"] is None and c.get("source") != "static"):
            notes.append("The second check could not run for some findings; they are marked \"second check did not run\".")

        tell(1, 1, "Writing the summary")
        clarifications = self._description_gaps(files, description)
        pr_notes, pr_checked = self._team_checks_about_the_pull_request(team, context, threads, files)
        clarifications += [f"Your knowledge base, check {number}: {why}" for number, why in sorted(pr_notes.items())]
        knowledge_checks = team_report(team, files, results, comments, pr_notes, pr_checked)
        proposed = sum(r["proposed"] for r in results.values())
        dropped = sum(len(r["removed"]) + len(r["rejected"]) for r in results.values())
        if proposed or dropped or comments:
            notes.insert(0, f"The AI proposed {proposed} finding{'' if proposed == 1 else 's'} in {len(results)} file{'' if len(results) == 1 else 's'}; "
                            f"{dropped} {'was' if dropped == 1 else 'were'} removed by the rules or the checks; "
                            f"{len(comments) - exact} from the AI and {exact} from exact checks in code {'is' if len(comments) == 1 else 'are'} shown.")
        evidence = {"changed_paths": [f["path"] for f in files], "work_items": work_items, "build_check": build_check}
        checklist = evaluate_checklist(parse_checklist(description), evidence) + placeholder_checks(description)
        notes = list(dict.fromkeys(notes))  # the same note, for example "could not be read", is not said twice
        verdict, scorecard = judge(comments)
        if not any(f["status"] == "reviewed" for f in files):
            verdict = "NOT_REVIEWED"
        return {
            "pull_request_id": pull_request_id, "verdict": verdict, "summary": summarize(files, comments, refs["source"], int(last.get("id") or len(iterations)), len(iterations)),
            "scorecard": scorecard, "comments": comments, "clarifications": clarifications, "posted_to_ado": False,
            "method": "diff-per-file", "source_commit": refs["source"] or None, "iterations": len(iterations),
            "files": files, "checklist": checklist, "notes": notes, "scope_note": SCOPE_NOTE, "knowledge_checks": knowledge_checks,
        }

    # ------------------------------------------------------------ steps

    def _team_checks_about_the_pull_request(self, team: list[dict[str, Any]], context: dict[str, Any], threads: list[dict[str, Any]],
                                            files: list[dict[str, Any]]) -> tuple[dict[int, str], bool]:
        """The team's checks that are about the pull request itself (its description, its files): ({check number: why it is broken}, whether the check ran).
        A check counts as broken only when the AI quotes words of the description, a file path or a comment that show it."""
        items = [i for i in team if i["pr_level"]]
        if not items:
            return {}, True
        paths = [f["path"] for f in files]
        general = [t for t in threads if not t["path"]]
        comments = comments_block([{**t, "general": True} for t in general[:MAX_GENERAL_COMMENTS]])
        user = ("Checks about this pull request:\n" + "\n".join(f"{i['number']}. {i['text']}" for i in items)
                + f"\n\nPull request title: {context['title']}\nPull request description:\n{context['description'] or '(none)'}\n\nChanged files:\n" + "\n".join(paths[:200])
                + f"\n\nComments people already made on the pull request as a whole:\n{comments}")
        try:
            answer = with_retry(lambda: chat_json(self.model, KB_PR_SYSTEM, user, temperature=0))
        except Exception as exc:
            logger.info("PR review: the team's checks about the pull request failed (%s)", type(exc).__name__)
            return {}, False
        haystack = _compact(f"{context['title']}\n{context['description']}\n" + "\n".join(paths) + "\n" + comments)
        wanted = {i["number"] for i in items}
        broken: dict[int, str] = {}
        for entry in answer.get("checks") if isinstance(answer.get("checks"), list) else []:
            number = _int(entry.get("number")) if isinstance(entry, dict) else None
            why = _text(entry.get("because"), 240) if isinstance(entry, dict) else ""
            if number in wanted and entry.get("breaks") is True and why and _grounded(_quoted(entry.get("quote")), haystack) and not _ASK.search(why) and not _HEDGE.search(why):
                broken[number] = why
        return broken, True

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

    def _plan(self, project: str, repo: str, entries: list[dict[str, Any]], refs: dict[str, str], reader: RepoReader | None = None) -> tuple[list[dict[str, Any]], list[FileView]]:
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
        for examined, (row, entry, language) in enumerate(candidates):
            if len(views) >= MAX_FILES:
                row["reason"] = f"over the limit of {MAX_FILES} files reviewed in one go"
                continue
            if examined >= MAX_EXAMINED:
                row["reason"] = f"not examined: more than {MAX_EXAMINED} files in this pull request"
                continue
            old, new, why = self._texts(project, repo, entry, refs, language)
            if new is None:
                row["reason"] = {"too_large": f"larger than {MAX_FILE_BYTES // 1000} KB", "binary": "not a text file", "not_arm": "JSON file that is not an ARM template"}.get(why or "", why or "could not be read")
                continue
            try:
                view = build_view(row["path"], language, row["change_type"], old, new, width=ARM_LINE_WIDTH if language == ARM_LANGUAGE else LINE_WIDTH)
            except ValueError as exc:
                row["reason"] = f"too long to compare ({exc})"
                continue
            if not view.has_changes:
                row["reason"] = "no change in the content"
                continue
            if language == ARM_LANGUAGE:
                view.extra = arm_context(old, new)
            view.old_text, view.new_text = old, new
            row["reason"] = None
            views.append(view)
        if reader is not None:
            for view in views:
                if view.language == "C#":
                    try:
                        view.facts = csharp_facts(reader, view.path)
                    except Exception as exc:  # noqa: BLE001
                        logger.info("PR review: the project facts of %s could not be read (%s)", view.path, type(exc).__name__)
        return files, views

    def _review_all(self, views: list[FileView], context: dict[str, Any], threads: list[dict[str, Any]], reader: RepoReader | None = None,
                    budget: float = REVIEW_BUDGET_SECONDS, tell: Callable[[int, int, str], None] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        results: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        if not views:
            return results, failures
        tell = tell or (lambda done, total, message: None)
        deadline = time.monotonic() + budget

        def one(view: FileView) -> tuple[str, dict[str, Any] | None, str]:
            if time.monotonic() > deadline:
                return view.path, None, "not reached in the time allowed"
            belt = ToolBelt(reader, view.path, deadline) if reader is not None else None
            try:
                return view.path, review_file(self.model, view, context, threads, belt), ""
            except Exception as exc:
                logger.warning("PR review: the AI call for %s failed (%s)", view.path, type(exc).__name__)
                return view.path, None, "the AI call failed"

        total = len(views)
        tell(0, total, f"Reviewing {total} file{'s' if total != 1 else ''}")
        with ThreadPoolExecutor(max_workers=min(WORKERS, total)) as pool:
            for done, future in enumerate(as_completed([pool.submit(one, view) for view in views]), 1):
                path, result, reason = future.result()
                if result is not None:
                    results[path] = result
                else:
                    failures[path] = reason
                tell(done, total, f"Reviewed {done} of {total} files")
        return results, failures

    @staticmethod
    def _mark(files: list[dict[str, Any]], path: str, status: str, reason: str) -> None:
        for row in files:
            if row["path"] == path:
                row["status"], row["reason"] = status, reason

    def _description_gaps(self, files: list[dict[str, Any]], description: str) -> list[str]:
        purposes = [f"{f['path']}: {f['purpose']}" for f in files if f["status"] == "reviewed" and f["purpose"]]
        body = clean_description(description)
        if not body or not purposes:
            return []
        user = f"Pull request description:\n{body}\n\nChanged files:\n" + "\n".join(purposes)
        try:
            answer = with_retry(lambda: chat_json(self.model, DESCRIPTION_SYSTEM, user, temperature=0))
        except Exception as exc:
            logger.info("PR review: the description check failed (%s)", type(exc).__name__)
            return []
        gaps = answer.get("missing_from_description")
        haystack = _compact(body)
        notes: list[str] = []
        for gap in (gaps if isinstance(gaps, list) else [])[:3]:
            change = _text(gap.get("change") if isinstance(gap, dict) else gap, 200)
            mention = _quoted(gap.get("description_mentions")) if isinstance(gap, dict) else ""
            if not change or covered_by(change, body) or (mention and _grounded(mention, haystack)):
                continue  # the description already says it: the sentence the AI quoted is really there
            notes.append(f"The description does not mention: {change}")
        return notes


_STOP_WORDS = {"this", "that", "with", "from", "have", "been", "were", "will", "into", "also", "than", "then", "when", "which", "while", "their", "there", "these", "those",
               "added", "adds", "change", "changes", "changed", "update", "updated", "updates", "file", "files", "code", "new", "function", "functions", "method", "methods"}


def _significant(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]{4,}", text.lower()) if w not in _STOP_WORDS}


def covered_by(gap: str, description: str) -> bool:
    """True when the description already says what a "not mentioned" note claims it leaves out: at least half of the note's own words
    (or their first five letters, so "validator" and "validation" match) are in the description."""
    words = _significant(gap)
    if not words:
        return False
    have = _significant(description)
    stems = {w[:5] for w in have}
    return sum(1 for w in words if w in have or w[:5] in stems) * 2 >= len(words)

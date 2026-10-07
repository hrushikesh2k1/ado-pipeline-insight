"""The checklist the reviewer must answer, item by item, for each kind of file.

A free-form "look for problems" instruction made the model answer "nothing" for files that held several well-known problems: told to be careful
and to report only what it can prove, it said nothing. A list it has to answer for EVERY item does not allow that: for each item it must say
"problem", "fine" or "not applicable", and a "problem" must come with a concrete case and the code it relies on (which the rest of the review
checks). The items are discrete and each names the pattern, with a short example, so that a small model can match it.
"""
from __future__ import annotations

from app.services.pr_arm import ARM_LANGUAGE

PYTHON = [
    "A loop that, for each item, searches another list (a list comprehension, any(), next() or `in` over a list inside the loop): quadratic. A dict or a set lookup fixes it.",
    "The same fixed strings (statuses such as \"PASS\" and \"FAIL\") written as literals in several places: use an Enum.",
    "A substring test used to read a value: `if \"m\" in text` also matches \"10ms\", and `\"GB\" in size` also matches \"GBps\". The unit must be matched whole.",
    "An average taken over values that are themselves averages (per product, per group): wrong when the groups differ in size; it must be weighted by count.",
    "A function, class, constant, import or variable this change added that nothing uses.",
    "A mutable default argument (`def f(x=[])`).",
    "A bare `except:`, or an except block that swallows the error, or a failure turned into a success value.",
    "subprocess with shell=True and input that is not fixed; a requests call without `timeout`.",
    "SQL or HTML built by string formatting from data (use query parameters; html.escape).",
    "A new function without a docstring or header comment when the other functions of the file have one.",
    "A file path, time or locale that is hard-coded or local where a parameter or UTC is needed.",
]

POWERSHELL = [
    "Invoke-Expression on anything that is not fixed (AvoidUsingInvokeExpression).",
    "A password or secret in plain text, ConvertTo-SecureString with -AsPlainText, or parameters named Password or UserName instead of a PSCredential.",
    "An empty catch block, or a command inside try without -ErrorAction Stop (so the catch never runs).",
    "A hard-coded computer name (AvoidUsingComputerNameHardcoded).",
    "Write-Host for output a caller may need: return objects instead (AvoidUsingWriteHost). A script that reports progress with Write-Host throughout follows its own convention: answer fine.",
    "A function that changes state without SupportsShouldProcess (UseShouldProcessForStateChangingFunctions).",
    "An unapproved verb in a function name (UseApprovedVerbs), or aliases and positional parameters in a script.",
    "$null on the right-hand side of a comparison (PossibleIncorrectComparisonWithNull); a global variable (AvoidGlobalVars).",
    "A variable assigned and never used (UseDeclaredVarsMoreThanAssignments).",
    "`+=` on an array or a string inside a loop (use a List or -join); Where-Object over a large collection inside a loop (use a hashtable lookup); Export-Csv -Append inside ForEach-Object.",
    "A new function without comment-based help, only when the other functions of the file have it (ProvideCommentHelp).",
    "A check or assertion that can never fail, or that tests less than its message says (a message that says \"every array is empty\" for a test of some of them).",
]

CSHARP = [
    "An empty catch, or a catch of Exception that hides the cause.",
    "async code that blocks with .Result or .Wait() (it can deadlock), async void outside an event handler, or a Task that is not awaited.",
    "An IDisposable (stream, connection, an HttpClient created for each call) that is not disposed.",
    "SQL built by string concatenation instead of parameters.",
    "A secret or connection string written in the code.",
    "DateTime.Now where UTC is needed.",
    "A query or loop over database results with no limit.",
    "A value that can be null used without a check; a default that hides a failure.",
    "lock on `this` or on a public object; mutable static state shared between requests.",
    "A name, route, option or setting this change renamed, while code that uses the old name still exists in the lines shown.",
]

SQL = [
    "A column or alias labeled differently from the same column in other parts of the same query (the other branches of a UNION, the other buckets). Check how the rest of the query labels it before you call it wrong.",
    "UPDATE or DELETE without a WHERE.",
    "A function applied to a column in a WHERE clause, which stops an index from being used.",
    "Dynamic SQL built by joining strings instead of parameters.",
    "Local time (GETDATE) where UTC is meant, or the reverse.",
    "A header comment that contradicts the code beside it: a procedure name, a parameter, or a last-modified date earlier than the created date. It is a documentation fault: category maintainability, severity suggestion.",
]

ALERTS = [
    "A changed threshold, operator, windowSize, evaluationFrequency, failingPeriods or query that changes when the alert fires (say what now fires or stops firing).",
    "minFailingPeriodsToAlert larger than numberOfEvaluationPeriods.",
    "A window shorter than what the query looks back over, or a time filter shorter than the time between runs (use the timing facts you are given, not your own arithmetic).",
    "A log alert meant to detect a lack of data (Microsoft recommends a metric alert for that).",
    "enabled set to false, or no action group (nobody is notified).",
    "muteActionsDuration that hides repeats, autoMitigate set to false so the alert never resolves, skipQueryValidation set to true.",
    "A severity that does not match what the alert is for (0 is the most severe).",
    "A query mistake: a table or column the query does not have, a filter that can never match, a count compared with a threshold meant for a measure column.",
    "A parameter that holds a password or key that is not securestring, or a secure value used where it is stored as plain text.",
    "A hard-coded subscription or resource id that ties the template to one environment.",
]

KQL = [
    "A missing or misplaced time filter.",
    "A join that multiplies rows.",
    "A column or table the query does not have, or a filter that can never match.",
    "Results that are not bounded.",
    "A summarize or threshold that does not measure what its name says.",
]

MARKDOWN = [
    "Content this change removed that other text still depends on (a heading that something links to, a table row or cell, a step later steps need).",
    "Instructions or commands that no longer match each other.",
    "A link to a file or an anchor this change broke, or a code block that is opened and never closed.",
]

YAML = [
    "A variable or parameter used in this file but not defined here or in the templates it uses.",
    "A step removed or changed so that a later step's input (a file, an artifact path, a directory) no longer exists.",
    "A secret or token written in plain text.",
    "A condition, dependsOn or output name that does not match the one it refers to.",
    "A task or image version that is not pinned, or a hard-coded agent pool or path that ties the file to one environment.",
]

COMMON = [
    "An error that is swallowed, or a failure turned into a success value.",
    "Input from outside used in a query, a command, a path or a URL without validation.",
    "A secret or key written in the code.",
    "A value that can be missing used without a check.",
    "A resource opened and never closed.",
    "A name, format or setting this change renamed or changed, while other lines shown still use the old one.",
]

CHECKS: dict[str, list[str]] = {
    "Python": PYTHON, "PowerShell": POWERSHELL, "C#": CSHARP, "SQL": SQL, ARM_LANGUAGE: ALERTS, "KQL": KQL, "Markdown": MARKDOWN, "YAML": YAML,
}


def checks_for(language: str) -> list[str]:
    """The checklist for a kind of file (a general one for languages without their own)."""
    return CHECKS.get(language, COMMON)


def block(checks: list[str]) -> str:
    """The checklist as text for the prompt, numbered from 1."""
    return "Checklist for this kind of file (answer every item):\n" + "\n".join(f"{n}. {text}" for n, text in enumerate(checks, 1))

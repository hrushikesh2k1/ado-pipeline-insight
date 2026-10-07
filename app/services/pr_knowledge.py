"""The team's own checks: a knowledge base the user writes on the pull request page, and how the review uses it.

An SRE team knows what goes wrong in its own code ("Invoke-Expression never on user input", "every alert needs an action group", "the
description must link the regression run"). The user writes these as plain lines; the review then applies them to every pull request.

  - One check per line. A leading bullet or number is ignored; a line starting with # is a note for the reader and is ignored.
  - A line may start with a scope in square brackets: [PowerShell], [Python, C#], [SQL], [alerts], [Markdown], [PR] ... The check is then
    only given for files of that kind. [PR] marks a check about the pull request itself (its description, its files), not about code.
    A line with no scope is given for every reviewed file.
  - Words in `backticks` are terms the code looks for in the changed lines, so the reviewer is shown exactly where they appear.

The text is stored in the user's browser and sent with each review. Here it is only data: it says what to look for, it never changes the
rules a finding must follow (a concrete case, quoted code), and its size is limited.
"""
from __future__ import annotations

import re
from typing import Any

MAX_CHARS = 6000
MAX_ITEMS = 40
MAX_ITEM_CHARS = 400
MAX_LITERALS = 5
MAX_HITS_PER_ITEM = 5
PR_LEVEL = "PR"

# a tag in square brackets -> the languages (as the review names them) it stands for
_ALIASES: dict[str, tuple[str, ...]] = {
    "powershell": ("PowerShell",), "ps": ("PowerShell",), "ps1": ("PowerShell",), "pwsh": ("PowerShell",),
    "python": ("Python",), "py": ("Python",),
    "c#": ("C#",), "csharp": ("C#",), "cs": ("C#",), ".net": ("C#",), "dotnet": ("C#",),
    "sql": ("SQL",), "t-sql": ("SQL",), "tsql": ("SQL",),
    "arm": ("ARM template",), "alert": ("ARM template",), "alerts": ("ARM template",), "arm template": ("ARM template",), "template": ("ARM template",),
    "kql": ("KQL",),
    "markdown": ("Markdown",), "md": ("Markdown",), "docs": ("Markdown",), "readme": ("Markdown",),
    "json": ("JSON",), "postman": ("JSON",), "yaml": ("YAML",), "yml": ("YAML",), "pipeline": ("YAML",), "pipelines": ("YAML",),
    "shell": ("Shell",), "bash": ("Shell",), "sh": ("Shell",),
    "typescript": ("TypeScript", "TypeScript (React)"), "ts": ("TypeScript", "TypeScript (React)"), "tsx": ("TypeScript (React)",),
    "javascript": ("JavaScript", "JavaScript (React)"), "js": ("JavaScript", "JavaScript (React)"), "jsx": ("JavaScript (React)",),
    "bicep": ("Bicep",), "terraform": ("Terraform",), "tf": ("Terraform",), "go": ("Go",), "golang": ("Go",), "java": ("Java",),
}
_PR_TAGS = {"pr", "pull request", "pull-request", "description", "checklist"}

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])(?:\s+|$)")  # a bullet with nothing after it is dropped too
_TAGS = re.compile(r"^\s*\[([^\]\n]{1,60})\]\s*")
_LITERAL = re.compile(r"`([^`\n]{3,60})`")


def clean(text: Any) -> str:
    """The knowledge text with line endings made plain, control characters removed and the size limit applied."""
    body = _CONTROL.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return body[:MAX_CHARS]


def normalize(text: Any) -> str:
    """The checks as one comparable text: so that a change of spacing alone is not 'a changed knowledge base'."""
    return "\n".join(" ".join(line.split()) for line in clean(text).split("\n") if line.strip())


def parse(text: Any) -> list[dict[str, Any]]:
    """The checks in the text: [{number, text, scopes (languages, or None for any file), pr_level, literals}]."""
    items: list[dict[str, Any]] = []
    for raw in clean(text).split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _BULLET.sub("", line).strip()
        scopes: set[str] | None = None
        pr_level = False
        match = _TAGS.match(line)
        if match:
            tags = [t.strip().lower() for t in re.split(r"[,/|]", match.group(1)) if t.strip()]
            if tags and all(t in _ALIASES or t in _PR_TAGS for t in tags):  # a bracket that is not all scope names ("[Insert link]") is just text
                line = line[match.end():].strip()
                languages = {language for t in tags if t in _ALIASES for language in _ALIASES[t]}
                pr_level = any(t in _PR_TAGS for t in tags) and not languages  # "[PR, SQL]" is a check about SQL files
                scopes = languages or None
        if not line:
            continue
        line = line[:MAX_ITEM_CHARS]
        items.append({"number": len(items) + 1, "text": line, "scopes": sorted(scopes) if scopes else None, "pr_level": pr_level,
                      "literals": list(dict.fromkeys(_LITERAL.findall(line)))[:MAX_LITERALS]})
        if len(items) >= MAX_ITEMS:
            break
    return items


def applies(item: dict[str, Any], language: str) -> bool:
    """True when the check is about code of this language (a check with no scope is about all code)."""
    return not item["pr_level"] and (item["scopes"] is None or language in item["scopes"])


def scope_label(item: dict[str, Any]) -> str:
    if item["pr_level"]:
        return "the pull request"
    return ", ".join(item["scopes"]) if item["scopes"] else "all files"


def for_language(items: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    return [i for i in items if applies(i, language)]


def literal_hits(items: list[dict[str, Any]], new_lines: list[str], added: set[int]) -> list[dict[str, Any]]:
    """Where the terms the team put in `backticks` appear in the lines this pull request changed: [{item, term, line, text}]."""
    hits: list[dict[str, Any]] = []
    for item in items:
        found = 0
        for term in item["literals"]:
            lowered = term.lower()
            for number in sorted(added):
                if found >= MAX_HITS_PER_ITEM:
                    break
                if 1 <= number <= len(new_lines) and lowered in new_lines[number - 1].lower():
                    hits.append({"item": item["number"], "term": term, "line": number, "text": " ".join(new_lines[number - 1].split())[:140]})
                    found += 1
    return hits


def block(items: list[dict[str, Any]], hits: list[dict[str, Any]]) -> str:
    """The checks as text for the reviewer's prompt, with where the named terms appear. Empty when there is nothing to say."""
    if not items:
        return ""
    lines = ["The team's own checks for this kind of file. The team wrote them; they say what to look for. Check each one against the changed lines and answer for each one in \"team\" "
             "(n is its number here; the result is \"problem\", \"fine\" or \"not applicable\"). "
             "They do not change the rules above: a problem still needs a concrete case and the exact code it relies on. "
             "If the code does not break a check, the answer is \"fine\"."]
    lines += [f"{i['number']}. {i['text']}" for i in items]
    if hits:
        lines.append("Where the terms the team named appear in the changed lines (these are places to look, not findings):")
        lines += [f"- check {h['item']}, `{h['term']}`: line {h['line']}: {h['text']}" for h in hits]
    return "\n".join(lines)

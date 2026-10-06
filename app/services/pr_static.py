"""Checks the review makes in code, without the AI: facts that can be read off a file with certainty.

An AI reading a diff misses things a program sees at once (a variable that is set and never read, a file that is no longer valid UTF-8,
a table row with a cell too many) and states other things with confidence that are not so. These checks are exact, so they are made
here, and a finding from them is marked "static check" instead of passing through the second AI check.
"""
from __future__ import annotations

import ast
import logging
import re
from typing import Any

from app.services.pr_diff import FileView

logger = logging.getLogger(__name__)

MAX_STATIC_FINDINGS = 6


def _finding(view: FileView, line: int, title: str, comment: str, case: str, evidence: str, severity: str = "suggestion", category: str = "maintainability") -> dict[str, Any]:
    return {
        "category": category, "severity": severity, "title": title, "comment": comment, "file_path": view.path, "language": view.language,
        "line_number": line, "end_line": None, "suggestion_code": None, "failing_case": case, "evidence": " ".join(evidence.split())[:300],
        "existing_thread": None, "existing_status": None, "verified": None, "source": "static",
    }


def _anchor(view: FileView, preferred: int | None = None) -> int | None:
    """The line a comment goes on: the preferred one when this pull request changed it, otherwise the first changed line."""
    changed = view.added | view.removed_at
    if preferred is not None and preferred in view.added:
        return preferred
    return min(changed) if changed else None


# ---------------------------------------------------------------- the file's encoding

def encoding_findings(view: FileView, old: Any, new: Any) -> list[dict[str, Any]]:
    """A file that was valid UTF-8 and no longer is, or a script that lost its byte order mark while holding non-ASCII text.
    `old` and `new` are the texts as the client read them (see core.ado_client.DecodedText); plain text carries no encoding facts."""
    if not hasattr(old, "bad_byte_line") or not hasattr(new, "bad_byte_line"):
        return []
    found: list[dict[str, Any]] = []
    if new.bad_byte_line is not None and old.bad_byte_line is None:
        line = _anchor(view, new.bad_byte_line)
        if line is not None:
            found.append(_finding(
                view, line, "The file is no longer valid UTF-8",
                f"The earlier version of this file was valid UTF-8{' (with a byte order mark)' if old.has_bom else ''}. This version is not: a byte on line {new.bad_byte_line} is not valid UTF-8, "
                "which is what happens when a file is saved in a Windows code page such as Windows-1252 (ANSI). Every character outside plain ASCII on those lines is shown as the replacement character (�) or as a wrong character. Save the file as UTF-8 again.",
                f"Reading the file as UTF-8 turns {new.bad_byte_count} byte(s) (the first on line {new.bad_byte_line}) into the replacement character, so that text is read wrongly; the earlier version read correctly.",
                view.new_lines[new.bad_byte_line - 1] if 0 < new.bad_byte_line <= len(view.new_lines) else "", "warning", "correctness"))
    if view.language == "PowerShell" and old.has_bom and not new.has_bom and new.bad_byte_line is None:
        number, text = next(((n, t) for n, t in enumerate(view.new_lines, 1) if any(ord(c) > 127 for c in t)), (None, ""))
        line = _anchor(view, number)
        if number is not None and line is not None:
            char = next(c for c in text if ord(c) > 127)
            found.append(_finding(
                view, line, "The script lost its UTF-8 byte order mark but has non-ASCII text",
                "The earlier version began with a UTF-8 byte order mark; this version does not, and the script contains non-ASCII characters. Microsoft documents that "
                "Windows PowerShell reads a script without the mark in the legacy ANSI code page, and tells you to save scripts with non-ASCII characters as UTF-8 with BOM. Save the file as UTF-8 with BOM.",
                f"Windows PowerShell 5.1 reads this file in the ANSI code page, so '{char}' on line {number} is read as different characters.", text, "warning", "correctness"))
    return found


# ---------------------------------------------------------------- PowerShell: a variable that is set and never read

_PS_SKIP_FILE = re.compile(r"\b(?:Get|Set|New|Remove|Clear)-Variable\b|\bInvoke-Expression\b|\biex\b|\$ExecutionContext|\bVariable:", re.IGNORECASE)
_PS_ASSIGN = re.compile(r"^\s*\$(\w+)\s*(?:[-+*/%])?=(?!=)")
_PS_PARAM = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*param\s*\(", re.IGNORECASE)
_PS_AUTOMATIC = {
    "_", "null", "true", "false", "args", "input", "this", "psitem", "error", "matches", "lastexitcode", "pscmdlet", "psboundparameters", "psscriptroot",
    "pscommandpath", "myinvocation", "home", "host", "pid", "pwd", "shellid", "foreach", "switch", "stacktrace", "psversiontable", "profile",
}


def _param_lines(lines: list[str]) -> set[int]:
    """The line numbers (1-based) inside a param( ... ) block: a parameter with a default value is not an assignment."""
    inside: set[int] = set()
    depth = 0
    for number, line in enumerate(lines, 1):
        if depth == 0 and not _PS_PARAM.match(line):
            continue
        inside.add(number)
        depth = max(depth + line.count("(") - line.count(")"), 0)
    return inside


def powershell_unused(view: FileView) -> list[dict[str, Any]]:
    """Variables a changed line assigns and no line of the file reads (PSScriptAnalyzer: UseDeclaredVarsMoreThanAssignments)."""
    lines = view.new_lines
    text = "\n".join(lines)
    if _PS_SKIP_FILE.search(text):  # the file reads variables by name: a textual search proves nothing
        return []
    params = _param_lines(lines)
    found: list[dict[str, Any]] = []
    done: set[str] = set()
    for number in sorted(view.added):
        if not 1 <= number <= len(lines) or number in params:
            continue
        match = _PS_ASSIGN.match(lines[number - 1])
        if not match:
            continue
        name = match.group(1)
        key = name.lower()
        if key in done or key in _PS_AUTOMATIC or key.endswith("preference"):
            continue
        done.add(key)
        use = re.compile(r"(?<![\w$])[$@]\{?" + re.escape(name) + r"\}?(?!\w)", re.IGNORECASE)
        occurrences = sum(len(use.findall(line)) for line in lines)
        targets = sum(1 for line in lines if (m := _PS_ASSIGN.match(line)) and m.group(1).lower() == key)
        if occurrences - targets > 0:
            continue
        found.append(_finding(
            view, number, f"${name} is assigned and never used",
            f"${name} is set on line {number} and no line of this file reads it, so the value is worked out for nothing (PSScriptAnalyzer rule UseDeclaredVarsMoreThanAssignments). "
            "Remove the variable; if the command on the right does something that is needed, keep the command and drop the assignment.",
            f"Searching this file for ${name} finds only the assignment, so its value never reaches anything.", lines[number - 1]))
    return found


# ---------------------------------------------------------------- Python: an import or a local variable that is never used

def _words(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_]\w*", text))


def _own_nodes(function: ast.AST):
    """The nodes of a function that belong to its own scope (not the bodies of functions, lambdas or classes inside it)."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _silenced(lines: list[str], node: ast.AST) -> bool:
    """True when the author wrote `# noqa` on any line of the statement: the unused name is deliberate."""
    first = node.lineno
    last = getattr(node, "end_lineno", first) or first
    return any("noqa" in line.lower() for line in lines[first - 1:last])


def python_unused(view: FileView) -> list[dict[str, Any]]:
    lines = view.new_lines
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError, RecursionError):
        return []
    found: list[dict[str, Any]] = []

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 120:
            used |= _words(node.value)  # names in __all__, in string annotations and in type comments
    guarded: list[tuple[int, int]] = []  # try and if blocks (compatibility imports, `if TYPE_CHECKING`): an import there is deliberate
    for node in ast.walk(tree):
        if isinstance(node, (ast.Try, ast.If)):
            guarded.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    if not view.path.rsplit("/", 1)[-1] == "__init__.py":
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.lineno not in view.added:
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "__future__" or any(a <= node.lineno <= b for a, b in guarded) or _silenced(lines, node):
                continue
            for alias in node.names:
                if alias.name == "*" or alias.asname == alias.name:  # `import x as x` is how a module says it re-exports x
                    continue
                if isinstance(node, ast.Import) and "." in alias.name and not alias.asname:  # `import pkg.sub` is often made for what it registers
                    continue
                name = alias.asname or (alias.name if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0])
                if name not in used:
                    found.append(_finding(view, node.lineno, f"{name} is imported and never used",
                                          f"`{alias.name}` is imported on line {node.lineno} and nothing in this file refers to `{name}`. Remove the import.",
                                          f"Searching this file for `{name}` finds only the import line.", lines[node.lineno - 1]))

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        everything = list(ast.walk(function))
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"locals", "vars", "eval", "exec"} for n in everything):
            continue
        read = {n.id for n in everything if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Store)}
        read |= {n.target.id for n in everything if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}
        read |= {name for n in everything if isinstance(n, (ast.Global, ast.Nonlocal)) for name in n.names}
        for node in _own_nodes(function):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                name = node.target.id
            else:
                continue
            if node.lineno in view.added and name not in read and not name.startswith("_") and not _silenced(lines, node):
                found.append(_finding(view, node.lineno, f"{name} is assigned and never used",
                                      f"`{name}` is set on line {node.lineno} in {function.name}() and nothing in the function reads it, so the value is worked out for nothing. "
                                      "Remove the variable; if the call on the right does something that is needed, keep the call and drop the assignment.",
                                      f"Searching {function.name}() for `{name}` finds only the assignment.", lines[node.lineno - 1]))
    seen: set[tuple[int, str]] = set()
    unique = []
    for f in found:
        key = (f["line_number"], f["title"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ---------------------------------------------------------------- Markdown: a table row with a different number of cells than its header

_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$")


def _cell_count(row: str) -> int:
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    count, in_code, i = 1, False, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        elif ch == "|" and not in_code:
            count += 1
        i += 1
    return count


def markdown_tables(view: FileView) -> list[dict[str, Any]]:
    """Rows of a table, added by this pull request, whose number of cells differs from the header's. In GitHub-flavored Markdown a row
    with fewer cells gets empty cells and a row with more has its extra cells ignored, so the text shows wrongly either way."""
    lines = view.new_lines
    found: list[dict[str, Any]] = []
    fenced = False
    run: list[tuple[int, str]] = []

    def close() -> None:
        if len(run) >= 3 and _SEPARATOR.match(run[1][1]) and _cell_count(run[1][1]) == _cell_count(run[0][1]):
            expected = _cell_count(run[0][1])
            for number, row in run[2:]:
                got = _cell_count(row)
                if number in view.added and got != expected:
                    what = "an empty cell is added to the row" if got < expected else "the extra cell is dropped"
                    found.append(_finding(view, number, f"Table row has {got} cells, the header has {expected}",
                                          f"The row on line {number} has {got} cell(s) and the table's header has {expected}. In GitHub-flavored Markdown {what}, so the table shows wrongly. Add or remove the missing `|`.",
                                          f"In the rendered table {what}.", row, "warning", "correctness"))
        run.clear()

    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            close()
            fenced = not fenced
            continue
        if not fenced and line.lstrip().startswith("|"):
            run.append((number, line))
        else:
            close()
    close()
    return found


# ---------------------------------------------------------------- all of them

def static_findings(view: FileView, old: Any = None, new: Any = None) -> list[dict[str, Any]]:
    """The exact checks for one file. A check that fails to run is skipped: it must never break a review."""
    found: list[dict[str, Any]] = []
    checks = [lambda: encoding_findings(view, old, new)]
    if view.language == "PowerShell":
        checks.append(lambda: powershell_unused(view))
    elif view.language == "Python":
        checks.append(lambda: python_unused(view))
    elif view.language == "Markdown":
        checks.append(lambda: markdown_tables(view))
    for check in checks:
        try:
            found.extend(check())
        except Exception as exc:  # noqa: BLE001
            logger.warning("PR review: a static check failed for %s (%s)", view.path, type(exc).__name__)
    return found[:MAX_STATIC_FINDINGS]

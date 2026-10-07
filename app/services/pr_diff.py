"""What the reviewer is shown for a changed file, and which lines a comment may point at.

The two versions of a file are compared line by line. The reviewer sees every line with its number in the new version, marked
"+" when the pull request added or changed it and "-" when it removed it, so it can tell new code from old.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.pr_arm import ARM_LANGUAGE

# A .json file is reviewed as an ARM template when its content is one (see pr_arm.is_arm_template) and as plain JSON otherwise; the review decides that
# after fetching the file.
LANGUAGES = {
    ".py": "Python", ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell", ".json": ARM_LANGUAGE, ".kql": "KQL",
    ".sh": "Shell", ".sql": "SQL", ".yml": "YAML", ".yaml": "YAML", ".bicep": "Bicep", ".tf": "Terraform",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".js": "JavaScript", ".jsx": "JavaScript (React)",
    ".cs": "C#", ".go": "Go", ".java": "Java", ".md": "Markdown", ".markdown": "Markdown",
}
FIRST_LANGUAGES = ("Python", "PowerShell", ARM_LANGUAGE)  # reviewed first when a pull request has more files than can be reviewed

LOCK_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "composer.lock", "gemfile.lock", "cargo.lock", "go.sum", "packages.lock.json"}
DOCUMENT_EXTENSIONS = {".txt", ".rst"}
DATA_EXTENSIONS = {".csv", ".tsv", ".xml", ".toml", ".ini", ".cfg", ".conf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".xlsx", ".docx", ".pptx", ".dll", ".exe", ".pyc", ".whl"}
GENERATED = re.compile(r"(\.min\.(js|css)$|\.map$|\.designer\.cs$|\.g\.cs$|_pb2\.py$|\.generated\.)", re.IGNORECASE)

MAX_LINES_TO_COMPARE = 12000
MAX_MATCH_CELLS = 4_000_000  # lines in the changed middle of the old file times those of the new: above this the comparison trades exactness for speed
LINE_WIDTH = 240

_TEST_NAME = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.tests?\.ps1|[^/]*\.(test|spec)\.[jt]sx?|[^/]*tests?\.cs)$", re.IGNORECASE)
_TEST_DIR = re.compile(r"(^|/)(tests|__tests__)/", re.IGNORECASE)
_CHANGELOG = re.compile(r"(^|/)(change-?log|release[-_ ]?notes)(\.[a-z]+)?$", re.IGNORECASE)


def extension(path: str) -> str:
    match = re.search(r"\.[^./]+$", path)
    return match.group(0).lower() if match else ""


def classify(path: str, change_type: str) -> tuple[str | None, str | None]:
    """(language, None) for a file the review reads, or (None, the reason it is not read)."""
    name = path.rsplit("/", 1)[-1]
    ext = extension(path)
    if "delete" in change_type.lower():
        return None, "deleted file"
    if name.lower() in LOCK_FILES or GENERATED.search(path):
        return None, "lock file, generated or minified"
    if ext in (".md", ".markdown") and is_changelog_path(path):
        return None, "documentation (a changelog)"
    if ext in LANGUAGES:
        return LANGUAGES[ext], None
    if ext in DOCUMENT_EXTENSIONS:
        return None, "documentation"
    if ext in DATA_EXTENSIONS:
        return None, "data or binary file"
    return None, "not a language this review covers"


def is_test_path(path: str) -> bool:
    return bool(_TEST_NAME.search(path) or _TEST_DIR.search(path))


def is_changelog_path(path: str) -> bool:
    return bool(_CHANGELOG.search(path))


def priority(language: str, path: str) -> tuple[int, int, str]:
    """Python, PowerShell and alert templates first, then the other languages, then Markdown; tests after the code they test."""
    return (0 if language in FIRST_LANGUAGES else 2 if language == "Markdown" else 1, 1 if is_test_path(path) else 0, path.lower())


@dataclass
class Row:
    kind: str  # keep | add | del
    new: int | None
    old: int | None
    text: str


@dataclass
class FileView:
    path: str
    language: str
    change_type: str
    rows: list[Row]
    new_lines: list[str]
    added: set[int] = field(default_factory=set)       # lines (in the new version) the pull request added or changed
    removed_at: set[int] = field(default_factory=set)  # the line that follows a block the pull request removed
    added_count: int = 0
    removed_count: int = 0
    whole_file: bool = True
    omitted_hunks: int = 0
    shown: str = ""
    extra: str = ""  # what else the reviewer is told about this file (for an alert template: the alerts, in words)
    outline: str = ""  # for a JSON file: where each changed part sits in the structure
    facts: str = ""  # facts about the project the file belongs to, read from its project files (for C#: the target framework and language version)
    old_text: Any = None  # the two versions as the client read them (they carry encoding facts: see core.ado_client.DecodedText)
    new_text: Any = None

    @property
    def new_line_count(self) -> int:
        return len(self.new_lines)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed_count)


def _clip(text: str, width: int = LINE_WIDTH) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def render_row(row: Row, width: int = LINE_WIDTH) -> str:
    if row.kind == "del":
        return f"- {'':>5} | {_clip(row.text, width)}"
    return f"{'+' if row.kind == 'add' else ' '} {row.new:>5} | {_clip(row.text, width)}"


def _opcodes(old: list[str], new: list[str]) -> list[tuple[str, int, int, int, int]]:
    """difflib's opcodes, after the lines the two versions share at the start and at the end are set aside: a change is usually a few places in a
    long file, and comparing only what lies between them is much faster. A very large changed middle is compared with difflib's junk heuristic."""
    limit = min(len(old), len(new))
    prefix = 0
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]:
        suffix += 1
    middle_old, middle_new = old[prefix:len(old) - suffix], new[prefix:len(new) - suffix]
    ops: list[tuple[str, int, int, int, int]] = []
    if prefix:
        ops.append(("equal", 0, prefix, 0, prefix))
    if middle_old or middle_new:
        matcher = difflib.SequenceMatcher(None, middle_old, middle_new, autojunk=len(middle_old) * len(middle_new) > MAX_MATCH_CELLS)
        ops.extend((tag, i1 + prefix, i2 + prefix, j1 + prefix, j2 + prefix) for tag, i1, i2, j1, j2 in matcher.get_opcodes())
    if suffix:
        ops.append(("equal", len(old) - suffix, len(old), len(new) - suffix, len(new)))
    return ops


def build_view(path: str, language: str, change_type: str, old_text: str | None, new_text: str,
               whole_file_lines: int = 350, context: int = 12, max_rows: int = 900, width: int = LINE_WIDTH) -> FileView:
    """The diff of one file, with the text shown to the reviewer. Raises ValueError when a file is too long to compare."""
    old_lines = (old_text or "").splitlines()
    new_lines = new_text.splitlines()
    if max(len(old_lines), len(new_lines)) > MAX_LINES_TO_COMPARE:
        raise ValueError(f"more than {MAX_LINES_TO_COMPARE} lines")

    rows: list[Row] = []
    added: set[int] = set()
    removed_at: set[int] = set()
    removed = 0
    for tag, i1, i2, j1, j2 in _opcodes(old_lines, new_lines):
        if tag == "equal":
            rows.extend(Row("keep", j1 + k + 1, i1 + k + 1, new_lines[j1 + k]) for k in range(i2 - i1))
            continue
        rows.extend(Row("del", None, k + 1, old_lines[k]) for k in range(i1, i2))
        rows.extend(Row("add", k + 1, None, new_lines[k]) for k in range(j1, j2))
        added.update(range(j1 + 1, j2 + 1))
        removed += i2 - i1
        if i2 > i1 and j2 == j1 and new_lines:  # code was only removed: the line that now follows it is where a comment can go
            removed_at.add(min(j1 + 1, len(new_lines)))

    view = FileView(path=path, language=language, change_type=change_type, rows=rows, new_lines=new_lines,
                    added=added, removed_at=removed_at, added_count=len(added), removed_count=removed)
    _render(view, whole_file_lines, context, max_rows, width)
    return view


def _render(view: FileView, whole_file_lines: int, context: int, max_rows: int, width: int = LINE_WIDTH) -> None:
    rows = view.rows
    if view.new_line_count <= whole_file_lines and len(rows) <= max_rows:
        view.whole_file = True
        view.shown = "\n".join(render_row(r, width) for r in rows)
        return

    view.whole_file = False
    changed = [i for i, r in enumerate(rows) if r.kind != "keep"]
    windows: list[list[int]] = []
    for index in changed:
        start, end = max(0, index - context), min(len(rows) - 1, index + context)
        if windows and start <= windows[-1][1] + 1:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])

    lines: list[str] = []
    shown_rows = 0
    last_end = -1
    for number, (start, end) in enumerate(windows):
        size = end - start + 1
        if shown_rows + size > max_rows and number > 0:
            view.omitted_hunks = len(windows) - number
            break
        if start > 0:
            lines.append("      ...")
        lines.extend(render_row(r, width) for r in rows[start:end + 1])
        shown_rows += size
        last_end = end
    if view.omitted_hunks or last_end < len(rows) - 1:
        lines.append("      ...")
    view.shown = "\n".join(lines)


def suggestable(view: FileView, start: int, end: int) -> bool:
    """A suggested replacement is only meaningful for lines the pull request itself changed."""
    return all(n in view.added for n in range(start, end + 1))

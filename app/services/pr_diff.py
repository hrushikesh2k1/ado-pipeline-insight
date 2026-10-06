"""What the reviewer is shown for a changed file, and which lines a comment may point at.

The two versions of a file are compared line by line. The reviewer sees every line with its number in the new version, marked
"+" when the pull request added or changed it and "-" when it removed it, so it can tell new code from old.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

LANGUAGES = {
    ".py": "Python", ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".sh": "Shell", ".sql": "SQL", ".yml": "YAML", ".yaml": "YAML", ".bicep": "Bicep", ".tf": "Terraform",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".js": "JavaScript", ".jsx": "JavaScript (React)",
    ".cs": "C#", ".go": "Go", ".java": "Java",
}
FIRST_LANGUAGES = ("Python", "PowerShell")  # reviewed first when a pull request has more files than can be reviewed

LOCK_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "composer.lock", "gemfile.lock", "cargo.lock", "go.sum", "packages.lock.json"}
DOCUMENT_EXTENSIONS = {".md", ".markdown", ".txt", ".rst"}
DATA_EXTENSIONS = {".json", ".csv", ".tsv", ".xml", ".toml", ".ini", ".cfg", ".conf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".xlsx", ".docx", ".pptx", ".dll", ".exe", ".pyc", ".whl"}
GENERATED = re.compile(r"(\.min\.(js|css)$|\.map$|\.designer\.cs$|\.g\.cs$|_pb2\.py$|\.generated\.)", re.IGNORECASE)

MAX_LINES_TO_COMPARE = 4000
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
    """Python and PowerShell first, then the other languages; tests after the code they test."""
    return (0 if language in FIRST_LANGUAGES else 1, 1 if is_test_path(path) else 0, path.lower())


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

    @property
    def new_line_count(self) -> int:
        return len(self.new_lines)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed_count)


def _clip(text: str) -> str:
    return text if len(text) <= LINE_WIDTH else text[:LINE_WIDTH - 1] + "…"


def render_row(row: Row) -> str:
    if row.kind == "del":
        return f"- {'':>5} | {_clip(row.text)}"
    return f"{'+' if row.kind == 'add' else ' '} {row.new:>5} | {_clip(row.text)}"


def build_view(path: str, language: str, change_type: str, old_text: str | None, new_text: str,
               whole_file_lines: int = 350, context: int = 12, max_rows: int = 900) -> FileView:
    """The diff of one file, with the text shown to the reviewer. Raises ValueError when a file is too long to compare."""
    old_lines = (old_text or "").splitlines()
    new_lines = new_text.splitlines()
    if max(len(old_lines), len(new_lines)) > MAX_LINES_TO_COMPARE:
        raise ValueError(f"more than {MAX_LINES_TO_COMPARE} lines")

    rows: list[Row] = []
    added: set[int] = set()
    removed_at: set[int] = set()
    removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
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
    _render(view, whole_file_lines, context, max_rows)
    return view


def _render(view: FileView, whole_file_lines: int, context: int, max_rows: int) -> None:
    rows = view.rows
    if view.new_line_count <= whole_file_lines and len(rows) <= max_rows:
        view.whole_file = True
        view.shown = "\n".join(render_row(r) for r in rows)
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
        lines.extend(render_row(r) for r in rows[start:end + 1])
        shown_rows += size
        last_end = end
    if view.omitted_hunks or last_end < len(rows) - 1:
        lines.append("      ...")
    view.shown = "\n".join(lines)


def suggestable(view: FileView, start: int, end: int) -> bool:
    """A suggested replacement is only meaningful for lines the pull request itself changed."""
    return all(n in view.added for n in range(start, end + 1))

"""What the second check may look up while it checks a finding: other files of the repository, at the commit being reviewed.

A finding is often about something outside the file it points at: the project's target framework, a setting's other uses, where a
name is defined, a file the same pull request changed. Reading one file cannot settle that, so the second check is given three
read-only tools (find_files, read_file, search_code). They only read; nothing is written to Azure DevOps. A result says how much was
searched, so "not found" in a partial search is not taken for "does not exist".
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

MAX_READ_LINES = 150
MAX_LINE_CHARS = 1500  # a line longer than this is cut, and the result says so (an alert's query is one long line of JSON)
MAX_RESULT_CHARS = 6000
MAX_FILE_BYTES = 150_000
MAX_SEARCH_FILES = 60  # files fetched by one search
MAX_FETCHES = 400  # file reads for one review: a guard for the Azure DevOps rate limit
MAX_MATCHES = 15
MAX_FIND = 40

SEARCH_SUFFIXES = {
    ".cs", ".csproj", ".props", ".targets", ".sln", ".config", ".json", ".xml", ".yml", ".yaml", ".ps1", ".psm1", ".psd1", ".py", ".sql", ".kql", ".md",
    ".sh", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".bicep", ".tf", ".toml", ".ini", ".cfg", ".txt", ".resx", ".razor", ".cshtml",
}
SKIPPED_DIRS = re.compile(r"(^|/)(node_modules|bin|obj|\.git|packages|dist|build|vendor|\.vs|__pycache__|\.venv|venv)/|\.min\.|package-lock\.json$", re.IGNORECASE)

TOOLS = [
    {"type": "function", "function": {
        "name": "find_files",
        "description": "List the files of the repository (at the commit being reviewed) whose path contains the text, for example 'WebApi.csproj' or 'appsettings'. Use it to locate a file before reading it.",
        "parameters": {"type": "object", "properties": {"contains": {"type": "string", "description": "text the path must contain, case-insensitive"}}, "required": ["contains"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": f"Read a file of the repository at the commit being reviewed: any file, not only the files of this pull request. Returns at most {MAX_READ_LINES} lines with their line numbers; give from_line to read further.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "path in the repository, for example src/Api/Api.csproj"}, "from_line": {"type": "integer", "description": "first line to read (default 1)"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Search the text of the repository's files for an exact piece of text (case-insensitive). Returns the matching lines with path and line number and says how many files were searched. A search that covered only some of the files and found nothing proves nothing.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "the text to find, for example a setting name or a type name"}, "path_contains": {"type": "string", "description": "optional: only search files whose path contains this"}}, "required": ["text"]}}},
]


def _clean_path(path: Any) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("/")


class RepoReader:
    """Read-only access to one repository at one commit, shared by the checks of a review (it is safe to use from several threads)."""

    def __init__(self, ado: Any, project: str, repository: str, commit: str, changed_paths: list[str] | None = None):
        self.ado, self.project, self.repository, self.commit = ado, project, repository, commit
        self.changed = [_clean_path(p) for p in changed_paths or []]
        self._files: list[str] | None = None
        self._files_tried = False
        self._cache: dict[str, tuple[str | None, str | None]] = {}
        self._fetches = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ the tree

    def files(self) -> tuple[list[str], bool]:
        """(paths, complete). When the repository's file list cannot be read, only the files of the pull request are known."""
        with self._lock:
            if not self._files_tried:
                self._files_tried = True
                listed = self.ado.list_repository_files(self.project, self.repository, self.commit) if hasattr(self.ado, "list_repository_files") else None
                self._files = [_clean_path(p) for p in listed] if listed is not None else None
            if self._files is None:
                return list(self.changed), False
            return self._files, True

    # ------------------------------------------------------------ reading

    def read(self, path: str) -> tuple[str | None, str | None]:
        """(text, None) or (None, why not). Each file is fetched once."""
        path = _clean_path(path)
        with self._lock:
            if path in self._cache:
                return self._cache[path]
            if self._fetches >= MAX_FETCHES:
                return None, "the limit of file reads for this review was reached"
            self._fetches += 1
        try:
            text, why = self.ado.get_item_text(self.project, self.repository, "/" + path, self.commit, MAX_FILE_BYTES)
        except Exception as exc:  # noqa: BLE001
            logger.info("PR review lookup: %s could not be read (%s)", path, type(exc).__name__)
            text, why = None, "unreadable"
        result = (text, None) if text is not None else (None, {"too_large": "the file is larger than the limit for a lookup", "binary": "not a text file"}.get(why or "", "the file does not exist at this commit or cannot be read"))
        with self._lock:
            self._cache[path] = result
        return result

    # ------------------------------------------------------------ the tools

    def find(self, contains: str) -> str:
        needle = _clean_path(contains).lower()
        if not needle:
            return "Give some text the path must contain."
        paths, complete = self.files()
        hits = [p for p in paths if needle in p.lower()]
        note = "" if complete else " (the repository's file list could not be read: only the files of this pull request are known)"
        if not hits:
            return f"No file path contains '{contains}'{note}."
        shown = "\n".join(hits[:MAX_FIND])
        return f"{len(hits)} file(s) contain '{contains}' in the path{note}:\n{shown}" + (f"\n... and {len(hits) - MAX_FIND} more" if len(hits) > MAX_FIND else "")

    def read_lines(self, path: str, from_line: Any = 1) -> str:
        text, why = self.read(path)
        if text is None:
            return f"{_clean_path(path)}: {why}."
        lines = text.splitlines()
        try:
            start = max(1, int(from_line or 1))
        except (TypeError, ValueError):
            start = 1
        chunk = lines[start - 1:start - 1 + MAX_READ_LINES]
        if not chunk:
            return f"{_clean_path(path)} has {len(lines)} line(s); nothing from line {start}."
        body = "\n".join(f"{n:>5} | {t[:MAX_LINE_CHARS]}" + (f" ...(line cut at {MAX_LINE_CHARS} characters)" if len(t) > MAX_LINE_CHARS else "") for n, t in enumerate(chunk, start))
        end = start + len(chunk) - 1
        more = f"\n(lines {start}-{end} of {len(lines)}; call again with from_line={end + 1} to read on)" if end < len(lines) else f"\n(lines {start}-{end} of {len(lines)})"
        return f"{_clean_path(path)}:\n{body}{more}"

    def search(self, text: str, path_contains: str = "", near: str = "") -> str:
        needle = str(text or "").strip()
        if len(needle) < 2:
            return "Give at least two characters to search for."
        paths, complete = self.files()
        want = _clean_path(path_contains).lower()
        candidates = [p for p in paths if (not want or want in p.lower()) and "." + p.rsplit(".", 1)[-1].lower() in SEARCH_SUFFIXES and not SKIPPED_DIRS.search(p)]
        changed = set(self.changed)
        home = _clean_path(near).rsplit("/", 1)[0] if near else ""

        def closeness(p: str) -> int:
            shared = 0
            for a, b in zip(p.split("/"), home.split("/")):
                if a != b:
                    break
                shared += 1
            return shared

        with self._lock:
            cached = {p for p in candidates if p in self._cache}
        ordered = sorted(candidates, key=lambda p: (p not in cached, p not in changed, -closeness(p), p))
        to_read = [p for p in ordered if p in cached][:] + [p for p in ordered if p not in cached][:MAX_SEARCH_FILES]
        with ThreadPoolExecutor(max_workers=4) as pool:
            texts = list(pool.map(lambda p: (p, self.read(p)[0]), to_read))
        lowered = needle.lower()
        matches: list[str] = []
        hit_files: set[str] = set()
        searched = 0
        for path, content in texts:
            if content is None:
                continue
            searched += 1
            for number, line in enumerate(content.splitlines(), 1):
                if lowered in line.lower():
                    hit_files.add(path)
                    if len(matches) < MAX_MATCHES:
                        matches.append(f"{path}:{number}: {line.strip()[:240]}")
        coverage = f"Searched {searched} of {len(candidates)} candidate file(s)" + ("" if complete else " (the repository's file list could not be read: only the files of this pull request were candidates)")
        partial = searched < len(candidates) or not complete
        if not matches:
            return coverage + f"; no line contains '{needle}'." + (" This search did not cover every file, so it does not show that the text is absent." if partial else "")
        found = f"{len(hit_files)} file(s) contain it. " if len(hit_files) > 1 else ""
        return f"{coverage}. {found}Matches:\n" + "\n".join(matches) + (f"\n(only the first {MAX_MATCHES} matches are shown)" if sum(1 for _, c in texts if c) and len(matches) >= MAX_MATCHES else "")


class ToolBelt:
    """The tools for one check, with a note of what was looked at (shown with the finding)."""

    def __init__(self, reader: RepoReader, near: str = "", deadline: float | None = None):
        self.reader, self.near, self.deadline = reader, near, deadline  # deadline: a time.monotonic() value after which no lookup is made
        self.looked: list[str] = []
        self.seen: list[str] = []  # what the lookups returned: the checker may quote it as evidence

    def _note(self, text: str) -> None:
        if text not in self.looked:
            self.looked.append(text)

    def run(self, name: str, args: dict[str, Any]) -> str:
        args = args if isinstance(args, dict) else {}
        if self.deadline is not None and time.monotonic() > self.deadline:
            return "The time for this review is over: no more lookups are possible. Answer now with what you have."
        try:
            if name == "find_files":
                self._note(f"searched file names for \"{str(args.get('contains') or '')[:40]}\"")
                result = self.reader.find(str(args.get("contains") or ""))
            elif name == "read_file":
                self._note(f"read {_clean_path(args.get('path'))}")
                result = self.reader.read_lines(str(args.get("path") or ""), args.get("from_line"))
            elif name == "search_code":
                self._note(f"searched the code for \"{str(args.get('text') or '')[:40]}\"")
                result = self.reader.search(str(args.get("text") or ""), str(args.get("path_contains") or ""), self.near)
            else:
                return f"Unknown tool '{name}'. Use find_files, read_file or search_code."
        except Exception as exc:  # noqa: BLE001
            logger.info("PR review lookup %s failed (%s)", name, type(exc).__name__)
            return "That lookup failed."
        result = result if len(result) <= MAX_RESULT_CHARS else result[:MAX_RESULT_CHARS] + "\n... (cut)"
        self.seen.append(result)
        return result


# ---------------------------------------------------------------- project facts: the C# language version

# Microsoft, "Language versioning - C# reference", section Defaults
_DOTNET_DEFAULT = {5: "9.0", 6: "10", 7: "11", 8: "12", 9: "13", 10: "14", 11: "15"}


def default_csharp(framework: str) -> str | None:
    """The C# language version the compiler uses by default for a target framework moniker, or None when it is not one the docs list."""
    tfm = framework.strip().lower()
    modern = re.match(r"net(\d+)\.\d+", tfm)
    if modern:
        return _DOTNET_DEFAULT.get(int(modern.group(1)))
    if re.match(r"netcoreapp3\.", tfm):
        return "8.0"
    if re.match(r"netcoreapp2\.", tfm):
        return "7.3"
    if tfm == "netstandard2.1":
        return "8.0"
    if re.match(r"netstandard(2\.0|1\.)", tfm) or re.match(r"net\d{2,3}$", tfm):  # .NET Standard 2.0 and 1.x, .NET Framework (net48, net472, ...)
        return "7.3"
    return None


_TFM = re.compile(r"<TargetFrameworks?>\s*([^<]+?)\s*</TargetFrameworks?>", re.IGNORECASE)
_LANGVERSION = re.compile(r"<LangVersion>\s*([^<]+?)\s*</LangVersion>", re.IGNORECASE)


def _project_settings(text: str) -> tuple[list[str], str | None]:
    frameworks = [f.strip() for f in ";".join(_TFM.findall(text)).split(";") if f.strip()]
    lang = _LANGVERSION.search(text)
    return frameworks, lang.group(1) if lang else None


def csharp_facts(reader: RepoReader, path: str) -> str:
    """What the project of a C# file says about its target framework and C# version, from its .csproj (and Directory.Build.props), in plain words.
    Empty when no project file is found."""
    paths, _ = reader.files()
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        by_dir.setdefault(p.rsplit("/", 1)[0] if "/" in p else "", []).append(p)
    folder = _clean_path(path).rsplit("/", 1)[0] if "/" in _clean_path(path) else ""
    project = None
    while True:
        project = next((p for p in by_dir.get(folder, []) if p.lower().endswith(".csproj")), None)
        if project or not folder:
            break
        folder = folder.rsplit("/", 1)[0] if "/" in folder else ""
    if not project:
        return ""
    text, _why = reader.read(project)
    if text is None:
        return ""
    frameworks, lang = _project_settings(text)
    source = project
    if not frameworks or lang is None:  # a Directory.Build.props above the project may set what the project does not
        parts = project.split("/")[:-1]
        while True:
            props = "/".join(parts + ["Directory.Build.props"])
            if props in paths:
                props_text, _why = reader.read(props)
                if props_text is not None:
                    found_frameworks, found_lang = _project_settings(props_text)
                    if not frameworks and found_frameworks:
                        frameworks, source = found_frameworks, props
                    lang = lang or found_lang
            if not parts:
                break
            parts.pop()
    if not frameworks:
        return f"Project facts: this file belongs to {project}, which does not state a target framework in the project file or a Directory.Build.props (it may come from a shared build file), so the C# version is not known."
    if any("$(" in f for f in frameworks):
        return f"Project facts: this file belongs to {project}, whose target framework is set by a property ({', '.join(frameworks)}), so the C# version is not known."
    versions = [(f, default_csharp(f)) for f in frameworks]
    stated = ", ".join(f"{f} (C# {v})" if v else f"{f} (a target the docs do not list)" for f, v in versions)
    text_out = f"Project facts: this file belongs to {project}, which targets {stated}"
    if source != project:
        text_out += f" (set in {source})"
    text_out += ". Microsoft: the default C# language version follows the target framework."
    if lang:
        text_out += f" The project sets LangVersion to {lang}, which overrides that default."
    known = [float(v) for _f, v in versions if v]
    if known and not lang:
        lowest = min(known)
        text_out += f" Syntax introduced in C# {lowest:g} or earlier is valid here; syntax introduced after that is not."
        if lowest >= 12:
            text_out += " For example collection expressions ([] and [a, b]) and primary constructors (both C# 12) are valid: do not report them as invalid."
    return text_out

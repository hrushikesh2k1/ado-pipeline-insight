"""Read a pipeline's real YAML (including the templates it includes) and tie telemetry findings to the exact step.

Telemetry says *where the time goes and what fails*; the YAML says *what the pipeline already does about it*. Putting
the two together lets the recommendations name the real step, skip advice that is already applied (for example
"add caching" when the job has a Cache@2 step) and show the change as a diff against the customer's own file.

Nothing here invents facts: a step is only located when its name matches the YAML, a diff is only shown as a diff when
its lines really exist in the file, and retry advice is only given when the failure looks transient. Every other YAML
block is labelled as an example.
"""
from __future__ import annotations

import difflib
import logging
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests
import yaml

from app.services.failure_kind import best_error_line, classify_failure
from app.services.root_causes import identify_cause

logger = logging.getLogger(__name__)

# What the language model is given of the pipeline files. Generous, so it sees the whole file in practice; the cap only
# protects the model's context window.
MAIN_PROMPT_CHARS = 40_000
TEMPLATE_PROMPT_CHARS = 20_000
TEMPLATES_PROMPT_TOTAL = 80_000
MAX_TEMPLATE_DEPTH = 8
MAX_TEMPLATE_FILES = 60
STEP_KINDS = ("task", "script", "bash", "powershell", "pwsh", "checkout", "download", "publish")

RETRY_EXAMPLE = "# example, not from your file: add this to the step named '{task}'\nretryCountOnTaskFailure: 2"
DEBUG_EXAMPLE = ("# example, not from your file: verbose logs for the next run, so the step log shows the first real error\n"
                 "variables:\n  system.debug: true")
CATEGORY_EXAMPLES = {
    "caching_opportunity": ("# example, not from your file: cache what this step downloads (replace the key file and the folder)\n- task: Cache@2\n"
                            "  displayName: Cache dependencies\n  inputs:\n    key: 'deps | \"$(Agent.OS)\" | <lock file>'\n    restoreKeys: |\n"
                            "      deps | \"$(Agent.OS)\"\n    path: <folder the tool downloads into>"),
    "bottleneck": ("# example, not from your file: run independent jobs in parallel (a job without dependsOn starts immediately)\njobs:\n"
                   "  - job: SlowPart\n    steps:\n      - script: echo the slow work\n  - job: OtherPart\n    steps:\n      - script: echo independent work"),
    "parallelization_opportunity": ("# example, not from your file: run independent jobs in parallel (a job without dependsOn starts immediately)\njobs:\n"
                                    "  - job: PartA\n    steps:\n      - script: echo part A\n  - job: PartB\n    steps:\n      - script: echo part B"),
    "queue_capacity": "# example, not from your file: run on a pool with more agents\npool:\n  name: <pool with more agents>",
    "regression": ("# example, not from your file: fail fast instead of waiting when the step is slower than expected\n- task: <the slow step>\n"
                   "  timeoutInMinutes: 15"),
    "other": ("# example, not from your file: fail fast instead of waiting when the step is slower than expected\n- task: <the step>\n"
              "  timeoutInMinutes: 15"),
}

# How to cache each package ecosystem on Azure Pipelines (Cache@2). The key file is the usual lock/manifest file and
# is stated as an assumption in the advice, never presented as something we found in the customer's repository.
CACHE_RECIPES: dict[str, dict[str, str]] = {
    "npm": {
        "name": "npm", "key": "npm | \"$(Agent.OS)\" | package-lock.json", "restore": "npm | \"$(Agent.OS)\"",
        "path": "$(Pipeline.Workspace)/.npm", "key_file": "package-lock.json",
        "hint": "Point npm at the cached folder, for example `npm ci --cache $(Pipeline.Workspace)/.npm`.",
    },
    "pip": {
        "name": "pip", "key": "pip | \"$(Agent.OS)\" | requirements.txt", "restore": "pip | \"$(Agent.OS)\"",
        "path": "$(Pipeline.Workspace)/.pip", "key_file": "requirements.txt",
        "hint": "Point pip at the cached folder with the variable `PIP_CACHE_DIR: $(Pipeline.Workspace)/.pip`.",
    },
    "nuget": {
        "name": "NuGet", "key": "nuget | \"$(Agent.OS)\" | **/*.csproj", "restore": "nuget | \"$(Agent.OS)\"",
        "path": "$(Pipeline.Workspace)/.nuget/packages", "key_file": "**/*.csproj",
        "hint": "Point NuGet at the cached folder with the variable `NUGET_PACKAGES: $(Pipeline.Workspace)/.nuget/packages`.",
    },
    "maven": {
        "name": "Maven", "key": "maven | \"$(Agent.OS)\" | **/pom.xml", "restore": "maven | \"$(Agent.OS)\"",
        "path": "$(Pipeline.Workspace)/.m2/repository", "key_file": "**/pom.xml",
        "hint": "Point Maven at the cached folder with `-Dmaven.repo.local=$(Pipeline.Workspace)/.m2/repository`.",
    },
    "gradle": {
        "name": "Gradle", "key": "gradle | \"$(Agent.OS)\" | **/*.gradle*", "restore": "gradle | \"$(Agent.OS)\"",
        "path": "$(Pipeline.Workspace)/.gradle", "key_file": "**/*.gradle*",
        "hint": "Point Gradle at the cached folder with the variable `GRADLE_USER_HOME: $(Pipeline.Workspace)/.gradle`.",
    },
}


# ---------------------------------------------------------------------------------------------------------------------
# Structure of the pipeline file (and the templates it includes)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class StepInfo:
    index: int
    display: str
    name: str
    kind: str
    task: str
    script: str
    retry: int
    ecosystem: str | None
    file: str = ""

    @property
    def label(self) -> str:
        script_line = self.script.strip().splitlines()[0][:60] if self.script.strip() else ""
        return self.display or self.name or self.task or script_line or f"step {self.index + 1}"


@dataclass
class JobInfo:
    name: str
    display: str
    depends_on: list[str]
    steps: list[StepInfo]
    file: str = ""

    @property
    def has_cache(self) -> bool:
        return any(s.task.lower().startswith(("cache@", "cachebeta@")) for s in self.steps)


@dataclass
class StageInfo:
    name: str
    display: str
    jobs: list[JobInfo]


@dataclass
class YamlFacts:
    stages: list[StageInfo] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)  # template references that could not be read
    files: dict[str, str] = field(default_factory=dict)  # every file that was read: the pipeline file and its templates
    template_errors: dict[str, str] = field(default_factory=dict)  # template reference -> why it could not be read


@dataclass
class YamlContext:
    """Outcome of trying to read a pipeline's YAML; `ok` is False with a human-readable `reason` when it could not."""
    ok: bool
    reason: str = ""
    path: str = ""
    branch: str = ""
    content: str = ""
    facts: YamlFacts | None = None

    @property
    def unresolved(self) -> list[str]:
        return self.facts.templates if self.facts else []

    @property
    def unresolved_with_reasons(self) -> list[str]:
        errors = self.facts.template_errors if self.facts else {}
        return [f"{ref} ({errors[ref]})" if errors.get(ref) else ref for ref in self.unresolved]


Loader = Callable[[str, str], "tuple[str, str] | None"]  # (template reference, referencing file key) -> (file key, text)


def file_key(path: str) -> str:
    return path.strip().lstrip("/")


def _is_expression(key: Any) -> bool:
    return isinstance(key, str) and key.strip().startswith("${{")


def _flatten(items: Any) -> list[Any]:
    """Expand `${{ if ... }}` / `${{ each ... }}` wrappers: whatever they guard is treated as part of the list."""
    result: list[Any] = []
    for item in items if isinstance(items, list) else [items]:
        if isinstance(item, dict) and len(item) == 1 and _is_expression(next(iter(item))):
            result.extend(_flatten(next(iter(item.values()))))
        elif item is not None:
            result.append(item)
    return result


def _safe_load(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _detect_ecosystem(kind: str, value: str, inputs: dict[str, Any]) -> str | None:
    task = value.lower() if kind == "task" else ""
    text = " ".join([value, *[str(v) for v in inputs.values()]]).lower()
    command = str(inputs.get("command", "")).lower()
    if re.search(r"\b(npm|yarn|pnpm)\s+(ci|install|i)\b", text) or (task.startswith("npm@") and command in ("", "install", "ci")):
        return "npm"
    if re.search(r"\bpip3?\s+install\b", text):
        return "pip"
    if task.startswith(("dotnetcorecli@", "nugetcommand@", "nugetrestore")) or re.search(r"\bdotnet\s+(restore|build|test|publish)\b", text):
        return "nuget"
    if task.startswith("maven@") or re.search(r"\bmvnw?\b", text):
        return "maven"
    if task.startswith("gradle@") or re.search(r"\bgradlew?\b", text):
        return "gradle"
    if task.startswith("docker@") or re.search(r"\bdocker\s+build\b", text):
        return "docker"
    return None


def _parse_step(index: int, raw: Any, file: str) -> StepInfo | None:
    if not isinstance(raw, dict):
        return None
    kind = next((k for k in STEP_KINDS if k in raw), "other")
    value = str(raw.get(kind) or "")
    inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
    try:
        retry = int(raw.get("retryCountOnTaskFailure") or 0)
    except (TypeError, ValueError):
        retry = 0
    return StepInfo(
        index=index,
        display=str(raw.get("displayName") or ""),
        name=str(raw.get("name") or ""),
        kind=kind,
        task=value if kind == "task" else "",
        script=value if kind in ("script", "bash", "powershell", "pwsh") else "",
        retry=retry,
        ecosystem=_detect_ecosystem(kind, value, inputs),
        file=file,
    )


def _job_steps_raw(job: dict[str, Any]) -> list[Any]:
    steps = list(_flatten(job.get("steps") or []))
    strategy = job.get("strategy")
    if not steps and isinstance(strategy, dict):  # deployment jobs keep their steps under strategy.<kind>.<phase>
        for kind in ("runOnce", "rolling", "canary"):
            block = strategy.get(kind)
            for phase in ("preDeploy", "deploy", "routeTraffic", "postRouteTraffic"):
                if isinstance(block, dict) and isinstance(block.get(phase), dict):
                    steps.extend(_flatten(block[phase].get("steps") or []))
    return steps


Item = tuple[Any, str, "tuple[str, ...]"]  # (raw item, file it came from, chain of files that led to it)


class _Parser:
    """Walks a pipeline document, splicing in the contents of `template:` references that the loader can read."""

    def __init__(self, loader: Loader | None):
        self.loader = loader
        self.files: dict[str, str] = {}
        self.unresolved: list[str] = []
        self.errors: dict[str, str] = {}

    def items(self, raw: Any, kind: str, file: str, chain: tuple[str, ...]) -> list[Item]:
        out: list[Item] = []
        for item in _flatten(raw or []):
            if isinstance(item, dict) and isinstance(item.get("template"), str):
                out.extend(self._template(item["template"], kind, file, chain))
            else:
                out.append((item, file, chain))
        return out

    def miss(self, ref: str, reason: str = "") -> list[Item]:
        if ref not in self.unresolved:
            self.unresolved.append(ref)
        self.errors.setdefault(ref, reason or getattr(self.loader, "errors", {}).get(ref, "it could not be read"))
        return []

    def _template(self, ref: str, kind: str, file: str, chain: tuple[str, ...]) -> list[Item]:
        if "${{" in ref:
            return self.miss(ref, "its path contains a pipeline expression that can only be resolved when the pipeline runs")
        if self.loader is None:
            return self.miss(ref, "templates were not read")
        if len(chain) >= MAX_TEMPLATE_DEPTH or len(self.files) >= MAX_TEMPLATE_FILES:
            return self.miss(ref, "the limit on included templates was reached")
        loaded = self.loader(ref, file)
        if not loaded:
            display, reason = getattr(self.loader, "last", (ref, ""))
            return self.miss(display or ref, reason)
        key, text = loaded
        if key in chain:  # a template that includes itself
            return []
        self.files.setdefault(key, text)
        doc = _safe_load(text)
        if not isinstance(doc, dict):
            return self.miss(ref, "it is not valid YAML")
        return self.items(doc.get(kind), kind, key, chain + (key,))

    def job(self, raw: Any, file: str, chain: tuple[str, ...], fallback_name: str) -> JobInfo | None:
        if not isinstance(raw, dict):
            return None
        steps = [s for i, (r, f, _c) in enumerate(self.items(_job_steps_raw(raw), "steps", file, chain)) if (s := _parse_step(i, r, f))]
        depends = raw.get("dependsOn") or []
        return JobInfo(
            name=str(raw.get("job") or raw.get("deployment") or fallback_name),
            display=str(raw.get("displayName") or ""),
            depends_on=[depends] if isinstance(depends, str) else [str(d) for d in depends],
            steps=steps,
            file=file,
        )

    def jobs(self, raw: Any, file: str, chain: tuple[str, ...]) -> list[JobInfo]:
        parsed = [self.job(r, f, c, f"job {i + 1}") for i, (r, f, c) in enumerate(self.items(raw, "jobs", file, chain))]
        return [j for j in parsed if j]

    def stages(self, doc: dict[str, Any], file: str, chain: tuple[str, ...]) -> list[StageInfo]:
        if doc.get("stages"):
            found = []
            for i, (raw, f, c) in enumerate(self.items(doc["stages"], "stages", file, chain)):
                if isinstance(raw, dict):
                    found.append(StageInfo(str(raw.get("stage") or f"stage {i + 1}"), str(raw.get("displayName") or ""), self.jobs(raw.get("jobs"), f, c)))
            return found
        if doc.get("jobs"):
            return [StageInfo("", "", self.jobs(doc["jobs"], file, chain))]
        if doc.get("steps"):
            job = self.job({"steps": doc["steps"]}, file, chain, "job")
            return [StageInfo("", "", [job] if job else [])]
        return []


def parse_pipeline_yaml(content: str, path: str = "", loader: Loader | None = None) -> YamlFacts | None:
    """Structure of an Azure Pipelines YAML file and the templates it includes, or None when it is not a pipeline file."""
    doc = _safe_load(content)
    if not isinstance(doc, dict):
        return None
    main = file_key(path)
    parser = _Parser(loader)
    chain = (main,)
    stages = parser.stages(doc, main, chain)
    extends = doc.get("extends")
    if not stages and isinstance(extends, dict) and isinstance(extends.get("template"), str):
        ref = extends["template"]
        loaded = loader(ref, main) if loader and "${{" not in ref else None
        if loaded and isinstance(inner := _safe_load(loaded[1]), dict):
            parser.files.setdefault(loaded[0], loaded[1])
            stages = parser.stages(inner, loaded[0], chain + (loaded[0],))
        else:
            parser.miss(ref)
    return YamlFacts(stages=stages, templates=parser.unresolved, files={main: content, **parser.files}, template_errors=parser.errors)


# ---------------------------------------------------------------------------------------------------------------------
# Matching telemetry names to YAML steps
# ---------------------------------------------------------------------------------------------------------------------

def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


_EXPRESSION = re.compile(r"\$\{\{.*?\}\}|\$\([^)]*\)")
MIN_LITERAL_CHARS = 8  # a name that is mostly an expression ("${{ parameters.name }}") would match anything


def _expanded_name_pattern(display: str) -> re.Pattern[str] | None:
    """A regex for a displayName that contains template expressions: the run data holds the expanded name
    ("Deploy AKS Alerts usgovvirginia"), the YAML holds "Deploy AKS Alerts ${{ parameters.region }}"."""
    if not _EXPRESSION.search(display):
        return None
    literals = _EXPRESSION.split(display)
    if sum(len(piece.strip()) for piece in literals) < MIN_LITERAL_CHARS:
        return None
    return re.compile("^" + ".+".join(re.escape(piece) for piece in literals) + "$", re.IGNORECASE)


def _step_matches(step: StepInfo, wanted: str) -> bool:
    first_line = step.script.strip().splitlines()[0] if step.script.strip() else ""
    return bool(wanted) and wanted in {_norm(step.display), _norm(step.name), _norm(step.task), _norm(first_line)}


def _step_matches_expanded(step: StepInfo, wanted: str) -> bool:
    pattern = _expanded_name_pattern(step.display)
    return bool(wanted and pattern and pattern.match(wanted.strip()))


def _matching_steps(facts: YamlFacts, wanted: str) -> tuple[list[tuple[StageInfo, JobInfo, StepInfo]], bool]:
    """(steps the name can refer to, whether they matched through a template expression). A literal name wins over an expression."""
    every = [(st, jb, sp) for st in facts.stages for jb in st.jobs for sp in jb.steps]
    literal = [hit for hit in every if _step_matches(hit[2], wanted)]
    if literal:
        return literal, False
    return [hit for hit in every if _step_matches_expanded(hit[2], wanted)], True


def step_candidates(facts: YamlFacts | None, task_name: str | None) -> list[StepInfo]:
    """The distinct steps (by file and name) the telemetry task name can refer to."""
    if not facts or not task_name:
        return []
    hits, _by_expression = _matching_steps(facts, _norm(task_name))
    return list({(sp.file, sp.display): sp for _st, _jb, sp in hits}.values())


def locate_step(facts: YamlFacts | None, stage_name: str | None, task_name: str | None) -> tuple[StageInfo, JobInfo, StepInfo] | None:
    """The step the telemetry task name refers to; when several steps share the name, the one in the named stage wins."""
    if not facts or not task_name:
        return None
    hits, by_expression = _matching_steps(facts, _norm(task_name))
    if by_expression and len({(sp.file, sp.display) for _st, _jb, sp in hits}) != 1:
        hits = []  # names written with template expressions are only trusted when they all point at one step
    if len(hits) > 1:
        in_stage = [h for h in hits if _norm(stage_name) in (_norm(h[0].name), _norm(h[0].display))]
        hits = in_stage or hits
    return hits[0] if hits else None


# ---------------------------------------------------------------------------------------------------------------------
# Exact-line edits, rendered as a unified diff against the customer's own file
# ---------------------------------------------------------------------------------------------------------------------

_DISPLAY_RE = re.compile(r"^(\s*)(- )?displayName:\s*(.+?)\s*$")


def _find_step_lines(lines: list[str], display: str) -> tuple[int, int, int] | None:
    """(line of the step's `displayName`, column of its keys, line where its `- ` list item starts)."""
    wanted = _norm(display)
    for i, line in enumerate(lines):
        match = _DISPLAY_RE.match(line)
        if not match or _norm(match.group(3).strip("'\"")) != wanted:
            continue
        key_col = len(match.group(1)) + (2 if match.group(2) else 0)
        if match.group(2):
            return i, key_col, i
        for j in range(i - 1, -1, -1):
            text = lines[j]
            if text.strip() and len(text) - len(text.lstrip()) == key_col - 2 and text.lstrip().startswith("- "):
                return i, key_col, j
            if text.strip() and len(text) - len(text.lstrip()) < key_col - 2:
                break
    return None


def _diff(original: list[str], edited: list[str], path: str) -> str:
    return "\n".join(difflib.unified_diff(original, edited, fromfile=f"a/{path.lstrip('/')}", tofile=f"b/{path.lstrip('/')}", n=2, lineterm=""))


def diff_add_retry(content: str, display: str, path: str, retries: int = 2) -> str | None:
    """Diff that adds `retryCountOnTaskFailure` to the step with this displayName, or None if it cannot be located."""
    lines = content.splitlines()
    found = _find_step_lines(lines, display) if display else None
    if not found:
        return None
    at, key_col, _start = found
    edited = lines[: at + 1] + [" " * key_col + f"retryCountOnTaskFailure: {retries}"] + lines[at + 1:]
    return _diff(lines, edited, path)


def cache_step_lines(ecosystem: str, dash_col: int) -> list[str]:
    recipe = CACHE_RECIPES[ecosystem]
    pad = " " * dash_col
    return [
        f"{pad}- task: Cache@2",
        f"{pad}  displayName: Cache {recipe['name']} packages",
        f"{pad}  inputs:",
        f"{pad}    key: '{recipe['key']}'",
        f"{pad}    restoreKeys: |",
        f"{pad}      {recipe['restore']}",
        f"{pad}    path: {recipe['path']}",
    ]


def diff_add_cache(content: str, display: str, ecosystem: str, path: str) -> str | None:
    """Diff that inserts a Cache@2 step directly before the step with this displayName, or None if it cannot be located."""
    if ecosystem not in CACHE_RECIPES or not display:
        return None
    lines = content.splitlines()
    found = _find_step_lines(lines, display)
    if not found:
        return None
    _at, key_col, start = found
    edited = lines[:start] + cache_step_lines(ecosystem, key_col - 2) + lines[start:]
    return _diff(lines, edited, path)


# ---------------------------------------------------------------------------------------------------------------------
# Checking a diff written by the language model against the real files
# ---------------------------------------------------------------------------------------------------------------------

def diff_added_lines(diff: str) -> list[str]:
    """The lines a diff adds, without the leading '+': what the customer would paste into the file."""
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


def _resolve_file(path: str, files: dict[str, str]) -> str | None:
    clean = path.strip().removeprefix("a/").removeprefix("b/").lstrip("/")
    if clean in files:
        return files[clean]
    for key, text in files.items():
        bare = key.split("@")[0]
        if bare == clean.split("@")[0] or bare.endswith("/" + clean) or clean.endswith("/" + bare):
            return text
    return None


def _contains_block(lines: list[str], block: list[str]) -> bool:
    return any(lines[i:i + len(block)] == block for i in range(len(lines) - len(block) + 1))


def check_diff(diff: str, files: dict[str, str]) -> bool:
    """True when every hunk's context and removed lines exist, in order, in the file the diff names.

    Line numbers in the hunk headers are ignored (models get them wrong); the content has to match the real file."""
    path, hunks, current = "", [], None
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = line[4:].strip()
            continue
        if line.startswith("+++ "):
            current = None
            continue
        if line.startswith("@@"):
            current = []
            hunks.append((path, current))
            continue
        if current is None:
            current = []
            hunks.append((path, current))
        if line[:1] in (" ", "-"):
            current.append(line[1:].rstrip())
        elif line == "":
            current.append("")
    if not path or not hunks:
        return False
    for hunk_path, old in hunks:
        while old and not old[-1]:
            old.pop()
        text = _resolve_file(hunk_path, files)
        if text is None or not any(line.strip() for line in old):
            return False
        if not _contains_block([ln.rstrip() for ln in text.splitlines()], old):
            return False
    return True


_DIFF_FENCE = re.compile(r"```diff[ \t]*\r?\n(.*?)\r?\n```", re.IGNORECASE | re.DOTALL)
_YAML_FENCE = re.compile(r"```(?:ya?ml)[ \t]*\r?\n.*?\r?\n```", re.IGNORECASE | re.DOTALL)
_ANY_FENCE = re.compile(r"```")


EXAMPLE_LABEL = "# example, not from your file"


def _is_labelled_example(fence: str) -> bool:
    body = fence.split("\n", 1)[1] if "\n" in fence else ""
    return body.lstrip().startswith(EXAMPLE_LABEL)


def validate_model_snippets(findings: list[dict[str, Any]], ctx: YamlContext | None) -> list[dict[str, Any]]:
    """A diff from the model is only shown as a diff when it matches the customer's real files. For a failing step nothing else of the
    model's is shown as code: a diff that does not match, or YAML we did not label, is a guess at the file's structure (the model once
    invented an `alertNotification:` block), so it is removed and the block derived from the error text takes its place. For other kinds of
    finding the added lines of a diff that does not match are kept as a snippet labelled an example."""
    files = ctx.facts.files if ctx and ctx.ok and ctx.facts else {}
    checked: list[dict[str, Any]] = []
    for finding in findings:
        text = str(finding.get("recommendation") or "")
        failing_step = finding.get("category") == "flaky_step"

        def convert(match: re.Match[str], failing_step: bool = failing_step) -> str:
            diff = match.group(1)
            if files and check_diff(diff, files):
                return match.group(0)
            if failing_step:
                return ""
            why = "the suggested diff could not be matched to your pipeline files" if files else "your pipeline files were not available to check it against"
            return "```yaml\n" + "\n".join([f"{EXAMPLE_LABEL} ({why})", *diff_added_lines(diff)]) + "\n```"

        converted = _DIFF_FENCE.sub(convert, text)
        if failing_step:
            converted = _YAML_FENCE.sub(lambda m: m.group(0) if _is_labelled_example(m.group(0)) else "", converted)
        if converted != text:
            converted = re.sub(r"\n{3,}", "\n\n", converted)
            checked.append({**finding, "recommendation": converted})
        else:
            checked.append(finding)
    return checked


# ---------------------------------------------------------------------------------------------------------------------
# Fetching the file and its templates
# ---------------------------------------------------------------------------------------------------------------------

def _http_reason(exc: requests.HTTPError) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return "the Azure DevOps token cannot read the repository (it needs the 'Code (Read)' scope)"
    if status == 404:
        return "the pipeline file was not found in its repository"
    return f"Azure DevOps returned an error ({status or 'unknown'})"


def _repository_resources(doc: Any) -> dict[str, dict[str, Any]]:
    resources = doc.get("resources") if isinstance(doc, dict) else None
    repos = resources.get("repositories") if isinstance(resources, dict) else None
    return {str(r["repository"]): r for r in repos or [] if isinstance(r, dict) and r.get("repository")}


def split_ref(ref: Any) -> tuple[str | None, str]:
    """(version, version type) for a git ref as written in a pipeline: refs/heads/x, refs/tags/x, a commit id or a bare branch name."""
    text = str(ref or "").strip()
    if not text:
        return None, "branch"
    if text.startswith("refs/heads/"):
        return text[len("refs/heads/"):], "branch"
    if text.startswith("refs/tags/"):
        return text[len("refs/tags/"):], "tag"
    if re.fullmatch(r"[0-9a-fA-F]{40}", text):
        return text, "commit"
    return text, "branch"


class TemplateLoader:
    """Reads `template:` files from the same repository (path relative to the including file, or from the repo root when it
    starts with `/`) or from a repository declared under `resources.repositories` (`file.yml@alias`, from that repo's root).
    When a template cannot be read, `errors` says why."""

    def __init__(self, client: Any, project: str, repo_id: str, branch: str, resources: dict[str, dict[str, Any]]):
        self.client, self.project, self.repo_id, self.branch, self.resources = client, project, repo_id, branch, resources
        self.cache: dict[str, str | None] = {}
        self.errors: dict[str, str] = {}
        self.last: tuple[str, str] = ("", "")  # (name of the last template that failed, why)

    def _fail(self, ref: str, reason: str, display: str | None = None) -> None:
        """`display` is the path that was actually tried (a relative `../x.yml` means different files from different places)."""
        name = display or ref
        self.last = (name, reason)
        self.errors[name] = reason
        logger.info("Template '%s' not read: %s", name, reason)

    def _target(self, ref: str, effective: str) -> tuple[str, str, str | None, str] | None:
        if not effective or effective == "self":
            return (self.project, self.repo_id, *split_ref(self.branch))
        repo = self.resources.get(effective)
        if not repo:
            self._fail(ref, f"repository alias '{effective}' is not declared under resources.repositories in the pipeline file")
            return None
        if str(repo.get("type") or "git") != "git":
            self._fail(ref, f"repository '{effective}' is of type '{repo.get('type')}'; only Azure Repos (git) is supported")
            return None
        repo_project, _, repo_name = str(repo.get("name") or "").rpartition("/")
        return (repo_project or self.project, repo_name, *split_ref(repo.get("ref")))

    def __call__(self, ref: str, from_key: str) -> tuple[str, str] | None:
        name, _, alias = ref.strip().partition("@")
        from_path, _, from_alias = from_key.partition("@")
        effective = alias or from_alias  # a file inside an external repo resolves its relative templates inside that repo
        target = self._target(ref, effective)
        if not target:
            return None
        rooted = name.startswith("/") or bool(alias)
        path = posixpath.normpath(name.lstrip("/") if rooted else posixpath.join(posixpath.dirname(from_path), name))
        if path.startswith(".."):
            self._fail(ref, "its path points outside the repository")
            return None
        key = f"{path}@{effective}" if effective and effective != "self" else path
        if key not in self.cache:
            self.cache[key] = self._read(ref, target, path, key)
        elif self.cache[key] is None:
            self.last = (key, self.errors.get(key, "it could not be read"))
        return (key, self.cache[key]) if self.cache[key] is not None else None

    def _read(self, ref: str, target: tuple[str, str, str | None, str], path: str, key: str) -> str | None:
        project, repo, version, version_type = target
        try:
            return self.client.get_repository_file(project, repo, path, version, version_type)
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                self._fail(ref, f"the token cannot read repository '{project}/{repo}' (it needs the 'Code (Read)' scope and access to that repository)", key)
            elif status == 404:
                self._fail(ref, f"'{path}' was not found in repository '{project}/{repo}' at {version_type} '{version or 'the default branch'}'", key)
            else:
                self._fail(ref, f"Azure DevOps returned HTTP {status or 'an error'} for repository '{project}/{repo}'", key)
        except Exception as exc:  # network trouble: reported as unread, never an error
            self._fail(ref, f"it could not be fetched ({type(exc).__name__})", key)
        return None


def make_template_loader(client: Any, project: str, repo_id: str, branch: str, resources: dict[str, dict[str, Any]]) -> TemplateLoader:
    return TemplateLoader(client, project, repo_id, branch, resources)


def fetch_pipeline_yaml(client: Any, project: str, pipeline_id: int) -> YamlContext:
    """Best-effort: read the pipeline's YAML (and its templates) from Azure Repos. Never raises; `reason` explains any failure."""
    try:
        definition = client.get_build_definition(project, pipeline_id)
        process = definition.get("process") or {}
        if process.get("type") != 2 or not process.get("yamlFilename"):
            return YamlContext(False, "this is a classic (non-YAML) pipeline, so there is no pipeline file to read")
        repo = definition.get("repository") or {}
        if repo.get("type") != "TfsGit":
            return YamlContext(False, f"the pipeline file lives in a '{repo.get('type') or 'unknown'}' repository; only Azure Repos is supported so far")
        branch = str(repo.get("defaultBranch") or "refs/heads/main").removeprefix("refs/heads/")
        path = str(process["yamlFilename"])
        content = client.get_repository_file(project, repo.get("id"), path, branch, "branch")
    except requests.HTTPError as exc:
        return YamlContext(False, _http_reason(exc))
    except Exception as exc:  # network trouble, malformed response: never break the analysis
        logger.warning("Could not read pipeline YAML: %s", type(exc).__name__)
        return YamlContext(False, "the pipeline file could not be read from Azure DevOps")
    loader = make_template_loader(client, project, repo.get("id"), branch, _repository_resources(_safe_load(content)))
    facts = parse_pipeline_yaml(content, path, loader)
    if facts is None:
        return YamlContext(False, f"'{path}' could not be parsed as an Azure Pipelines YAML file", path=path, branch=branch)
    return YamlContext(True, path=path, branch=branch, content=content, facts=facts)


def yaml_for_prompt(ctx: YamlContext) -> dict[str, Any] | None:
    """What the language model gets to see: the whole pipeline file and the templates that were read (size-capped for its context window)."""
    if not ctx.ok or not ctx.facts:
        return None
    main = file_key(ctx.path)
    templates, used, truncated = [], 0, len(ctx.content) > MAIN_PROMPT_CHARS
    for key, text in ctx.facts.files.items():
        if key == main or used >= TEMPLATES_PROMPT_TOTAL:
            continue
        piece = text[:TEMPLATE_PROMPT_CHARS]
        truncated = truncated or len(text) > len(piece)
        templates.append({"file": key, "content": piece})
        used += len(piece)
    return {
        "file": ctx.path, "branch": ctx.branch, "content": ctx.content[:MAIN_PROMPT_CHARS], "truncated": truncated,
        "templates": templates, "templates_not_expanded": ctx.unresolved[:10], "template_errors": dict(list(ctx.facts.template_errors.items())[:10]),
    }


# ---------------------------------------------------------------------------------------------------------------------
# Turning telemetry findings into file-specific advice
# ---------------------------------------------------------------------------------------------------------------------

def _line_of(text: str, display: str) -> int | None:
    found = _find_step_lines(text.splitlines(), display) if display else None
    return found[0] + 1 if found else None


def _stages_using(ctx: YamlContext, step: StepInfo) -> int:
    """How many stages contain this very step (a template included by several stages is the same step in each)."""
    facts = ctx.facts
    return sum(1 for st in facts.stages if any(sp.file == step.file and sp.label == step.label for jb in st.jobs for sp in jb.steps)) if facts else 1


def where_text(ctx: YamlContext, loc: tuple[StageInfo, JobInfo, StepInfo]) -> str:
    """'In `file` (...) -> stage -> job -> step "name" (line N)'. Names that are template expressions are left out, and when several
    stages use the same step it says so instead of naming one stage that may not be the failing one."""
    stage, job, step = loc
    main = file_key(ctx.path)
    file = step.file or main
    path, _, alias = file.partition("@")
    if file == main:
        head = f"`{file}` ({ctx.branch})"
    elif alias:
        head = f"`{path}` (a template from repository `{alias}`, used by `{ctx.path}`)"
    else:
        head = f"`{file}` (a template used by `{ctx.path}`)"
    parts = [head]
    uses = _stages_using(ctx, step)
    if uses > 1:
        parts.append(f"used by {uses} stages")
    else:
        for label, value in (("stage", stage.name or stage.display), ("job", job.name)):
            if value and "${{" not in value:
                parts.append(f"{label} `{value}`")
    text, _path = _file_text(ctx, step)
    line = _line_of(text, step.display)
    label = _EXPRESSION.sub("<…>", step.label)
    parts.append(f'step "{label}"' + (f" (line {line})" if line else ""))
    return "In " + " → ".join(parts)


def _file_text(ctx: YamlContext, step: StepInfo) -> tuple[str, str]:
    """(text, path) of the file the step is defined in."""
    key = step.file or file_key(ctx.path)
    text = ctx.facts.files.get(key) if ctx.facts else None
    return (text if text is not None else ctx.content), key


def _fence(diff: str) -> str:
    return f"```diff\n{diff}\n```"


def yaml_fence(text: str) -> str:
    return f"```yaml\n{text}\n```"


def _not_used(ctx: YamlContext | None) -> str:
    return "" if not ctx or ctx.ok else f" (your pipeline YAML was not used: {ctx.reason})"


def _candidate_list(ctx: YamlContext, steps: list[StepInfo]) -> str:
    parts = []
    for step in steps[:4]:
        text, key = _file_text(ctx, step)
        line = _line_of(text, step.display)
        path, _, alias = key.partition("@")
        parts.append(f"`{path}`" + (f" in repository `{alias}`" if alias else "") + (f" (line {line})" if line else ""))
    return "; ".join(parts) + (f"; and {len(steps) - 4} more" if len(steps) > 4 else "")


def _template_note(ctx: YamlContext | None, task_name: str | None = None) -> str:
    """Why a step could not be placed in the files: its name fits several steps (the run data does not say which one ran), it is in a
    template that could not be read, or it is in none of the files that were read."""
    if not ctx or not ctx.ok:
        return ""
    candidates = step_candidates(ctx.facts, task_name)
    if len(candidates) > 1:
        return (f" This step's name fits {len(candidates)} steps in your files and the run data does not say which one ran: "
                f"{_candidate_list(ctx, candidates)}.")
    if not ctx.unresolved:
        return " The step was not found in the files that could be read."
    names = ", ".join(f"`{t}`" for t in ctx.unresolved[:3]) + (f" and {len(ctx.unresolved) - 3} more" if len(ctx.unresolved) > 3 else "")
    return f" The step was not found in the files that could be read; it may be defined in a template that could not be read ({names}; the analysis message says why)."


def investigate_remediation(task_name: str, error_excerpt: str | None, kind: str, ctx: YamlContext | None = None) -> str:
    """Advice for a failure that is not clearly transient: the cause when the error names it, otherwise how to find it. Always ends with a
    YAML block to paste (an example to adapt: the values it needs are not in the error text)."""
    cause = identify_cause(error_excerpt)
    loc = locate_step(ctx.facts, None, task_name) if ctx and ctx.ok else None
    where = f"{where_text(ctx, loc)}: " if loc and ctx else ""
    note = "" if loc else _template_note(ctx, task_name)  # only when the step really could not be placed
    line = best_error_line(error_excerpt)
    if cause:
        return f"{where}{cause.remediation}{note}\n\n{yaml_fence(cause.yaml_fix)}"
    if kind == "persistent":
        lead = (f"The error looks like a real fault, not an intermittent one (`{line}`). Retrying would only repeat it and make the run slower; "
                "fix the cause in the step's script or configuration.")
    else:
        seen = f"The log excerpt shows `{line}`" if line else "The log excerpt only shows a generic exit code"
        lead = f"{seen}, which does not say whether this failure is intermittent or a real fault."
    return (f"{where}{lead} Run the pipeline again with verbose logging (the YAML below), open the step log (Trace) and find the first error line; "
            f"add `retryCountOnTaskFailure` only if the cause turns out to be transient (a timeout, a dropped connection, throttling).{note}"
            f"\n\n{yaml_fence(DEBUG_EXAMPLE)}")


def retry_remediation(task_name: str, ctx: YamlContext | None, error_excerpt: str | None = None, intermittent: bool = False) -> str:
    """Remediation text for a flaky step. A retry is only advised when the failure looks transient (or the step is already
    seen succeeding on retry); otherwise the advice is to find the cause. Never invents the step's contents."""
    kind = classify_failure(error_excerpt)
    if kind != "transient" and not intermittent:
        return investigate_remediation(task_name, error_excerpt, kind, ctx)
    loc = locate_step(ctx.facts, None, task_name) if ctx and ctx.ok else None
    if loc and ctx and loc[2].retry:
        return (f"{where_text(ctx, loc)}: the step already retries {loc[2].retry} time(s) (`retryCountOnTaskFailure`) and still fails, "
                "so more retries will not fix it. Fix the cause shown in the error log.\n\n" + yaml_fence(DEBUG_EXAMPLE))
    if loc and ctx:
        text, path = _file_text(ctx, loc[2])
        diff = diff_add_retry(text, loc[2].display, path)
        if diff:
            return f"{where_text(ctx, loc)}, retry the step when it fails (the error looks transient):\n\n{_fence(diff)}"
    return (f"Add `retryCountOnTaskFailure: 2` to the step named '{task_name}' in your pipeline YAML{_not_used(ctx)}.{'' if loc else _template_note(ctx, task_name)}\n\n"
            + yaml_fence(RETRY_EXAMPLE.format(task=task_name)))


def cache_remediation(task_name: str, ecosystem: str | None, ctx: YamlContext | None) -> str | None:
    """Remediation text for slow dependency steps, or None when the job already caches (nothing to recommend)."""
    loc = locate_step(ctx.facts, None, task_name) if ctx and ctx.ok else None
    eco = (loc[2].ecosystem if loc else None) or ecosystem
    if loc and loc[1].has_cache:
        return None
    if eco not in CACHE_RECIPES:
        return (f"Cache what '{task_name}' downloads between runs with the `Cache@2` task, keyed on your dependency lock file{_not_used(ctx)}. "
                f"Which folder to cache depends on the tool, so replace the placeholders in the example.{'' if loc else _template_note(ctx, task_name)}\n\n"
                + yaml_fence(CATEGORY_EXAMPLES["caching_opportunity"]))
    recipe = CACHE_RECIPES[eco]
    note = f"{recipe['hint']} The key assumes your lock file is `{recipe['key_file']}`; change it if yours differs."
    if loc and ctx:
        text, path = _file_text(ctx, loc[2])
        diff = diff_add_cache(text, loc[2].display, eco, path)
        if diff:
            return f"{where_text(ctx, loc)}, add a cache step before it (the job has none):\n\n{_fence(diff)}\n\n{note}"
    example = "\n".join(["# example, not from your file", *cache_step_lines(eco, 0)])
    return f"Add a cache step before '{task_name}'{_not_used(ctx)}.{'' if loc else _template_note(ctx, task_name)} Example to adapt:\n\n{yaml_fence(example)}\n\n{note}"


_SECTION = re.compile(r"(\*\*(?:Diagnosis|Remediation|Impact)\*\*:)")


def get_section(text: str, name: str) -> str:
    """The body of one **Diagnosis**/**Remediation**/**Impact** section of a recommendation ('' when it has none)."""
    parts = _SECTION.split(text)
    for i in range(1, len(parts), 2):
        if parts[i].strip("*:").lower() == name:
            return parts[i + 1].strip()
    return ""


def replace_sections(text: str, **sections: str) -> str:
    """Rewrite the named sections of a recommendation, keeping the others; a section that is missing is appended."""
    parts = _SECTION.split(text)
    if len(parts) == 1:  # unstructured text cannot be corrected in part, so none of it is kept
        parts = [""]
    seen: set[str] = set()
    for i in range(1, len(parts), 2):
        name = parts[i].strip("*:").lower()
        seen.add(name)
        if name in sections:
            parts[i + 1] = f" {sections[name]}\n"
    rebuilt = "".join(parts).rstrip("\n")
    for name, body in sections.items():
        if name not in seen:
            rebuilt += f"\n**{name.capitalize()}**: {body}"
    return rebuilt


def is_pasteable_yaml(block: str) -> bool:
    """True for YAML a customer can put in a pipeline file: a mapping, or a list of mappings (steps, jobs, stages). Comment-only text,
    a bare line of prose, a shell command and a bullet list of sentences all parse as 'nothing' or as plain strings, and are not a fix."""
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return False
    if isinstance(data, list):
        return any(isinstance(item, dict) and item for item in data)
    return isinstance(data, dict) and bool(data)


_OTHER_FENCE = re.compile(r"```(?!ya?ml\b|diff\b|patch\b)[A-Za-z0-9_+\-]+[ \t]*\r?\n(.*?)\r?\n```", re.IGNORECASE | re.DOTALL)
_YAML_OR_DIFF_FENCE = re.compile(r"```(?:ya?ml|diff|patch)[ \t]*\r?\n", re.IGNORECASE)


def clean_snippets(text: str) -> str:
    """Leave only blocks that can be pasted: a ```yaml block that is not real pipeline YAML is removed, and a fenced block in another
    language (a shell command) becomes plain indented text so it cannot be mistaken for the YAML fix."""
    text = _OTHER_FENCE.sub(lambda m: "\n".join("    " + line for line in m.group(1).splitlines()), text)
    return _YAML_FENCE.sub(lambda m: m.group(0) if is_pasteable_yaml(m.group(0).split("\n", 1)[1].rsplit("\n```", 1)[0]) else "", text)


_UNSUPPORTED = re.compile(
    r"(?:\b(?:since|because|as)\s+(?:the\s+)?(?:failure|error|issue)\s+is\s+(?:deterministic|transient|intermittent)[^.]*\.|"
    r"[^.\n]*\bis\s+(?:a\s+)?(?:deterministic|transient)\b[^.\n]*\.|[^.\n]*\b(?:deterministic|transient)\s+(?:failure|error|issue)s?\b[^.\n]*\.)\s*",
    re.IGNORECASE)


def strip_unsupported_claims(text: str) -> str:
    """Remove sentences that call a failure deterministic or transient. Used only when the error text does not show either."""
    return _UNSUPPORTED.sub("", text)


def ensure_fix_block(recommendation: str, block: str) -> str:
    """Make sure the recommendation carries a code block to paste: `block` is added to the remediation when it has none."""
    if _YAML_OR_DIFF_FENCE.search(recommendation):
        return recommendation
    marker = "**Impact**:"
    if marker in recommendation:
        head, _, tail = recommendation.partition(marker)
        return f"{head.rstrip()}\n\n{block}\n{marker}{tail}"
    return f"{recommendation.rstrip()}\n\n{block}"


def task_evidence(summary: dict[str, Any]) -> dict[str, tuple[str, float]]:
    """task name (lower) -> (error excerpt, retry rate %) from the measured telemetry summary."""
    found: dict[str, tuple[str, float]] = {}
    for stage in summary.get("stages") or []:
        for task in stage.get("tasks") or []:
            found[_norm(task.get("name"))] = (str(task.get("error_excerpt") or ""), float(task.get("retry_rate_pct", 0) or 0))
    return found


def enforce_retry_policy(findings: list[dict[str, Any]], summary: dict[str, Any], ctx: YamlContext | None = None) -> list[dict[str, Any]]:
    """Retry advice is only kept when the measured failure looks transient; otherwise it is replaced with 'find the cause'.

    The language model is told this too, but the rule is enforced here so a confident-sounding "mitigate transient
    errors" can never be shown for a failure the log does not show to be intermittent."""
    evidence = task_evidence(summary)
    checked: list[dict[str, Any]] = []
    for finding in findings:
        text = str(finding.get("recommendation") or "")
        excerpt, retry_pct = evidence.get(_norm(finding.get("task_name")), ("", 0.0))
        kind = classify_failure(excerpt)
        if finding.get("category") == "flaky_step" and "retryCountOnTaskFailure" in text and kind != "transient" and retry_pct <= 0:
            fixed = investigate_remediation(str(finding.get("task_name") or ""), excerpt, kind, ctx)
            finding = {**finding, "recommendation": replace_sections(text, remediation=fixed)}
        checked.append(finding)
    return checked


def apply_yaml_context(findings: list[dict[str, Any]], ctx: YamlContext | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Check model-written findings against the real files: drop advice that is already applied, say where it applies, and never
    leave a snippet for a failing step the model could not have seen (its structure would be a guess). A block derived from the
    error text replaces such a snippet later (finding_quality.ensure_fix_block), so the finding still carries something to paste."""
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []
    for finding in findings:
        loc = locate_step(ctx.facts, finding.get("stage_name"), finding.get("task_name")) if ctx and ctx.ok else None
        text = str(finding.get("recommendation") or "")
        if not loc:
            if finding.get("category") == "flaky_step":
                revised = _YAML_FENCE.sub("", text).rstrip()
                note = _template_note(ctx, finding.get("task_name"))  # says why the step could not be placed in the files
                if note and note.strip() not in revised:
                    body = get_section(revised, "remediation")
                    revised = replace_sections(revised, remediation=f"{body}{note}") if body else f"{revised}{note}"
                if revised != text:
                    finding = {**finding, "recommendation": revised}
            kept.append(finding)
            continue
        if finding.get("category") == "caching_opportunity" and loc[1].has_cache:
            skipped.append(f"caching for '{finding.get('task_name')}': job '{loc[1].name}' already has a Cache@2 step")
            continue
        where = where_text(ctx, loc) + ":"
        text = text.replace("**Remediation**:", f"**Remediation**: {where}", 1) if "**Remediation**:" in text else f"{where} {text}"
        if finding.get("category") == "flaky_step" and loc[2].retry:
            text += f"\n\nNote: this step already has `retryCountOnTaskFailure: {loc[2].retry}`; retries are not the fix here."
        kept.append({**finding, "recommendation": text})
    return kept, skipped

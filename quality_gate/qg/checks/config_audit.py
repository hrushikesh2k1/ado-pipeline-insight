from __future__ import annotations

import re

from qg.model import CheckResult, Finding, FAIL, PASS, WARN
from qg.util import REPO_ROOT, tracked_files

ID, NAME, CATEGORY = "config", "Repository, container and pipeline hygiene", "Security"
WHAT = ("Checks the files around the code: Dockerfile (runs as non-root?), CI/CD workflows (least-privilege tokens, pinned actions), "
        "dependency pinning, and whether virtualenvs, publish profiles, .env files or zip artifacts are committed to git.")

TRACKED_BAD = [
    (re.compile(r"^(venv|\.venv[^/]*|env)/"), "medium", "Virtual environment is committed to git",
     "git rm -r --cached venv && add 'venv/' to .gitignore (it bloats the repo and ships third-party binaries)."),
    (re.compile(r"(^|/)node_modules/"), "medium", "node_modules is committed to git", "git rm -r --cached and ignore it."),
    (re.compile(r"(^|/)\.env($|\.(?!example))"), "high", "A real .env file is committed", "Remove from git history and rotate its secrets."),
    (re.compile(r"(^|/)local\.settings\.json$"), "high", "local.settings.json is committed", "Remove and rotate; only commit *.example.json."),
    (re.compile(r"\.(pubxml|publishsettings)$|(^|/)publish\.xml$"), "high", "Publish profile is committed", "Publish profiles contain deployment credentials; remove and reset them in Azure."),
    (re.compile(r"\.(zip|tgz|tar\.gz)$"), "low", "Build artifact (archive) is committed", "Build artifacts belong in CI storage, not git."),
    (re.compile(r"\.(pem|pfx|key|p12)$"), "high", "Key/certificate file is committed", "Remove and rotate."),
    (re.compile(r"(^|/)startup\.log$|\.log$"), "low", "Log file is committed", "Logs can contain tokens and PII; remove."),
]


def _add(res: CheckResult, sev: str, title: str, loc: str, fix: str, rule: str, detail: str = "") -> None:
    res.findings.append(Finding(sev, title, loc, detail, rule, fix))


def _tracked(res: CheckResult) -> None:
    grouped: dict[str, list[str]] = {}
    meta: dict[str, tuple] = {}
    for f in tracked_files():
        if not (REPO_ROOT / f).exists():
            continue
        for rx, sev, title, fix in TRACKED_BAD:
            if rx.search(f):
                grouped.setdefault(title, []).append(f)
                meta[title] = (sev, fix)
                break
    for title, files in grouped.items():
        sev, fix = meta[title]
        sample = ", ".join(files[:3]) + (f" (+{len(files) - 3} more)" if len(files) > 3 else "")
        _add(res, sev, f"{title} ({len(files)} file{'s' if len(files) != 1 else ''})", sample, fix, "GIT-HYGIENE")
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore") if (REPO_ROOT / ".gitignore").exists() else ""
    checks = [(r"(?m)^/?\.env\b", ".env", ".env files"),
              (r"(?m)^/?local\.settings\.json", "local.settings.json", "local.settings.json"),
              (r"(?m)^/?(\*\*/)?venv/?\s*$", "venv/", "virtualenvs (venv/)")]
    for pattern, needle, label in checks:
        if not re.search(pattern, ignore):
            _add(res, "medium", f".gitignore does not exclude {label}", ".gitignore", f"Add '{needle}' to .gitignore.", "GITIGNORE")


def _dockerfile(res: CheckResult) -> None:
    path = REPO_ROOT / "Dockerfile"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    user = re.findall(r"(?im)^\s*USER\s+(\S+)", text)
    if not user or user[-1].lower() in ("root", "0"):
        _add(res, "medium", "Container runs as root", "Dockerfile", "Add a non-root user: RUN useradd -r app && USER app.", "DOCKER-ROOT")
    for image in re.findall(r"(?im)^\s*FROM\s+(\S+)", text):
        if image.endswith(":latest") or ":" not in image and "@" not in image:
            _add(res, "medium", f"Base image '{image}' is not pinned to a version", "Dockerfile", "Pin a specific tag or digest.", "DOCKER-PIN")
    if not re.search(r"(?im)^\s*HEALTHCHECK", text):
        _add(res, "low", "Dockerfile has no HEALTHCHECK", "Dockerfile", "Add HEALTHCHECK hitting /api/v1/health.", "DOCKER-HEALTH")
    if re.search(r"(?im)^\s*(ENV|ARG)\s+\S*(PASSWORD|SECRET|TOKEN|KEY|PAT)\S*\s*=?\s*\S+", text):
        _add(res, "high", "Secret-looking ENV/ARG baked into image", "Dockerfile", "Inject secrets at runtime, never at build time.", "DOCKER-SECRET")


def _workflows(res: CheckResult) -> None:
    files = list((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")) + list(REPO_ROOT.glob("azure-pipelines*.yml"))
    for p in files:
        rel_p = p.relative_to(REPO_ROOT).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "github/workflows" in rel_p:
            if "pull_request_target" in text:
                _add(res, "high", "Workflow uses pull_request_target (runs untrusted code with secrets)", rel_p, "Use pull_request.", "GHA-PRT")
            if not re.search(r"(?m)^permissions:", text) and "permissions:" not in text:
                _add(res, "medium", "Workflow does not restrict GITHUB_TOKEN permissions", rel_p, "Add top-level 'permissions: contents: read'.", "GHA-PERMS")
            unpinned = sorted({m for m in re.findall(r"uses:\s*([\w./-]+@[^\s#]+)", text) if not re.search(r"@[0-9a-f]{40}$", m)})
            if unpinned:
                _add(res, "low", f"{len(unpinned)} action(s) pinned by tag, not commit SHA", rel_p,
                     "Pin third-party actions to a full commit SHA to prevent tag hijacking.", "GHA-PIN", ", ".join(unpinned[:4]))
            if re.search(r"\$\{\{\s*github\.event\.(issue|pull_request|comment|head_commit)[^}]*\}\}", text) and re.search(r"run:", text):
                _add(res, "high", "Untrusted event data used inside a run: step (script injection)", rel_p, "Pass via env: and quote.", "GHA-INJECT")
            if re.search(r"zip release\.zip \./\* -r(?! -x)", text):
                _add(res, "low", "Workflow zips the whole workspace (may include .git, venv, secrets)", rel_p, "Zip only the deployable files.", "GHA-ARTIFACT")
            if not re.search(r"pytest|quality_gate|npm (run )?test|Optional: Add step to run tests", text.replace("Optional: Add step to run tests here", "")):
                _add(res, "medium", "Deployment workflow runs no tests or security gate before deploying", rel_p,
                     "Add a step: python quality_gate/run_all.py --ci  (fails the build when the gate fails).", "CI-NOGATE")
        else:
            if "npm install" in text:
                _add(res, "low", "Pipeline uses 'npm install' (non-reproducible)", rel_p, "Use 'npm ci'.", "PIPE-NPM")
            if "quality_gate" not in text and "bandit" not in text:
                _add(res, "medium", "Azure pipeline has no security gate stage", rel_p, "Add: python quality_gate/run_all.py --ci", "CI-NOGATE")


def _requirements(cfg: dict, res: CheckResult) -> None:
    versions: dict[str, dict[str, str]] = {}
    for req in cfg["scope"]["requirements"]:
        p = REPO_ROOT / req
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith(("-", "http")):
                continue
            m = re.match(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(==|>=|<=|~=|>|<|!=)?\s*([\w.\-]+)?", line)
            if not m:
                continue
            name, op, ver = m.group(1).lower(), m.group(3), m.group(4)
            if op != "==":
                _add(res, "medium", f"Dependency '{name}' is not pinned with ==", req, "Pin exact versions so builds are reproducible and auditable.", "DEP-PIN")
            versions.setdefault(name, {})[req] = ver or "?"
    for name, per in versions.items():
        if len(set(per.values())) > 1:
            _add(res, "low", f"'{name}' has different versions across requirement files", ", ".join(f"{k}={v}" for k, v in per.items()),
                 "Keep the web app and function on the same version.", "DEP-DRIFT")


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    _tracked(res)
    _dockerfile(res)
    _workflows(res)
    _requirements(cfg, res)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    res.findings.sort(key=lambda f: order[f.severity])
    counts = res.counts
    res.metrics = {"high": counts["high"], "medium": counts["medium"], "low": counts["low"]}
    if counts["critical"] or counts["high"]:
        res.status, res.summary = FAIL, f"{counts['high'] + counts['critical']} high-risk hygiene issue(s), {counts['medium']} medium, {counts['low']} low"
    elif counts["medium"]:
        res.status, res.summary = FAIL, f"{counts['medium']} medium hygiene issue(s), {counts['low']} low"
    elif counts["low"]:
        res.status, res.summary = WARN, f"{counts['low']} low-severity hygiene issue(s)"
    else:
        res.status, res.summary = PASS, "no hygiene issues"
    return res

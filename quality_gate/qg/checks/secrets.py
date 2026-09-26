from __future__ import annotations

import re

from qg.model import CheckResult, Finding, FAIL, PASS
from qg.util import REPO_ROOT, git, tracked_files

ID, NAME, CATEGORY = "secrets", "Hard-coded secrets scan", "Security"
WHAT = ("Looks for passwords, API keys, connection strings, tokens and private keys committed to the repository. "
        "Scans every git-tracked file plus untracked, non-ignored files, so a leaked key cannot hide in a config or script.")

SKIP_PATHS = re.compile(
    r"(^|/)(venv|\.venv[^/]*|node_modules|dist|__pycache__|\.pytest_cache|playwright-report|test-results|reports|logs-extracted|quality_gate)/"
    r"|package-lock\.json$|\.(zip|png|jpg|ico|pyc|woff2?|map)$")

FIX = "Remove it, rotate the credential, and load it from Key Vault or an environment variable."
PATTERNS = [
    ("Connection string with inline password",
     re.compile(r"(?i)(?:server|data source|host|uid|user id)\s*=[^\n]{0,300}?\b(?:password|pwd)\s*=\s*(?![\s;'\"%{$<?*])(?!(?:your|xxx|changeme|example|placeholder|redacted|none|null)\b)[^;\s'\"]{6,}")),
    (".env-style secret assignment",
     re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|SECRET|API_KEY|_KEY|_TOKEN|_PAT)[ \t]*=[ \t]*(?!@Microsoft\.KeyVault)[^\s#<$%{'\"]{8,}")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Azure storage account key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}")),
    ("Azure DevOps PAT-like token (52 base32 chars)", re.compile(r"(?<![A-Za-z0-9])[a-z2-7]{52}(?![A-Za-z0-9])")),
    ("Function/host key in a URL (code=...)", re.compile(r"[?&]code=[A-Za-z0-9_\-]{30,}={0,2}")),
    ("JWT / bearer token", re.compile(r"eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}")),
    ("OpenAI-style API key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}")),
    ("API key / secret assigned to a string literal",
     re.compile(r"(?i)(?:api[_-]?key|secret|token|password)['\"]?\s*[:=]\s*['\"](?!@Microsoft\.KeyVault)[A-Za-z0-9/+_\-=.]{24,}['\"]")),
]


def _candidate_files() -> list[str]:
    files = set(tracked_files())
    others = git("ls-files", "--others", "--exclude-standard")
    files.update(others.splitlines() if others else [])
    return sorted(f for f in files if not SKIP_PATHS.search(f) and (REPO_ROOT / f).is_file())


def run_check(cfg: dict) -> CheckResult:
    res = CheckResult(ID, NAME, CATEGORY, WHAT)
    files = _candidate_files()
    for f in files:
        try:
            text = (REPO_ROOT / f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 2_000_000:
            continue
        lines = text.splitlines()
        for label, rx in PATTERNS:
            for m in rx.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                line_text = lines[line_no - 1] if line_no - 1 < len(lines) else ""
                if "REDACTED" in line_text or "nosec-secret" in line_text:
                    continue
                res.findings.append(Finding("high", label, f"{f}:{line_no}",
                                            f"value hidden (starts with: {m.group(0)[:4]}...)", "regex", FIX))
    res.metrics = {"files scanned": len(files), "secrets found": len(res.findings)}
    res.status = FAIL if res.findings else PASS
    res.summary = (f"{len(res.findings)} potential secret(s) in {len(files)} files" if res.findings
                   else f"no secrets found in {len(files)} files")
    return res

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_DIR = REPO_ROOT / "quality_gate"
REPORTS_DIR = GATE_DIR / "reports"
WORK_DIR = REPORTS_DIR / "raw"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1"}
    if env:
        full_env.update(env)
    try:
        return subprocess.run(
            cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=full_env, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, exc.stdout or "", f"timeout after {timeout}s")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def py(*args: str, **kw) -> subprocess.CompletedProcess:
    return run([sys.executable, *args], **kw)


def module_available(module: str) -> bool:
    return py("-c", f"import {module}").returncode == 0


def tool_version(module: str) -> str:
    r = py("-m", module, "--version")
    return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 and (r.stdout or r.stderr).strip() else "unavailable"


def parse_json(text: str, default=None):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def git(*args: str) -> str:
    r = run(["git", *args])
    return r.stdout.strip() if r.returncode == 0 else ""


def tracked_files() -> list[str]:
    out = git("ls-files")
    return out.splitlines() if out else []


def rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def existing(paths: list[str]) -> list[str]:
    return [p for p in paths if (REPO_ROOT / p).exists()]

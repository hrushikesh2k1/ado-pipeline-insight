"""Release version metadata.

The version number lives in exactly one place: the VERSION file at the repository root (edit it with
scripts/bump_version.py). Packaging (scripts/package_webapp.py) stamps build details (commit, branch, time) into
app/version.json, which is a build artifact and is not committed. When that file is missing (local runs) the
VERSION file is used directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent
SERVICE_NAME = "ADO Pipeline Insight"


def _read_version_file() -> str:
    for path in (REPO_ROOT / "VERSION", APP_DIR / "VERSION"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return "0.0.0"


def get_version_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "version": _read_version_file(),
        "git_commit": "unknown",
        "git_branch": "unknown",
        "build_timestamp": None,
        "service": SERVICE_NAME,
        "environment": "production",
    }
    build_file = APP_DIR / "version.json"
    if build_file.is_file():
        try:
            stamped = json.loads(build_file.read_text(encoding="utf-8"))
            if isinstance(stamped, dict):
                # The VERSION file stays authoritative for the number; the stamp supplies the build details.
                info.update({k: v for k, v in stamped.items() if k != "version"})
        except (OSError, ValueError):
            pass
    return info

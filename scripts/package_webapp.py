"""Build webapp-deploy.zip for `az webapp deploy`, stamping the release version and build details.

    cd frontend && npm run build && cd ..
    python scripts/package_webapp.py
    az webapp deploy -g <resource-group> -n <app-name> --src-path webapp-deploy.zip --type zip

The version comes from the VERSION file (change it with scripts/bump_version.py). The commit, branch and time are
written to app/version.json, which is a build artifact (git-ignored) and shipped inside the zip.
"""
from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "webapp-deploy.zip"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def add_tree(zf: zipfile.ZipFile, folder: Path, prefix: str) -> int:
    count = 0
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not SKIP_DIRS.intersection(path.parts) and path.suffix not in {".pyc", ".pyo"}:
            zf.write(path, f"{prefix}/{path.relative_to(folder).as_posix()}")
            count += 1
    return count


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    stamp = {
        "version": version,
        "git_commit": git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else ""),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "build_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service": "ADO Pipeline Insight",
        "environment": "production",
    }
    (ROOT / "app" / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")

    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("frontend/dist is missing: run `npm run build` in frontend/ first")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ROOT / "requirements.txt", "requirements.txt")
        zf.write(ROOT / "VERSION", "VERSION")
        files = add_tree(zf, ROOT / "app", "app") + add_tree(zf, ROOT / "core", "core") + add_tree(zf, dist, "frontend/dist")
    print(f"Packaged v{version} ({stamp['git_commit']} on {stamp['git_branch']}): {files + 2} files, {ZIP_PATH.stat().st_size // 1024} KB -> {ZIP_PATH.name}")
    if dirty:
        print("Warning: uncommitted changes are included in this build; commit first so the stamped commit matches.")


if __name__ == "__main__":
    main()

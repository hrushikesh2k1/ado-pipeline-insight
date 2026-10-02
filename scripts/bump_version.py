"""Change the release version in the one place it lives (the VERSION file) and keep frontend/package.json in step.

    python scripts/bump_version.py patch      # 1.4.0 -> 1.4.1  (bug fixes only)
    python scripts/bump_version.py minor      # 1.4.0 -> 1.5.0  (new features, backwards compatible)
    python scripts/bump_version.py major      # 1.4.0 -> 2.0.0  (breaking changes)
    python scripts/bump_version.py 1.6.2      # set an exact version

Then add a CHANGELOG.md entry, commit, and package with scripts/package_webapp.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> tuple[int, int, int]:
    match = SEMVER.match(VERSION_FILE.read_text(encoding="utf-8").strip())
    if not match:
        raise SystemExit(f"{VERSION_FILE} does not contain a MAJOR.MINOR.PATCH version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def next_version(current: tuple[int, int, int], change: str) -> str:
    major, minor, patch = current
    if change == "major":
        return f"{major + 1}.0.0"
    if change == "minor":
        return f"{major}.{minor + 1}.0"
    if change == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if SEMVER.match(change):
        return change
    raise SystemExit("usage: bump_version.py major|minor|patch|MAJOR.MINOR.PATCH")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    old = ".".join(map(str, read_version()))
    new = next_version(read_version(), argv[1])
    VERSION_FILE.write_text(new + "\n", encoding="utf-8")

    package_json = ROOT / "frontend" / "package.json"
    if package_json.exists():
        text = package_json.read_text(encoding="utf-8")
        text = re.sub(r'("version"\s*:\s*")[^"]+(")', rf"\g<1>{new}\g<2>", text, count=1)
        package_json.write_text(text, encoding="utf-8")

    print(f"Version {old} -> {new}")
    print("Next: add a CHANGELOG.md entry, commit, then run scripts/package_webapp.py and deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

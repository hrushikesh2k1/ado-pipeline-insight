"""Release versioning: one VERSION file is the source of truth; build details are stamped separately."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.core import version as version_module

ROOT = Path(__file__).resolve().parents[1]


def _load_bump():
    spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_file_is_valid_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", (ROOT / "VERSION").read_text(encoding="utf-8").strip())


def test_reported_version_comes_from_the_version_file_not_the_stamp(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (tmp_path / "VERSION").write_text("2.5.1\n", encoding="utf-8")
    (app_dir / "version.json").write_text(json.dumps({"version": "9.9.9", "git_commit": "abc1234", "git_branch": "master",
                                                      "build_timestamp": "2026-10-03T00:00:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(version_module, "APP_DIR", app_dir)
    monkeypatch.setattr(version_module, "REPO_ROOT", tmp_path)
    info = version_module.get_version_info()
    assert info["version"] == "2.5.1"  # a stale stamp can never change the number
    assert info["git_commit"] == "abc1234" and info["service"] == "ADO Pipeline Insight"


def test_missing_or_corrupt_stamp_falls_back_gracefully(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (tmp_path / "VERSION").write_text("1.0.0", encoding="utf-8")
    (app_dir / "version.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(version_module, "APP_DIR", app_dir)
    monkeypatch.setattr(version_module, "REPO_ROOT", tmp_path)
    assert version_module.get_version_info()["version"] == "1.0.0"
    (tmp_path / "VERSION").unlink()
    assert version_module.get_version_info()["version"] == "0.0.0"


@pytest.mark.parametrize("change,expected", [("patch", "1.4.1"), ("minor", "1.5.0"), ("major", "2.0.0"), ("3.1.4", "3.1.4")])
def test_bump_rules(change, expected):
    assert _load_bump().next_version((1, 4, 0), change) == expected


def test_bump_rejects_garbage():
    with pytest.raises(SystemExit):
        _load_bump().next_version((1, 4, 0), "banana")


def test_no_hardcoded_release_number_in_the_ui_or_api():
    ui = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert not re.search(r">v\d+\.\d+\.\d+<", ui), "the header version must come from /api/v1/version"
    assert '"version": "1.' not in (ROOT / "app" / "api" / "routes.py").read_text(encoding="utf-8")

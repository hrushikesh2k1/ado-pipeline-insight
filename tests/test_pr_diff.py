"""The diff the reviewer is shown, the lines a comment may point at, and which files are read at all."""
from __future__ import annotations

import pytest

from app.services.pr_diff import build_view, classify, is_changelog_path, is_test_path, priority, suggestable


class TestClassify:
    @pytest.mark.parametrize("path,language", [
        ("src/a.py", "Python"), ("tools/Deploy.ps1", "PowerShell"), ("Mod/Mod.psm1", "PowerShell"), ("Mod/Mod.psd1", "PowerShell"),
        ("run.sh", "Shell"), ("db/x.sql", "SQL"), ("p.yml", "YAML"), ("main.bicep", "Bicep"), ("app/x.TSX", "TypeScript (React)"),
    ])
    def test_languages_that_are_read(self, path, language):
        assert classify(path, "edit") == (language, None)

    @pytest.mark.parametrize("path,reason", [
        ("README.md", "documentation"), ("notes.txt", "documentation"), ("data/x.json", "data or binary file"), ("logo.png", "data or binary file"),
        ("package-lock.json", "lock file, generated or minified"), ("poetry.lock", "lock file, generated or minified"),
        ("dist/app.min.js", "lock file, generated or minified"), ("api/x_pb2.py", "lock file, generated or minified"), ("Makefile", "not a language this review covers"),
    ])
    def test_files_that_are_not(self, path, reason):
        assert classify(path, "edit") == (None, reason)

    def test_deleted_files_are_not_read_whatever_their_type(self):
        assert classify("src/a.py", "delete") == (None, "deleted file")
        assert classify("src/a.py", "edit, Delete") == (None, "deleted file")


class TestPaths:
    @pytest.mark.parametrize("path", ["tests/helper.py", "a/b/test_x.py", "a/x_test.py", "Mod/Mod.Tests.ps1", "web/app.test.ts", "web/app.spec.jsx", "__tests__/a.js", "Api.Tests.cs"])
    def test_test_files(self, path):
        assert is_test_path(path)

    @pytest.mark.parametrize("path", ["scripts/latest.py", "docs/contest.md", "src/specification.md", "main.py", "testing_notes.md", "src/attest.py"])
    def test_names_that_only_contain_the_word(self, path):
        assert not is_test_path(path)

    @pytest.mark.parametrize("path", ["CHANGELOG.md", "docs/changelog.md", "RELEASE_NOTES.md", "release-notes.txt", "Change-Log"])
    def test_changelog_files(self, path):
        assert is_changelog_path(path)

    def test_a_file_that_only_mentions_a_changelog_is_not_one(self):
        assert not is_changelog_path("tools/changelog_helper.py")

    def test_python_and_powershell_come_first_and_tests_after_the_code(self):
        order = sorted([("YAML", "ci.yml"), ("Python", "tests/test_a.py"), ("PowerShell", "a.ps1"), ("Python", "app/b.py")], key=lambda p: priority(*p))
        assert [p[1] for p in order] == ["a.ps1", "app/b.py", "tests/test_a.py", "ci.yml"]


OLD = "alpha\nbeta\ngamma\ndelta\n"


class TestBuildView:
    def test_added_changed_and_removed_lines(self):
        view = build_view("a.py", "Python", "edit", OLD, "alpha\nBETA\ngamma\nepsilon\nzeta\n")
        assert view.added == {2, 4, 5}
        assert view.removed_count == 2 and view.added_count == 3
        assert view.has_changes

    def test_every_line_is_shown_with_its_number_in_the_new_file_and_a_mark(self):
        view = build_view("a.py", "Python", "edit", OLD, "alpha\nBETA\ngamma\ndelta\n")
        lines = view.shown.splitlines()
        assert lines[0] == "      1 | alpha"
        assert "-       | beta" in lines
        assert "+     2 | BETA" in lines
        assert view.whole_file

    def test_a_new_file_is_all_added(self):
        view = build_view("a.py", "Python", "add", "", "one\ntwo\n")
        assert view.added == {1, 2} and view.removed_count == 0
        assert [row.kind for row in view.rows] == ["add", "add"]

    def test_code_that_was_only_removed_is_anchored_to_the_line_that_follows(self):
        view = build_view("a.py", "Python", "edit", OLD, "alpha\ngamma\ndelta\n")
        assert view.added == set()
        assert view.removed_at == {2}
        assert view.has_changes

    def test_removal_at_the_end_is_anchored_to_the_last_line(self):
        view = build_view("a.py", "Python", "edit", OLD, "alpha\nbeta\ngamma\n")
        assert view.removed_at == {3}

    def test_nothing_changed(self):
        assert not build_view("a.py", "Python", "edit", OLD, OLD).has_changes

    def test_a_file_that_is_too_long_to_compare_is_refused(self):
        with pytest.raises(ValueError, match="4000"):
            build_view("a.py", "Python", "edit", "", "x\n" * 4001)

    def test_a_long_line_is_cut(self):
        view = build_view("a.py", "Python", "add", "", "x" * 500 + "\n")
        assert view.shown.endswith("…") and len(view.shown) < 270

    def test_a_large_file_shows_only_the_changes_with_context(self):
        old = "".join(f"line {n}\n" for n in range(1, 501))
        new = old.replace("line 250\n", "CHANGED 250\n").replace("line 450\n", "CHANGED 450\n")
        view = build_view("a.py", "Python", "edit", old, new, whole_file_lines=350, context=2)
        assert not view.whole_file and view.omitted_hunks == 0
        assert "+   250 | CHANGED 250" in view.shown and "+   450 | CHANGED 450" in view.shown
        assert "line 100" not in view.shown
        assert view.shown.count("...") == 3  # before, between and after

    def test_when_the_changes_do_not_fit_the_last_parts_are_left_out_and_counted(self):
        old = "".join(f"line {n}\n" for n in range(1, 601))
        new = old
        for n in (100, 300, 500):
            new = new.replace(f"line {n}\n", f"CHANGED {n}\n")
        view = build_view("a.py", "Python", "edit", old, new, whole_file_lines=350, context=2, max_rows=8)
        assert view.omitted_hunks == 2
        assert "CHANGED 100" in view.shown and "CHANGED 300" not in view.shown and "CHANGED 500" not in view.shown

    def test_a_small_file_is_shown_whole_even_when_only_one_line_changed(self):
        old = "".join(f"line {n}\n" for n in range(1, 101))
        view = build_view("a.py", "Python", "edit", old, old.replace("line 50\n", "CHANGED\n"))
        assert view.whole_file and "      1 | line 1" in view.shown and "     99 | line 99" in view.shown
        assert "+    50 | CHANGED" in view.shown


class TestSuggestable:
    def test_only_lines_the_pull_request_changed(self):
        view = build_view("a.py", "Python", "edit", OLD, "alpha\nBETA\ngamma\nepsilon\nzeta\n")
        assert suggestable(view, 4, 5)
        assert suggestable(view, 2, 2)
        assert not suggestable(view, 2, 3)  # line 3 was not changed
        assert not suggestable(view, 1, 1)

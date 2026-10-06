"""The checklist in a pull request description, checked against what the pull request contains."""
from __future__ import annotations

from app.services.pr_checklist import evaluate_checklist, linked_build_ids, parse_checklist

DESCRIPTION = """Some text.

Unit Tests Created and Tested
- [x] Unit tests have been created
- [ ] Unit tests have been run and passed
* [X] Changelog updated
  - [ ] indented box
Not a box: [x] nothing
- [x]no space after the box
"""


def item(text, checked=True):
    return [{"text": text, "checked": checked}]


def evaluate(text, checked=True, **evidence):
    base = {"changed_paths": [], "work_items": [], "build_check": None}
    base.update(evidence)
    return evaluate_checklist(item(text, checked), base)[0]


class TestParse:
    def test_ticked_and_unticked_boxes_in_either_list_style(self):
        assert parse_checklist(DESCRIPTION) == [
            {"text": "Unit tests have been created", "checked": True},
            {"text": "Unit tests have been run and passed", "checked": False},
            {"text": "Changelog updated", "checked": True},
            {"text": "indented box", "checked": False},
        ]

    def test_no_description(self):
        assert parse_checklist("") == [] and parse_checklist(None) == []

    def test_a_link_in_an_item_is_shown_as_its_words(self):
        text = "- [ ] [Alert Inventory wiki] (https://example.com/wiki/page) is updated with Alert details.\n- [x] See [the guide](https://example.com/g) and [other](https://example.com/o)\n"
        assert [i["text"] for i in parse_checklist(text)] == ["Alert Inventory wiki is updated with Alert details.", "See the guide and other"]

    def test_brackets_that_are_not_a_link_stay(self):
        assert parse_checklist("- [x] Add tests [if applicable]\n")[0]["text"] == "Add tests [if applicable]"

    def test_linked_runs(self):
        text = "see https://x/_build/results?buildId=100200&view=results and ...?buildId=100350 and buildId=100200"
        assert linked_build_ids(text) == [100200, 100350]


class TestChangelog:
    def test_ticked_and_the_file_changed(self):
        result = evaluate("Changelog updated", changed_paths=["docs/CHANGELOG.md"])
        assert result["status"] == "ok" and "CHANGELOG.md" in result["evidence"]

    def test_ticked_but_no_changelog_file_is_a_mismatch(self):
        result = evaluate("Changelog updated", changed_paths=["a.py"])
        assert result["status"] == "mismatch" and "no changelog file" in result["evidence"]

    def test_not_ticked_and_not_changed_is_open(self):
        assert evaluate("Changelog updated", checked=False, changed_paths=["a.py"])["status"] == "open"

    def test_not_ticked_but_changed_is_fine_and_says_the_box_is_empty(self):
        result = evaluate("Update the change log", checked=False, changed_paths=["CHANGELOG.md"])
        assert result["status"] == "ok" and "not ticked" in result["evidence"]


class TestTests:
    def test_created_tests_are_looked_for_by_file_name(self):
        assert evaluate("Unit tests have been created", changed_paths=["tests/test_a.py"])["status"] == "ok"
        assert evaluate("Added tests that prove fix is effective or that feature works", changed_paths=["x.Tests.ps1"])["status"] == "ok"

    def test_ticked_without_a_test_file_is_a_mismatch(self):
        assert evaluate("Unit tests have been created", changed_paths=["app/a.py"])["status"] == "mismatch"

    def test_having_run_the_tests_cannot_be_checked(self):
        for text in ("Unit tests have been run and passed", "New and existing unit tests pass locally with current changes"):
            assert evaluate(text, changed_paths=["tests/test_a.py"])["status"] == "unverifiable"


class TestWorkItems:
    def test_linked(self):
        result = evaluate("WorkItem is associated to the PR", work_items=["55", "56"])
        assert result["status"] == "ok" and "#55" in result["evidence"]

    def test_none_linked(self):
        assert evaluate("WorkItem is associated to the PR", work_items=[])["status"] == "mismatch"
        assert evaluate("WorkItem is associated to the PR", checked=False, work_items=[])["status"] == "open"

    def test_could_not_be_read(self):
        result = evaluate("WorkItem is associated to the PR", work_items=None)
        assert result["status"] == "unverifiable" and "could not be read" in result["evidence"]


class TestEverythingElse:
    def test_other_items_are_listed_as_not_verifiable(self):
        for text in ("Spell check performed", "Coding standards are followed", "Source branch is squashed while completing PR"):
            result = evaluate(text)
            assert result["status"] == "unverifiable" and result["checked"] is True


class TestRegressionRun:
    def test_a_newer_run_of_the_same_pipeline_exists(self):
        results = evaluate_checklist([], {"changed_paths": [], "work_items": [], "build_check": {"linked_id": 100200, "pipeline": "Testing", "newer_id": 100350, "newer_result": "failed"}})
        assert results[0]["status"] == "mismatch"
        assert "100200" in results[0]["evidence"] and "100350 (failed)" in results[0]["evidence"] and "Testing" in results[0]["evidence"]

    def test_the_linked_run_is_the_newest(self):
        results = evaluate_checklist([], {"changed_paths": [], "work_items": [], "build_check": {"linked_id": 5, "pipeline": "Testing", "newer_id": None, "newer_result": None}})
        assert results[0]["status"] == "ok"

    def test_it_could_not_be_compared(self):
        results = evaluate_checklist([], {"changed_paths": [], "work_items": [], "build_check": {"error": True}})
        assert results[0]["status"] == "unverifiable"

    def test_no_link_in_the_description_adds_no_check(self):
        assert evaluate_checklist([], {"changed_paths": [], "work_items": [], "build_check": None}) == []

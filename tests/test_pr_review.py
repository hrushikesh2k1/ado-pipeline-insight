"""The pull request review: which files are read, how every finding is checked, and what is worked out in code."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.services import pr_review
from app.services.pr_diff import build_view
from app.services.pr_review import (
    AiUnavailable, PullRequestReviewService, ReviewFailed, clean_findings, get_model_client, judge, summarize, thread_summaries,
)
from irp_support import FIXTURES
from pr_support import DESCRIPTION, PS_NEW, PY_NEW, PY_OLD, FakeAdo, FakePrModel, change, finding, thread

# PY_NEW: the lines this pull request changed are 2, 5 and 14-17; line 12, for example, is old code
REPORT = "scripts/report.py"
TOTALS = "scripts/totals.ps1"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)


def run(ado=None, model=None):
    ado, model = ado or FakeAdo(), model or FakePrModel()
    return PullRequestReviewService(ado, model).review("proj", "repo", 7), ado, model


def view():
    return build_view(REPORT, "Python", "edit", PY_OLD, PY_NEW)


def by_path(result):
    return {f["path"]: f for f in result["files"]}


class TestWhichFilesAreRead:
    def test_python_and_powershell_are_reviewed_and_documentation_is_not(self):
        result, _, _ = run()
        rows = by_path(result)
        assert (rows[REPORT]["status"], rows[REPORT]["language"]) == ("reviewed", "Python")
        assert (rows[TOTALS]["status"], rows[TOTALS]["language"]) == ("reviewed", "PowerShell")
        assert (rows["CHANGELOG.md"]["status"], rows["CHANGELOG.md"]["reason"]) == ("skipped", "documentation")
        assert result["method"] == "diff-per-file" and result["posted_to_ado"] is False
        assert result["source_commit"] == "a" * 40 and result["iterations"] == 1

    def test_the_reviewer_is_shown_the_diff_not_the_whole_file_as_if_it_were_new(self):
        _, _, model = run()
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        assert "+     2 | from typing import Any" in prompt
        assert "+    17 |     return sum(values) / len(values)" in prompt
        assert "     12 |         return int(text.strip(\"GB\")) * 10**9" in prompt  # old code is context, not marked
        assert "Pull request title: Add the report" in prompt and "Checklist:" in prompt

    def test_powershell_files_are_read_and_get_powershell_guidance(self):
        _, ado, model = run()
        assert "new-/scripts/totals.ps1" in ado.blob_calls
        system = next(s for s, u in model.calls if u.startswith(f"File: {TOTALS}"))
        assert "AvoidUsingWriteHost" in system and "+= on an array" in system and "Python:" not in system
        assert any("Language: PowerShell" in u for u in model.calls_of("file"))

    def test_python_files_get_python_guidance(self):
        _, _, model = run()
        system = next(s for s, u in model.calls if u.startswith(f"File: {REPORT}"))
        assert "quadratic" in system and "json.load returns any JSON type" in system and "PowerShell:" not in system

    def test_other_languages_get_the_general_guidance(self):
        ado = FakeAdo(changes=[change("/ci/pipeline.yml", "add")], blobs={"new-/ci/pipeline.yml": "steps: []\n"})
        _, _, model = run(ado)
        system = model.calls[0][0]
        assert "Look for correctness, security and error-handling problems" in system and "Python:" not in system and "PowerShell:" not in system

    def test_a_file_that_cannot_be_read_is_skipped_with_the_reason(self):
        ado = FakeAdo(blobs={**FakeAdo().blobs, "new-/scripts/totals.ps1": {"reason": "too_large"}, "new-/tests/test_report.py": {"reason": "binary"}})
        result, _, _ = run(ado)
        rows = by_path(result)
        assert rows[TOTALS]["status"] == "skipped" and "200 KB" in rows[TOTALS]["reason"]
        assert rows["tests/test_report.py"]["reason"] == "not a text file"

    def test_a_file_whose_earlier_version_is_missing_is_skipped(self):
        blobs = {k: v for k, v in FakeAdo().blobs.items() if k != "old-/scripts/report.py"}
        result, _, _ = run(FakeAdo(blobs=blobs))
        assert by_path(result)[REPORT]["reason"] == "the earlier version could not be read"

    def test_a_file_with_no_change_in_content_is_skipped(self):
        ado = FakeAdo(blobs={**FakeAdo().blobs, "old-/scripts/report.py": PY_NEW})
        assert by_path(run(ado)[0])[REPORT]["reason"] == "no change in the content"

    def test_a_file_that_is_too_long_to_compare_is_skipped(self):
        ado = FakeAdo(blobs={**FakeAdo().blobs, "new-/scripts/report.py": "x = 1\n" * 4001})
        assert "too long to compare" in by_path(run(ado)[0])[REPORT]["reason"]

    def test_deleted_files_are_listed_and_not_read(self):
        ado = FakeAdo(changes=[change("/old.py", "delete"), change("/scripts/report.py")])
        result, ado, _ = run(ado)
        assert by_path(result)["old.py"]["reason"] == "deleted file"
        assert "old-/old.py" not in ado.blob_calls

    def test_at_most_twenty_files_are_reviewed_and_the_rest_say_why(self):
        names = [f"/src/m{n:02d}.py" for n in range(25)]
        ado = FakeAdo(changes=[change(n, "add") for n in names], blobs={f"new-{n}": "x = 1\n" for n in names})
        result, _, model = run(ado)
        assert sum(1 for f in result["files"] if f["status"] == "reviewed") == 20
        skipped = [f for f in result["files"] if f["status"] == "skipped"]
        assert len(skipped) == 5 and all("over the limit of 20" in f["reason"] for f in skipped)
        assert len(model.calls_of("file")) == 20

    def test_python_and_powershell_are_reviewed_first_when_there_is_not_room_for_everything(self):
        yaml = [f"/ci/p{n:02d}.yml" for n in range(20)]
        ado = FakeAdo(changes=[change(n, "add") for n in yaml] + [change("/tools/x.ps1", "add")], blobs={**{f"new-{n}": "a: 1\n" for n in yaml}, "new-/tools/x.ps1": "Get-Date\n"})
        rows = by_path(run(ado)[0])
        assert rows["tools/x.ps1"]["status"] == "reviewed"
        assert rows["ci/p19.yml"]["status"] == "skipped"

    def test_only_a_changelog_means_nothing_is_reviewed_and_the_model_is_not_asked(self):
        ado = FakeAdo(changes=[change("/CHANGELOG.md")])
        result, _, model = run(ado)
        assert result["verdict"] == "NOT_REVIEWED" and "Nothing could be reviewed" in result["summary"]
        assert model.calls == [] and result["comments"] == []

    def test_a_pull_request_with_no_pushes_or_no_changes_is_refused(self):
        with pytest.raises(ReviewFailed) as error:
            run(FakeAdo(iterations=0))
        assert error.value.status_code == 422
        with pytest.raises(ReviewFailed) as error:
            run(FakeAdo(changes=[]))
        assert error.value.status_code == 422 and "no file changes" in str(error.value)

    def test_the_latest_push_is_the_one_reviewed(self):
        result, _, _ = run(FakeAdo(iterations=4))
        assert result["iterations"] == 4 and "push 4 of 4" in result["summary"]


class TestCleaningFindings:
    def test_a_finding_on_changed_lines_is_kept_with_its_place(self):
        kept, removed = clean_findings([finding(17, "Division by zero")], view())
        assert removed == [] and len(kept) == 1
        assert (kept[0]["file_path"], kept[0]["line_number"], kept[0]["end_line"], kept[0]["language"]) == (REPORT, 17, None, "Python")
        assert kept[0]["existing_thread"] is None and kept[0]["verified"] is None

    def test_a_finding_on_old_code_is_removed(self):
        kept, removed = clean_findings([finding(12, "Old code")], view())
        assert kept == [] and removed == [("Old code", "it pointed at lines this pull request did not change")]

    def test_a_range_that_touches_a_changed_line_is_kept(self):
        kept, _ = clean_findings([finding(13, "Range", end_line=15)], view())
        assert kept and (kept[0]["line_number"], kept[0]["end_line"]) == (13, 15)

    def test_a_line_that_does_not_exist_or_is_missing(self):
        kept, removed = clean_findings([finding(99, "Beyond"), finding(0, "Zero"), {**finding(5, "No line"), "line": None}, {**finding(5, "Words"), "line": "five"}], view())
        assert kept == [] and {why for _, why in removed} == {"it did not point at a line of the file"}

    def test_a_line_given_as_text_is_understood(self):
        kept, _ = clean_findings([finding("17", "As text")], view())
        assert kept and kept[0]["line_number"] == 17

    def test_a_finding_without_an_explanation_is_removed(self):
        kept, removed = clean_findings([finding(17, "Empty", comment="  ")], view())
        assert kept == [] and removed == [("Empty", "it had no explanation")]

    def test_praise_is_dropped_quietly(self):
        kept, removed = clean_findings([finding(17, "Nice", severity="praise")], view())
        assert kept == [] and removed == []

    def test_an_end_line_before_the_line_or_past_the_file_is_corrected(self):
        kept, _ = clean_findings([finding(16, "Backwards", end_line=3), finding(16, "Past the end", end_line=500)], view())
        assert (kept[0]["end_line"], kept[1]["end_line"]) == (None, 17)

    def test_a_very_long_range_is_cut(self):
        long_view = build_view("a.py", "Python", "add", "", "x = 1\n" * 100)
        kept, _ = clean_findings([finding(1, "Whole file", end_line=100)], long_view)
        assert kept[0]["end_line"] == 40

    def test_the_same_finding_twice_is_kept_once(self):
        kept, _ = clean_findings([finding(17, "Same"), finding(17, "same")], view())
        assert len(kept) == 1

    def test_unknown_category_and_severity_get_safe_values(self):
        kept, _ = clean_findings([finding(17, "Odd", category="style", severity="blocker")], view())
        assert (kept[0]["category"], kept[0]["severity"]) == ("maintainability", "suggestion")

    def test_the_worst_findings_come_first(self):
        kept, _ = clean_findings([finding(14, "a", severity="suggestion"), finding(15, "b", severity="critical"), finding(16, "c", severity="warning")], view())
        assert [f["severity"] for f in kept] == ["critical", "warning", "suggestion"]

    def test_malformed_entries_are_ignored(self):
        assert clean_findings(["text", 5, None, {"line": 17}], view()) == ([], [("Review finding", "it had no explanation")])
        assert clean_findings("not a list", view()) == ([], [])

    def test_a_suggested_replacement_is_kept_for_changed_lines_and_cleaned(self):
        kept, _ = clean_findings([finding(5, "Type", suggestion_code="```python\ndef load(path) -> Any:\n```")], view())
        assert kept[0]["suggestion_code"] == "def load(path) -> Any:"

    def test_a_suggestion_for_lines_that_were_not_all_changed_is_dropped_but_the_finding_stays(self):
        kept, _ = clean_findings([finding(4, "Spans old code", end_line=5, suggestion_code="x = 1")], view())
        assert len(kept) == 1 and kept[0]["suggestion_code"] is None

    def test_a_suggestion_that_repeats_the_code_is_dropped(self):
        kept, _ = clean_findings([finding(17, "Same code", suggestion_code="    return sum(values) / len(values)")], view())
        assert kept[0]["suggestion_code"] is None

    def test_code_that_was_only_removed_can_be_commented_on_at_the_next_line(self):
        gone = build_view("a.py", "Python", "edit", "alpha\nbeta\ngamma\n", "alpha\ngamma\n")
        kept, _ = clean_findings([finding(2, "Removed the check")], gone)
        assert len(kept) == 1


class TestSecondCheck:
    def test_a_finding_that_does_not_hold_is_removed_and_explained(self):
        model = FakePrModel({REPORT: [finding(17, "Division by zero"), finding(5, "Return type")]}, holds=lambda path, numbers: {1: (False, "average() is never called with an empty list")})
        result, _, _ = run(model=model)
        assert [c["title"] for c in result["comments"]] == ["Return type"]
        assert any("Removed on a second check: scripts/report.py: Division by zero (average() is never called with an empty list)" in n for n in result["notes"])
        assert any("1 finding(s) did not hold on a second check" in n for n in result["notes"])

    def test_findings_that_hold_are_marked_confirmed(self):
        result, _, model = run(model=FakePrModel({REPORT: [finding(17)]}))
        assert result["comments"][0]["verified"] is True
        assert "1. line 17:" in model.calls_of("verify")[0]

    def test_the_second_check_sees_the_diff_and_the_suggested_code(self):
        model = FakePrModel({REPORT: [finding(5, "Type", suggestion_code="def load(path) -> Any:")]})
        run(model=model)
        prompt = model.calls_of("verify")[0]
        assert "Suggested replacement:\ndef load(path) -> Any:" in prompt and "+     5 | def load(path) -> dict:" in prompt

    def test_when_the_second_check_cannot_run_the_findings_stay_and_say_so(self):
        model = FakePrModel({REPORT: [finding(17)]}, holds=lambda path, numbers: RuntimeError("down"))
        result, _, _ = run(model=model)
        assert len(result["comments"]) == 1 and result["comments"][0]["verified"] is None
        assert any("second check could not run" in n for n in result["notes"])

    def test_files_without_findings_are_not_double_checked(self):
        _, _, model = run()
        assert model.calls_of("verify") == []

    def test_a_finding_the_checker_does_not_mention_stays_unconfirmed(self):
        class Silent(FakePrModel):
            def _create(self, model, messages, temperature=0, response_format=None):
                if messages[0]["content"].startswith("You check findings"):
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"findings": []}'))])
                return super()._create(model, messages, temperature, response_format)

        model = Silent({REPORT: [finding(17)]})
        model.client.chat.completions.create = model._create
        result, _, _ = run(model=model)
        assert result["comments"][0]["verified"] is None


class TestRemovedBeforeShowing:
    def test_what_was_removed_is_counted_in_the_notes(self):
        model = FakePrModel({REPORT: [finding(17, "Good"), finding(12, "Old code"), finding(99, "Nowhere"), finding(2, "x", comment="")]})
        result, _, _ = run(model=model)
        assert [c["title"] for c in result["comments"]] == ["Good"]
        note = next(n for n in result["notes"] if n.startswith("Removed before showing"))
        assert "1 finding(s) pointed at lines this pull request did not change" in note and "2 finding(s) were malformed" in note

    def test_more_findings_than_the_limit_are_cut_and_counted(self):
        many = [finding(14 + n % 4, f"Finding {n}", severity="suggestion") for n in range(12)]
        result, _, _ = run(model=FakePrModel({REPORT: many}))
        assert len(result["comments"]) == 8
        assert any("4 lower-priority finding(s) in scripts/report.py are not shown" in n for n in result["notes"])


class TestExistingComments:
    def test_a_finding_people_already_raised_is_marked_and_does_not_count(self):
        ado = FakeAdo(threads=[thread(REPORT, 17, "Please guard against an empty list", status="fixed")])
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}))
        comment = result["comments"][0]
        assert comment["existing_thread"] == "Already raised by Sam Reviewer (resolved)" and comment["existing_status"] == "fixed"
        assert result["verdict"] == "APPROVED" and "already raised in the pull request comments" in result["summary"]

    def test_a_thread_that_is_still_open_still_counts(self):
        ado = FakeAdo(threads=[thread(REPORT, 16, "Look at this", status="active")])
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}))
        assert result["comments"][0]["existing_thread"] == "Already raised by Sam Reviewer (open)"
        assert result["verdict"] == "APPROVED_WITH_SUGGESTIONS"

    def test_a_thread_far_away_or_on_another_file_is_not_a_match(self):
        ado = FakeAdo(threads=[thread(REPORT, 3, "far"), thread("other.py", 17, "other file")])
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}))
        assert result["comments"][0]["existing_thread"] is None

    def test_the_reviewer_is_told_what_was_already_said_on_that_file_only(self):
        ado = FakeAdo(threads=[thread(REPORT, 14, "Add a header comment", author="Alex"), thread(TOTALS, 5, "totals thread"), thread(None, None, "PR level remark"),
                               thread(REPORT, 9, "system noise", system=True)])
        _, _, model = run(ado)
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        assert "- line 14 [resolved] Alex: Add a header comment" in prompt
        assert "totals thread" not in prompt and "PR level remark" not in prompt and "system noise" not in prompt
        assert "(none)" in next(u for u in model.calls_of("file") if u.startswith("File: tests/test_report.py"))


class TestThreadSummaries:
    def test_system_deleted_and_empty_comments_are_left_out(self):
        threads = [thread(REPORT, 3, "a human comment"), thread(REPORT, 4, "merge attempt", system=True), {**thread(REPORT, 5, "gone"), "isDeleted": True},
                   {"status": "active", "isDeleted": False, "threadContext": None, "comments": [{"commentType": "text", "content": "  "}]}]
        found = thread_summaries(threads)
        assert [t["text"] for t in found] == ["a human comment"]

    def test_the_place_the_author_and_the_status(self):
        found = thread_summaries([thread(REPORT, 7, "text", status="wontFix", author="Pat")])[0]
        assert (found["path"], found["line"], found["end"], found["status"], found["author"]) == (REPORT, 7, 7, "wontFix", "Pat")

    def test_a_comment_on_the_whole_pull_request_has_no_file(self):
        found = thread_summaries([thread(None, None, "general")])[0]
        assert found["path"] == "" and found["line"] is None

    def test_images_become_a_word_and_text_is_shortened(self):
        found = thread_summaries([thread(REPORT, 1, "see ![shot](https://x/y.png) " + "word " * 200)])[0]
        assert "[image]" in found["text"] and "https://x" not in found["text"] and len(found["text"]) <= 300

    def test_nothing(self):
        assert thread_summaries(None) == [] and thread_summaries([]) == []


class TestVerdictAndScorecard:
    def c(self, severity, category="correctness", status=None):
        return {"severity": severity, "category": category, "existing_status": status}

    def test_no_findings(self):
        verdict, card = judge([])
        assert verdict == "APPROVED" and set(card.values()) == {"NO_FINDINGS"}

    def test_a_critical_finding_requests_changes(self):
        verdict, card = judge([self.c("critical", "security"), self.c("suggestion", "maintainability")])
        assert verdict == "CHANGES_REQUESTED" and card["security"] == "CONCERNING" and card["maintainability"] == "GOOD" and card["correctness"] == "NO_FINDINGS"

    def test_a_warning_or_suggestion_is_approved_with_suggestions(self):
        assert judge([self.c("warning", "performance")])[0] == "APPROVED_WITH_SUGGESTIONS"
        assert judge([self.c("warning", "performance")])[1]["performance"] == "NEEDS_IMPROVEMENT"
        assert judge([self.c("suggestion")])[0] == "APPROVED_WITH_SUGGESTIONS"

    def test_resolved_findings_do_not_count_but_open_ones_do(self):
        assert judge([self.c("critical", status="fixed"), self.c("critical", status="wontFix")])[0] == "APPROVED"
        assert judge([self.c("critical", status="active")])[0] == "CHANGES_REQUESTED"

    def test_the_verdict_comes_from_the_findings_not_from_the_model(self):
        model = FakePrModel({REPORT: [finding(17, severity="suggestion")]})
        result, _, _ = run(model=model)
        assert result["verdict"] == "APPROVED_WITH_SUGGESTIONS" and result["scorecard"]["correctness"] == "GOOD" and result["scorecard"]["security"] == "NO_FINDINGS"


class TestSummary:
    def files(self, reviewed=2, skipped=1):
        return ([{"path": f"a{n}.py", "language": "Python", "status": "reviewed", "reason": None} for n in range(reviewed)]
                + [{"path": f"b{n}.md", "language": None, "status": "skipped", "reason": "documentation"} for n in range(skipped)])

    def test_counts_and_where(self):
        text = summarize(self.files(), [{"severity": "critical"}, {"severity": "warning"}, {"severity": "warning"}], "f" * 40, 3, 5)
        assert text == "Reviewed 2 of 3 changed files (2 Python) at commit ffffffff, push 3 of 5. 3 findings: 1 critical, 2 warnings. 1 file was not reviewed."

    def test_no_findings_says_it_is_about_the_files_reviewed(self):
        assert "No findings in the files reviewed." in summarize(self.files(1, 0), [], "", 1, 1) and "the latest push" in summarize(self.files(1, 0), [], "", 1, 1)

    def test_nothing_reviewed_says_which_files_and_why(self):
        assert summarize(self.files(0, 2), [], "", 1, 1) == "Reviewed 0 of 2 changed files at the latest push, push 1 of 1. Nothing could be reviewed: b0.md (documentation); b1.md (documentation)."

    def test_when_more_than_three_files_were_skipped_the_rest_are_counted(self):
        text = summarize(self.files(0, 5), [], "", 1, 1)
        assert "b0.md (documentation); b1.md (documentation); b2.md (documentation); and 2 more." in text and "(none)" not in text

    def test_one_finding_is_singular(self):
        assert "1 finding: 1 suggestion." in summarize(self.files(1, 0), [{"severity": "suggestion"}], "", 1, 1)


class TestAiFailures:
    def test_one_file_failing_does_not_stop_the_others(self):
        model = FakePrModel({TOTALS: RuntimeError("boom"), REPORT: [finding(17)]})
        result, _, _ = run(model=model)
        rows = by_path(result)
        assert rows[TOTALS]["status"] == "skipped" and rows[TOTALS]["reason"] == "the AI call failed"
        assert rows[REPORT]["status"] == "reviewed" and len(result["comments"]) == 1
        assert "2 of 4" in result["summary"] or "Reviewed 2 of 4" in result["summary"]

    def test_if_every_file_fails_there_is_no_review(self):
        model = FakePrModel({REPORT: RuntimeError("x"), TOTALS: RuntimeError("x"), "tests/test_report.py": RuntimeError("x")})
        with pytest.raises(ReviewFailed) as error:
            run(model=model)
        assert error.value.status_code == 502 and "Nothing was reviewed" in str(error.value)

    def test_a_slow_model_gives_a_partial_review_not_a_timeout(self, monkeypatch):
        clock = iter([0, 100, 200, 300, 400, 500, 600])  # the first reading sets the deadline (170 s); each file is checked against it
        monkeypatch.setattr(pr_review.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(pr_review, "WORKERS", 1)
        result, _, model = run(model=FakePrModel({REPORT: [finding(17)]}))
        rows = by_path(result)
        assert rows[REPORT]["status"] == "reviewed" and len(result["comments"]) == 1
        late = [f for f in result["files"] if f["reason"] == "not reached in the time allowed"]
        assert len(late) == 2 and all(f["status"] == "skipped" for f in late)
        assert len(model.calls_of("file")) == 1

    def test_if_the_time_runs_out_before_any_file_there_is_no_review(self, monkeypatch):
        clock = iter([0, 500, 600, 700, 800])
        monkeypatch.setattr(pr_review.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(pr_review, "WORKERS", 1)
        with pytest.raises(ReviewFailed, match="not reached in the time allowed"):
            run()

    def test_a_first_failure_is_retried(self):
        class Flaky(FakePrModel):
            attempts = 0

            def _create(self, model, messages, temperature=0, response_format=None):
                if messages[0]["content"].startswith("You review one changed file") and f"File: {REPORT}" in messages[1]["content"]:
                    Flaky.attempts += 1
                    if Flaky.attempts == 1:
                        raise RuntimeError("busy")
                return super()._create(model, messages, temperature, response_format)

        model = Flaky({REPORT: [finding(17)]})
        model.client.chat.completions.create = model._create
        result, _, _ = run(model=model)
        assert by_path(result)[REPORT]["status"] == "reviewed" and Flaky.attempts == 2


class TestChecklistInTheReview:
    def statuses(self, result):
        return {c["item"]: c["status"] for c in result["checklist"]}

    def test_claims_are_checked_against_the_pull_request(self):
        result, _, _ = run()
        states = self.statuses(result)
        assert states["Changelog updated"] == "ok"
        assert states["Unit tests have been created"] == "ok"
        assert states["WorkItem is associated to the PR"] == "ok"
        assert states["Spell check performed"] == "unverifiable" and states["Coding standards are followed"] == "unverifiable"

    def test_the_run_in_the_description_is_compared_with_the_newest_run_of_that_pipeline(self):
        result, _, _ = run()
        build = next(c for c in result["checklist"] if c["item"].startswith("The run linked"))
        assert build["status"] == "mismatch" and "100" in build["evidence"] and "120 (failed)" in build["evidence"] and "Regression" in build["evidence"]

    def test_the_newest_run_is_fine(self):
        ado = FakeAdo(builds=[{"id": 100, "result": "succeeded", "definition": {"id": 7, "name": "Regression"}}, {"id": 90, "result": "failed", "definition": {"id": 7}}])
        result, _, _ = run(ado)
        assert next(c for c in result["checklist"] if c["item"].startswith("The run linked"))["status"] == "ok"

    def test_a_newer_run_of_another_pipeline_does_not_count(self):
        ado = FakeAdo(builds=[{"id": 130, "result": "failed", "definition": {"id": 99, "name": "CI"}}, {"id": 100, "result": "succeeded", "definition": {"id": 7}}])
        result, _, _ = run(ado)
        assert next(c for c in result["checklist"] if c["item"].startswith("The run linked"))["status"] == "ok"

    def test_ticked_claims_without_evidence_are_flagged(self):
        ado = FakeAdo(changes=[change("/scripts/report.py")], work_items=[])
        states = self.statuses(run(ado)[0])
        assert states["Changelog updated"] == "mismatch" and states["Unit tests have been created"] == "mismatch" and states["WorkItem is associated to the PR"] == "mismatch"

    def test_what_cannot_be_read_is_reported_and_the_review_still_happens(self):
        result, _, _ = run(FakeAdo(fail={"threads", "work_items", "builds"}), FakePrModel({REPORT: [finding(17)]}))
        assert len(result["comments"]) == 1
        assert any("The existing comments could not be read" in n for n in result["notes"])
        assert any("The linked work items could not be read" in n for n in result["notes"])
        states = self.statuses(result)
        assert states["WorkItem is associated to the PR"] == "unverifiable"
        assert next(c for c in result["checklist"] if c["item"].startswith("The run linked"))["status"] == "unverifiable"

    def test_a_description_without_a_checklist_or_link_adds_nothing(self):
        result, _, _ = run(FakeAdo(description="Just words."))
        assert result["checklist"] == []

    def test_the_pull_request_itself_must_be_readable(self):
        with pytest.raises(RuntimeError):
            run(FakeAdo(fail={"get_pull_request"}))


class TestDescriptionCheck:
    def test_changes_the_description_does_not_mention_are_listed(self):
        model = FakePrModel(gaps=["a retry mechanism was added", "  "], purposes={REPORT: "adds an average function"})
        result, _, _ = run(model=model)
        assert result["clarifications"] == ["The description does not mention: a retry mechanism was added"]
        sent = model.calls_of("description")[0]
        assert "scripts/report.py: adds an average function" in sent and "Adds a report." in sent

    def test_a_failed_check_adds_nothing(self):
        assert run(model=FakePrModel(gaps=RuntimeError("down")))[0]["clarifications"] == []

    def test_no_description_means_no_call(self):
        _, _, model = run(FakeAdo(description=""))
        assert model.calls_of("description") == []

    def test_no_more_than_three(self):
        result, _, _ = run(model=FakePrModel(gaps=["a", "b", "c", "d", "e"]))
        assert len(result["clarifications"]) == 3


class TestModelClient:
    def settings(self, **over):
        base = dict(azure_openai_endpoint="https://x.openai.azure.com", azure_openai_deployment="gpt", azure_openai_api_version="2024-02-01", azure_openai_api_key="k")
        base.update(over)
        return SimpleNamespace(**base)

    def test_not_configured_means_no_review_and_says_so(self, monkeypatch):
        for missing in ({"azure_openai_endpoint": ""}, {"azure_openai_deployment": None}):
            monkeypatch.setattr(pr_review, "get_settings", lambda missing=missing: self.settings(**missing))
            with pytest.raises(AiUnavailable, match="Nothing was reviewed"):
                get_model_client()

    def test_a_configured_model_is_used(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(pr_review, "get_settings", lambda: self.settings())
        monkeypatch.setattr(pr_review, "PipelineRecommendationClient", lambda *args: seen.setdefault("args", args) and "client")
        assert get_model_client() == "client" and seen["args"] == ("https://x.openai.azure.com", "gpt", "2024-02-01", "k")

    def test_a_client_that_cannot_start_means_no_review(self, monkeypatch):
        def broken(*args):
            raise ValueError("bad endpoint")
        monkeypatch.setattr(pr_review, "get_settings", lambda: self.settings())
        monkeypatch.setattr(pr_review, "PipelineRecommendationClient", broken)
        with pytest.raises(AiUnavailable, match="could not be started"):
            get_model_client()


ALERT_OLD = (FIXTURES / "vpn_log_alert.arm.json").read_text(encoding="utf-8")
ALERT_NEW = ALERT_OLD.replace('"threshold": 0', '"threshold": 3').replace('"windowSize": "PT10M"', '"windowSize": "PT15M"')
ALERT_PATH = "alerts/vpn.json"


def alert_ado(new=ALERT_NEW, old=ALERT_OLD, **over):
    blobs = {f"new-/{ALERT_PATH}": new, f"old-/{ALERT_PATH}": old}
    return FakeAdo(changes=[change(f"/{ALERT_PATH}")], blobs=blobs, description="", **over)


def line_of(text: str, part: str) -> int:
    return next(n for n, line in enumerate(text.splitlines(), 1) if part in line)


class TestAlertTemplates:
    """The files this review exists for: alerts written as ARM templates."""

    def test_an_alert_template_is_reviewed_not_skipped_as_data(self):
        result, _, _ = run(alert_ado())
        row = by_path(result)[ALERT_PATH]
        assert (row["status"], row["language"], row["reason"]) == ("reviewed", "ARM template", None)
        assert "Reviewed 1 of 1 changed files (1 ARM template)" in result["summary"]

    def test_the_reviewer_is_told_what_the_alert_means_and_what_changed(self):
        _, _, model = run(alert_ado())
        prompt = model.calls_of("file")[0]
        assert "What the alert rules in this template are, and what changed in them:" in prompt
        assert "Fires when the number of rows returned by the alert query is greater than 3" in prompt
        assert "window size: PT10M -> PT15M" in prompt and "Evaluated every 5 minutes over a window of 15 minutes." in prompt

    def test_the_whole_query_is_in_the_diff_not_cut_at_the_usual_width(self):
        _, _, model = run(alert_ado(new=ALERT_NEW.replace("Disconnects = count()", "Disconnects = count() " + "x" * 400)))
        prompt = model.calls_of("file")[0]
        assert "x" * 400 in prompt and "project TimeGenerated, Resource, Disconnects" in prompt

    def test_alert_guidance_is_given_and_it_is_the_one_checked_against_microsofts_documentation(self):
        _, _, model = run(alert_ado())
        system = model.calls[0][0]
        assert "Azure Monitor alerts in an ARM template" in system and "minFailingPeriodsToAlert larger than numberOfEvaluationPeriods" in system
        assert "securestring" in system and "Python:" not in system and "PowerShell:" not in system

    def test_a_finding_on_the_changed_threshold_is_kept_and_checked_with_the_alert_details(self):
        threshold = line_of(ALERT_NEW, '"threshold": 3')
        model = FakePrModel({ALERT_PATH: [finding(threshold, "Threshold of 3 hides single disconnects", comment="With a threshold of 3 a single tunnel disconnect no longer fires the alert. Keep 0 or lower the window.")]})
        result, _, _ = run(alert_ado(), model)
        assert [(c["file_path"], c["line_number"], c["verified"]) for c in result["comments"]] == [(ALERT_PATH, threshold, True)]
        assert "The alert rules, read from the template:" in model.calls_of("verify")[0]

    def test_a_finding_on_an_unchanged_line_of_the_template_is_still_removed(self):
        model = FakePrModel({ALERT_PATH: [finding(line_of(ALERT_NEW, '"severity": 1'), "Unchanged severity")]})
        result, _, _ = run(alert_ado(), model)
        assert result["comments"] == []

    def test_a_template_that_is_no_longer_valid_json_is_put_in_front_of_the_reviewer(self):
        _, _, model = run(alert_ado(new=ALERT_NEW.replace('"resources": [', '"resources": [,')))
        assert "cannot be deployed as it is" in model.calls_of("file")[0]

    def test_json_that_is_not_an_arm_template_is_skipped_with_that_reason_and_costs_one_fetch(self):
        ado = FakeAdo(changes=[change("/config/data.json")], blobs={"new-/config/data.json": '{"name": "pkg", "items": [1, 2]}', "old-/config/data.json": "{}"}, description="")
        result, ado, model = run(ado)
        assert by_path(result)["config/data.json"]["reason"] == "JSON file that is not an ARM template"
        assert "old-/config/data.json" not in ado.blob_calls and model.calls == []
        assert "Nothing could be reviewed: config/data.json (JSON file that is not an ARM template)." in result["summary"]

    def test_json_files_that_are_not_templates_do_not_use_up_the_limit(self):
        names = [f"/data/d{n:02d}.json" for n in range(25)] + ["/src/a.py", "/src/b.py"]
        blobs = {f"new-{n}": '{"x": 1}' for n in names[:25]} | {"new-/src/a.py": "x = 1\n", "new-/src/b.py": "y = 2\n"}
        result, _, _ = run(FakeAdo(changes=[change(n, "add") for n in names], blobs=blobs, description=""))
        rows = by_path(result)
        assert rows["src/a.py"]["status"] == "reviewed" and rows["src/b.py"]["status"] == "reviewed"
        assert all(rows[f"data/d{n:02d}.json"]["reason"] == "JSON file that is not an ARM template" for n in range(25))

    def test_a_very_large_pull_request_is_not_read_without_end(self, monkeypatch):
        monkeypatch.setattr(pr_review, "MAX_EXAMINED", 3)
        names = [f"/data/d{n}.json" for n in range(5)]
        ado = FakeAdo(changes=[change(n, "add") for n in names], blobs={f"new-{n}": '{"x": 1}' for n in names}, description="")
        result, ado, _ = run(ado)
        reasons = [f["reason"] for f in result["files"]]
        assert reasons.count("JSON file that is not an ARM template") == 3 and reasons.count("not examined: more than 3 files in this pull request") == 2
        assert len(ado.blob_calls) == 3

    def test_kql_files_are_read_with_kql_guidance(self):
        ado = FakeAdo(changes=[change("/queries/restarts.kql", "add")], blobs={"new-/queries/restarts.kql": "KubePodInventory\n| take 100\n"}, description="")
        result, _, model = run(ado)
        assert by_path(result)["queries/restarts.kql"]["language"] == "KQL"
        assert "KQL: look for a missing or misplaced time filter" in model.calls[0][0]

    def test_alert_templates_are_reviewed_before_other_files_when_there_is_not_room_for_all(self):
        yaml = [f"/ci/p{n:02d}.yml" for n in range(20)]
        ado = FakeAdo(changes=[change(n, "add") for n in yaml] + [change(f"/{ALERT_PATH}")],
                      blobs={**{f"new-{n}": "a: 1\n" for n in yaml}, f"new-/{ALERT_PATH}": ALERT_NEW, f"old-/{ALERT_PATH}": ALERT_OLD}, description="")
        assert by_path(run(ado)[0])[ALERT_PATH]["status"] == "reviewed"


class TestNothingIsMadeUp:
    def test_the_prompts_hold_no_text_from_a_single_example_pull_request(self):
        text = pr_review.FILE_SYSTEM + pr_review.VERIFY_SYSTEM + pr_review.DESCRIPTION_SYSTEM
        assert "MDC" not in text and "regression report" not in text.lower()

    def test_the_old_canned_review_is_gone(self):
        import app.services.ai_service as ai_service
        assert not hasattr(ai_service, "_pr_review_fallback") and not hasattr(ai_service.AIService, "review_pull_request")

    def test_a_clean_pull_request_gets_no_invented_comments(self):
        result, _, _ = run()
        assert result["comments"] == [] and result["verdict"] == "APPROVED" and "No findings in the files reviewed." in result["summary"]

    def test_the_scope_of_the_review_is_always_stated(self):
        result, _, _ = run()
        assert "cannot judge how the result looks" in result["scope_note"]

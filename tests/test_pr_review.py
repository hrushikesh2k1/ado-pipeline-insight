"""The pull request review: which files are read, how every finding is checked, and what is worked out in code."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.services import pr_review
from app.services.pr_diff import build_view
from app.services.pr_review import (
    AiUnavailable, PullRequestReviewService, ReviewFailed, clean_description, clean_findings, get_model_client, judge, summarize, thread_summaries,
)
from irp_support import FIXTURES
from pr_support import DESCRIPTION, PS_NEW, PY_NEW, PY_OLD, FakeAdo, FakePrModel, change, evidence_at, finding, thread

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


def grounded(line, *args, **over):
    """A finding that quotes the code on its line, as a well-behaved model does (for tests that call clean_findings directly)."""
    over.setdefault("evidence", evidence_at(PY_NEW, int(line) if str(line).isdigit() else 0))
    return finding(line, *args, **over)


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
        kept, removed = clean_findings([grounded(17, "Division by zero")], view())
        assert removed == [] and len(kept) == 1
        assert (kept[0]["file_path"], kept[0]["line_number"], kept[0]["end_line"], kept[0]["language"]) == (REPORT, 17, None, "Python")
        assert kept[0]["existing_thread"] is None and kept[0]["verified"] is None

    def test_a_finding_on_old_code_is_removed(self):
        kept, removed = clean_findings([grounded(12, "Old code")], view())
        assert kept == [] and removed == [("Old code", "it pointed at lines this pull request did not change")]

    def test_a_range_that_touches_a_changed_line_is_kept(self):
        kept, _ = clean_findings([grounded(13, "Range", end_line=15)], view())
        assert kept and (kept[0]["line_number"], kept[0]["end_line"]) == (13, 15)

    def test_a_line_that_does_not_exist_or_is_missing(self):
        kept, removed = clean_findings([grounded(99, "Beyond"), grounded(0, "Zero"), {**grounded(5, "No line"), "line": None}, {**grounded(5, "Words"), "line": "five"}], view())
        assert kept == [] and {why for _, why in removed} == {"it did not point at a line of the file"}

    def test_a_line_given_as_text_is_understood(self):
        kept, _ = clean_findings([grounded("17", "As text")], view())
        assert kept and kept[0]["line_number"] == 17

    def test_a_finding_without_an_explanation_is_removed(self):
        kept, removed = clean_findings([grounded(17, "Empty", comment="  ")], view())
        assert kept == [] and removed == [("Empty", "it had no explanation")]

    def test_praise_is_dropped_quietly(self):
        kept, removed = clean_findings([grounded(17, "Nice", severity="praise")], view())
        assert kept == [] and removed == []

    def test_an_end_line_before_the_line_or_past_the_file_is_corrected(self):
        kept, _ = clean_findings([grounded(16, "Backwards", end_line=3), grounded(16, "Past the end", end_line=500)], view())
        assert (kept[0]["end_line"], kept[1]["end_line"]) == (None, 17)

    def test_a_very_long_range_is_cut(self):
        long_view = build_view("a.py", "Python", "add", "", "value = compute(1)\n" * 100)
        kept, _ = clean_findings([grounded(1, "Whole file", end_line=100, evidence="value = compute(1)")], long_view)
        assert kept[0]["end_line"] == 40

    def test_the_same_finding_twice_is_kept_once(self):
        kept, _ = clean_findings([grounded(17, "Same"), grounded(17, "same")], view())
        assert len(kept) == 1

    def test_unknown_category_and_severity_get_safe_values(self):
        kept, _ = clean_findings([grounded(17, "Odd", category="style", severity="blocker")], view())
        assert (kept[0]["category"], kept[0]["severity"]) == ("maintainability", "suggestion")

    def test_the_worst_findings_come_first(self):
        kept, _ = clean_findings([grounded(14, "a", severity="suggestion"), grounded(15, "b", severity="critical"), grounded(16, "c", severity="warning")], view())
        assert [f["severity"] for f in kept] == ["critical", "warning", "suggestion"]

    def test_malformed_entries_are_ignored(self):
        assert clean_findings(["text", 5, None, {"line": 17}], view()) == ([], [("Review finding", "it had no explanation")])
        assert clean_findings("not a list", view()) == ([], [])

    def test_a_suggested_replacement_is_kept_for_changed_lines_and_cleaned(self):
        kept, _ = clean_findings([grounded(5, "Type", suggestion_code="```python\ndef load(path) -> Any:\n```")], view())
        assert kept[0]["suggestion_code"] == "def load(path) -> Any:"

    def test_a_suggestion_for_lines_that_were_not_all_changed_is_dropped_but_the_finding_stays(self):
        kept, _ = clean_findings([grounded(4, "Spans old code", end_line=5, suggestion_code="x = 1")], view())
        assert len(kept) == 1 and kept[0]["suggestion_code"] is None

    def test_a_suggestion_that_repeats_the_code_is_dropped(self):
        kept, _ = clean_findings([grounded(17, "Same code", suggestion_code="    return sum(values) / len(values)")], view())
        assert kept[0]["suggestion_code"] is None

    def test_code_that_was_only_removed_can_be_commented_on_at_the_next_line(self):
        gone = build_view("a.py", "Python", "edit", "first line\nsecond line\nthird line\n", "first line\nthird line\n")
        kept, _ = clean_findings([grounded(2, "Removed the check", evidence="third line")], gone)
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

    def test_the_reviewer_is_told_what_was_said_on_that_file_and_on_the_pull_request_as_a_whole(self):
        ado = FakeAdo(threads=[thread(REPORT, 14, "Add a header comment", author="Alex"), thread(TOTALS, 5, "totals thread"), thread(None, None, "PR level remark"),
                               thread(REPORT, 9, "system noise", system=True)])
        _, _, model = run(ado)
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        assert "E1: line 14 [resolved] Alex: Add a header comment" in prompt
        assert "E2: (on the pull request as a whole) [resolved] Sam Reviewer: PR level remark" in prompt
        assert "totals thread" not in prompt and "system noise" not in prompt
        other = next(u for u in model.calls_of("file") if u.startswith("File: tests/test_report.py"))
        assert "E1: (on the pull request as a whole)" in other and "Alex" not in other

    def test_the_last_reply_is_told_too_so_a_deferred_point_is_not_raised_again(self):
        ado = FakeAdo(threads=[thread(REPORT, 14, "Use a dict lookup here", replies=[("Pat", "Will be done in the follow-up work item"), ("Sam", "Fine, resolved")])])
        _, _, model = run(ado)
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        assert "E1: line 14 [resolved] Sam Reviewer: Use a dict lookup here | last reply from Sam: Fine, resolved" in prompt

    def test_a_comment_on_the_whole_file_is_told_but_is_not_matched_by_line(self):
        ado = FakeAdo(threads=[thread(REPORT, None, "This file needs a header")])
        result, _, model = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}))
        assert "E1: (on the file) [resolved] Sam Reviewer: This file needs a header" in next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        assert result["comments"][0]["existing_thread"] is None

    def test_how_many_comments_are_told_is_bounded(self):
        threads = [thread(REPORT, 3 + n % 5, f"file comment {n}") for n in range(15)] + [thread(None, None, f"general {n}") for n in range(14)]
        _, _, model = run(FakeAdo(threads=threads))
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        lines = [line for line in prompt.splitlines() if re.match(r"E\d+: ", line)]
        assert len(lines) == pr_review.MAX_FILE_COMMENTS + pr_review.MAX_GENERAL_COMMENTS == 22


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

    def test_a_template_with_older_and_newer_format_alerts_tells_the_reviewer_the_truth_about_both(self):
        from test_alert_legacy import current, legacy, template
        old = template(legacy(query="KubePodInventory | take 1"), current(window="PT10M"))
        new = template(legacy(query="KubePodInventory | take 2"), current(window="PT30M"))
        _, _, model = run(alert_ado(new=new, old=old))
        prompt = model.calls_of("file")[0]
        assert '"AKS - Restart": log alert (older 2018-04-16 format), severity 2 (Warning), enabled' in prompt
        assert "Action groups: ag-oncall" in prompt and "nobody is notified" not in prompt
        assert '- "AKS - Restart": the query changed' in prompt and '- "AKS - Crash": window size: PT10M -> PT30M.' in prompt

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


class TestTheAuthorsExplanation:
    LONG = "## Description\n\n" + ("Improves alerting. " * 80) + "\n\n**Second check**\n- Skips events newer than 3 minutes. The 3 minute pause lets late log lines arrive.\n- Window changes from PT10M to PT30M.\n"

    def test_checklist_lines_images_and_html_comments_are_taken_out(self):
        text = "Intro.\n\n- [ ] Spell check\n  * [X] Changelog updated\n- [x] [Wiki](https://x.example/y) is updated\n![shot](https://x.example/a.png)\n<!-- template hint -->\nMore words.\n\n\n\nEnd."
        assert clean_description(text) == "Intro.\n\nMore words.\n\nEnd."

    def test_a_description_that_is_only_a_checklist_is_empty(self):
        assert clean_description("- [ ] a\n- [x] b\n") == "" and clean_description(None) == "" and clean_description("") == ""

    def test_what_is_too_long_is_cut_at_the_end_and_says_so(self):
        text = clean_description("word " * 5000, limit=100)
        assert text.endswith("... (the rest of the description is cut)") and len(text) < 160

    def test_the_explanation_reaches_the_reviewer_even_when_it_is_far_into_the_description(self):
        assert self.LONG.index("The 3 minute pause") > 1200  # past the old cut-off
        _, _, model = run(FakeAdo(description=self.LONG))
        assert all("The 3 minute pause lets late log lines arrive." in prompt for prompt in model.calls_of("file"))

    def test_and_the_second_check_sees_it_too(self):
        model = FakePrModel({REPORT: [finding(17)]})
        run(FakeAdo(description=self.LONG), model)
        verify = model.calls_of("verify")[0]
        assert "Why the author made this change" in verify and "The 3 minute pause lets late log lines arrive." in verify and "Pull request title: " not in verify

    def test_the_checklist_is_not_sent_to_the_ai_because_the_code_reads_it(self):
        _, _, model = run()
        prompt = model.calls_of("file")[0]
        assert "Adds a report." in prompt and "Regression results: https://" in prompt
        assert "Changelog updated" not in prompt and "[x]" not in prompt

    def test_the_description_check_uses_the_cleaned_text(self):
        model = FakePrModel(gaps=[])
        run(FakeAdo(description=self.LONG + "\n- [ ] Spell check performed\n"), model)
        sent = model.calls_of("description")[0]
        assert "The 3 minute pause" in sent and "Spell check performed" not in sent


class TestWhatTheAiIsTold:
    def test_the_reviewer_must_show_a_case_not_say_could_and_respect_what_is_intended(self):
        for part in ('"failing_case" (required)', 'do not use "may", "might", "could"', '"evidence" (required)', "copied character for character", "Do not ask the author to verify or confirm",
                     "says a behaviour is intended", "Report each problem once"):
            assert part in pr_review.FILE_SYSTEM
        assert '"failing_case": "the concrete input or situation and the wrong result"' in pr_review.FILE_SYSTEM and '"evidence": "the exact code it relies on"' in pr_review.FILE_SYSTEM

    def test_the_second_check_throws_out_vague_findings_and_intended_behaviour(self):
        for part in ("could, may or might go wrong, without showing a concrete input", "says the behaviour is intended", "duplicate_of", "already_raised_by"):
            assert part in pr_review.VERIFY_SYSTEM

    def test_the_second_check_is_given_the_comments_numbered_like_the_reviewer_was(self):
        ado = FakeAdo(threads=[thread(REPORT, 3, "Guard against empty lists", status="active", author="Alex"), thread(None, None, "Please update the wiki")])
        model = FakePrModel({REPORT: [finding(17)]})
        run(ado, model)
        verify = model.calls_of("verify")[0]
        assert "E1: line 3 [open] Alex: Guard against empty lists" in verify and "E2: (on the pull request as a whole) [resolved] Sam Reviewer: Please update the wiki" in verify


class TestDuplicatesAndAlreadyRaised:
    TWO = {REPORT: [finding(14, "Window is shifted", comment="The window starts 2 minutes late, so a crash in that gap is not matched."), finding(17, "Window is shifted again", comment="Here too the window starts 2 minutes late.")]}

    def comments(self, holds, threads=(), findings=None):
        result, _, _ = run(FakeAdo(threads=list(threads)), FakePrModel(findings or self.TWO, holds=holds))
        return result

    def test_a_finding_that_repeats_an_earlier_one_is_merged_into_it(self):
        result = self.comments(lambda path, numbers: {2: {"duplicate_of": 1}})
        assert [c["title"] for c in result["comments"]] == ["Window is shifted"]
        assert result["comments"][0]["comment"].endswith(" The same applies at line 17.")
        assert any("1 finding(s) repeated another finding" in n for n in result["notes"])
        assert "1 finding: 1 warning." in result["summary"]

    def test_a_repeat_is_not_merged_into_a_finding_that_was_itself_removed(self):
        result = self.comments(lambda path, numbers: {1: (False, "no concrete case"), 2: {"duplicate_of": 1}})
        assert [c["title"] for c in result["comments"]] == ["Window is shifted again"]

    def test_only_an_earlier_finding_can_be_the_original(self):
        result = self.comments(lambda path, numbers: {1: {"duplicate_of": 2}})
        assert len(result["comments"]) == 2

    def test_nonsense_references_are_ignored(self):
        for said in ({2: {"duplicate_of": 2}}, {2: {"duplicate_of": 9}}, {2: {"duplicate_of": "banana"}}, {2: {"duplicate_of": 0}}):
            assert len(self.comments(lambda path, numbers, said=said: said)["comments"]) == 2

    def test_a_finding_an_existing_comment_already_makes_is_marked_whatever_line_it_is_on(self):
        threads = [thread(REPORT, 3, "The window should not be shifted", status="active", author="Alex")]
        result = self.comments(lambda path, numbers: {1: {"already_raised_by": "E1"}}, threads, {REPORT: [finding(17, "Window is shifted")]})
        comment = result["comments"][0]
        assert comment["existing_thread"] == "Already raised by Alex (open)" and comment["existing_status"] == "active"

    def test_a_general_comment_counts_too_and_a_resolved_one_does_not_count_toward_the_verdict(self):
        result = self.comments(lambda path, numbers: {1: {"already_raised_by": "E1"}}, [thread(None, None, "The window is wrong", status="fixed")], {REPORT: [finding(17, "Window is shifted")]})
        assert result["comments"][0]["existing_thread"] == "Already raised by Sam Reviewer (resolved)"
        assert result["verdict"] == "APPROVED"

    def test_a_comment_number_that_does_not_exist_is_ignored(self):
        for said in ("E9", "E0", "banana", 7, None):
            result = self.comments(lambda path, numbers, said=said: {1: {"already_raised_by": said}}, [thread(REPORT, 3, "x")], {REPORT: [finding(17, "Window is shifted")]})
            assert result["comments"][0]["existing_thread"] is None

    def test_a_comment_on_the_same_lines_is_still_a_match_without_the_second_check(self):
        model = FakePrModel({REPORT: [finding(17, "Division by zero")]}, holds=lambda path, numbers: RuntimeError("down"))
        result, _, _ = run(FakeAdo(threads=[thread(REPORT, 16, "Guard against empty lists")]), model)
        assert result["comments"][0]["existing_thread"] == "Already raised by Sam Reviewer (resolved)" and result["comments"][0]["verified"] is None


class TestGuessesAreEnforcedInCode:
    """Asking the model in a prompt not to guess was not enough (a real review gave four hedged findings, all wrong, and the second check agreed
    with them). A finding is now only kept when it shows a concrete case, quotes the code it relies on and states a defect."""

    def removed(self, **over):
        kept, removed = clean_findings([grounded(17, "Division by zero", **over)], view())
        return kept, [reason for _, reason in removed]

    def test_a_finding_that_shows_a_case_and_quotes_the_code_is_kept_with_both(self):
        kept, removed = self.removed(failing_case="average([]) divides by zero and raises ZeroDivisionError.")
        assert removed == [] and kept[0]["failing_case"] == "average([]) divides by zero and raises ZeroDivisionError."
        assert kept[0]["evidence"] == "return sum(values) / len(values)"

    @pytest.mark.parametrize("case", [None, "", "wrong", "It breaks."])
    def test_no_concrete_case(self, case):
        over = {} if case is None else {"failing_case": case}
        kept, reasons = clean_findings([{k: v for k, v in grounded(17, "Division by zero", **over).items() if case is not None or k != "failing_case"}], view())
        assert kept == [] and reasons == [("Division by zero", "it showed no concrete case")]

    @pytest.mark.parametrize("word", ["may", "might", "could", "potentially", "possibly", "perhaps", "probably", "MAY"])
    def test_a_case_that_is_a_guess_is_removed_and_the_word_is_named(self, word):
        kept, reasons = self.removed(failing_case=f"If these two differ in format the join {word} miss some rows.")
        assert kept == [] and reasons == [f"its case was a guess ('{word.lower()}')"]

    def test_hedging_in_the_explanation_alone_does_not_remove_a_finding_that_shows_a_case(self):
        kept, reasons = self.removed(comment="Division by zero: average([]) raises ZeroDivisionError, which may surprise callers. Return 0.0 for an empty list.",
                                     failing_case="average([]) raises ZeroDivisionError instead of returning a value.")
        assert reasons == [] and len(kept) == 1

    @pytest.mark.parametrize("ask", ["Verify that the values are normalized consistently.", "Please confirm whether this is needed.", "Confirm that this change aligns with the plan.",
                                     "Double-check the window.", "Make sure that this is right.", "Is this intended?", "Please verify the result."])
    def test_a_finding_that_asks_the_author_to_confirm_something_is_removed(self, ask):
        kept, reasons = self.removed(comment=f"average([]) raises ZeroDivisionError. {ask}")
        assert kept == [] and reasons == ["it asked the author to confirm something instead of showing a defect"]

    def test_the_title_counts_too(self):
        kept, removed = clean_findings([grounded(17, "Verify that the window is right")], view())
        assert kept == [] and removed[0][1].startswith("it asked the author")

    def test_a_plain_recommendation_is_not_a_request_to_confirm(self):
        kept, reasons = self.removed(comment="average([]) raises ZeroDivisionError. Ensure len(values) > 0 before dividing, or return 0.0.")
        assert reasons == [] and len(kept) == 1

    def test_no_evidence_or_too_little_of_it(self):
        for evidence in ("", "   ", "x = 1", None):
            kept, removed = clean_findings([{**grounded(17, "Division by zero"), "evidence": evidence}], view())
            assert kept == [] and removed == [("Division by zero", "it did not quote the code it relies on")], evidence

    def test_code_that_is_not_in_the_file_is_removed(self):
        kept, reasons = self.removed(evidence="return statistics.mean(values)")
        assert kept == [] and reasons == ["the code it quoted is not in the file"]

    @pytest.mark.parametrize("evidence", [
        "+    17 |     return sum(values) / len(values)",          # copied with the line number and mark of the diff view
        "return   sum(values)  /  len(values)",                    # spacing differs
        "def average(values): ... return sum(values) / len(values)",  # pieces
        ["def average(values):", "return sum(values) / len(values)"],  # a list of pieces
        "-       | def load(path):",                               # code the change removed is in the view too
    ])
    def test_quotes_that_are_in_the_file_are_accepted(self, evidence):
        kept, reasons = self.removed(evidence=evidence)
        assert reasons == [] and len(kept) == 1

    def test_one_piece_that_is_missing_removes_the_finding(self):
        kept, reasons = self.removed(evidence="def average(values): ... return statistics.mean(values)")
        assert kept == [] and reasons == ["the code it quoted is not in the file"]

    def test_a_quote_from_the_alert_details_counts_as_being_in_the_file(self):
        alert_view = build_view("a.json", "ARM template", "add", "", '{"query": "T | where X == 1"}\n')
        alert_view.extra = "Query:\n   T\n   | where Status == \"failed\"\n   | summarize Count = count()"
        kept, _ = clean_findings([{**grounded(1, "Wrong filter"), "evidence": '| where Status == "failed"\n| summarize Count = count()'}], alert_view)
        assert len(kept) == 1

    def test_the_order_of_the_checks_reports_lines_that_were_not_changed_first(self):
        kept, removed = clean_findings([{**grounded(12, "Old code"), "failing_case": ""}], view())
        assert removed == [("Old code", "it pointed at lines this pull request did not change")]

    @pytest.mark.parametrize("reason,group", [
        ("it pointed at lines this pull request did not change", "pointed at lines this pull request did not change"),
        ("it did not hold on a second check: no case", "did not hold on a second check"),
        ("it repeats another finding", "repeated another finding"),
        ("it showed no concrete case", "showed no concrete case"),
        ("its case was a guess ('may')", "only guessed at a case"),
        ("it asked the author to confirm something instead of showing a defect", "asked the author to confirm something instead of showing a defect"),
        ("it did not quote the code it relies on", "relied on code that is not in the file"),
        ("the code it quoted is not in the file", "relied on code that is not in the file"),
        ("it had no explanation", "were malformed"),
    ])
    def test_every_reason_belongs_to_a_group_in_the_notes(self, reason, group):
        assert pr_review.removal_group(reason) == group


class TestWhatTheReviewerSeesOfTheGuesses:
    # the shape of the four findings a real review gave: hedged, asking for confirmation, or a definite claim the code contradicts
    HEDGED = [
        finding(14, "Potential mismatch in the join keys", comment="If these differ in format, the join may miss matches. Verify that both sides are normalized the same way.",
                failing_case="If these differ in casing or format, the join may miss matches."),
        finding(15, "Time window mismatch", comment="This may cause rows to be missed. Confirm that the window aligns with the schedule.",
                failing_case="Rows outside this range may be missed."),
        finding(16, "Larger window may delay alerting", comment="This may delay alerting by up to the window.", failing_case="The alert could fire up to 30 minutes late."),
    ]
    GOOD = finding(17, "average() fails on an empty list", comment="average([]) divides by zero and raises ZeroDivisionError. Return 0.0 or raise a clear error.",
                   failing_case="average([]) divides by zero and raises ZeroDivisionError.")

    def review(self, findings):
        return run(model=FakePrModel({REPORT: findings}))

    def test_the_guesses_are_not_shown_and_the_grounded_finding_stays(self):
        result, _, _ = self.review([*self.HEDGED, self.GOOD])
        assert [c["title"] for c in result["comments"]] == ["average() fails on an empty list"]
        assert "1 finding: 1 warning." in result["summary"]

    def test_the_notes_say_what_was_dropped_and_why_so_it_can_be_checked(self):
        result, _, _ = self.review([*self.HEDGED, self.GOOD])
        notes = " | ".join(result["notes"])
        assert "3 finding(s) only guessed at a case" in notes or ("only guessed at a case" in notes and "asked the author" in notes)
        assert "Removed as a guess: scripts/report.py: Potential mismatch in the join keys (its case was a guess ('may'))" in result["notes"]
        assert "Removed as a guess: scripts/report.py: Larger window may delay alerting (its case was a guess ('could'))" in result["notes"]

    def test_a_file_where_every_finding_was_a_guess_is_not_sent_to_the_second_check(self):
        result, _, model = self.review(self.HEDGED)
        assert result["comments"] == [] and model.calls_of("verify") == []
        assert result["verdict"] == "APPROVED" and "No findings in the files reviewed." in result["summary"]

    def test_at_most_six_are_listed_and_the_rest_are_counted(self):
        many = [finding(14 + n % 4, f"Guess {n}", failing_case="The join may miss rows in some cases.") for n in range(9)]
        result, _, _ = self.review(many)
        assert sum(1 for n in result["notes"] if n.startswith("Removed as a guess:")) == 6
        assert "3 more findings were removed as guesses." in result["notes"]

    def test_a_kept_finding_carries_its_case_and_its_quote(self):
        result, _, _ = self.review([self.GOOD])
        comment = result["comments"][0]
        assert comment["failing_case"] == "average([]) divides by zero and raises ZeroDivisionError." and comment["evidence"] == "return sum(values) / len(values)"

    def test_the_second_check_is_given_the_case_and_the_quote_to_trace(self):
        _, _, model = self.review([self.GOOD])
        verify = model.calls_of("verify")[0]
        assert "Its case: average([]) divides by zero and raises ZeroDivisionError." in verify
        assert "The code it relies on: return sum(values) / len(values)" in verify
        assert "Trace the case through the code yourself" in pr_review.VERIFY_SYSTEM


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

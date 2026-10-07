"""The process around the AI: the hostile second look, the gates, repeats between code and AI, notes about the description, alert timing and SQL guidance.

All the code, names and settings in this file are made up.
"""
from __future__ import annotations

import pytest

from app.services import pr_lookup, pr_review
from app.services.alert_facts import duration_minutes
from app.services.pr_arm import arm_context, timing_facts
from app.services.pr_diff import build_view
from app.services.pr_review import PullRequestReviewService, clean_findings, refute_findings
from irp_support import FIXTURES
from pr_support import PY_NEW, PY_OLD, FakeAdo, FakePrModel, change, finding
from test_pr_review_checks import OPTIONS_PATH, RENAME_CASE, cs_pr, rename_finding

REPORT = "scripts/report.py"
LINE = "return sum(values) / len(values)"  # line 17 of the report script: a line this pull request changed


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)


def run(ado=None, model=None):
    ado, model = ado or FakeAdo(), model or FakePrModel()
    return PullRequestReviewService(ado, model).review("proj", "repo", 7), ado, model


def view():
    return build_view(REPORT, "Python", "edit", PY_OLD, PY_NEW)


class TestFindingsThatAdmitTheyHaveNoCase:
    @pytest.mark.parametrize("case", [
        "No failing case, but the code is unnecessarily verbose and harder to read.", "There is no failing case here, it is only a style matter.", "None. It is a matter of taste.",
        "N/A", "No concrete case; it reads badly.", "no specific scenario applies but it is untidy", "Not applicable to a real input today.", "There is no real example of it going wrong.",
    ])
    def test_a_case_that_says_there_is_none_is_removed(self, case):
        kept, removed = clean_findings([finding(17, "Verbose", failing_case=case.ljust(25, "."), evidence=LINE)], view())
        assert kept == [] and removed == [("Verbose", "it showed no concrete case")]

    def test_a_real_case_that_uses_the_word_no_is_kept(self):
        case = "For an empty list the function divides by zero and no value is returned to the caller."
        kept, _ = clean_findings([finding(17, "Zero", failing_case=case, evidence=LINE)], view())
        assert len(kept) == 1

    def test_the_prompt_tells_the_ai_not_to_write_it(self):
        assert "Never write that there is no failing case" in pr_review.FILE_SYSTEM


class TestTheHostileSecondLook:
    def refuted(self, said, **kw):
        return run(model=FakePrModel({REPORT: [finding(17, "Division by zero")]}, refutes={REPORT: said}, **kw))

    def test_a_finding_is_removed_when_the_ai_quotes_code_that_shows_it_is_wrong(self):
        result, _, _ = self.refuted({1: ("the caller never passes an empty list", LINE)})
        assert result["comments"] == []
        assert "Removed on a second check: scripts/report.py: Division by zero (the caller never passes an empty list)" in result["notes"]
        assert any("1 finding(s) were contradicted by code the second check quoted" in n for n in result["notes"])

    @pytest.mark.parametrize("quote", ["code that is not in the file at all", "", "ab"])
    def test_an_opinion_or_a_quote_that_is_not_in_the_file_removes_nothing(self, quote):
        result, _, _ = self.refuted({1: ("it is wrong because I say so", quote)})
        assert len(result["comments"]) == 1 and result["comments"][0]["verified"] is True

    def test_a_reason_is_needed_as_well_as_the_quote(self):
        result, _, _ = self.refuted({1: ("", LINE)})
        assert len(result["comments"]) == 1

    def test_the_description_cannot_be_the_proof_because_it_says_what_the_author_meant(self):
        description_quote = "Regression results: https://dev.azure.com/org/proj/_build/results?buildId=100"
        result, _, _ = self.refuted({1: ("the author says it is covered", description_quote)})
        assert len(result["comments"]) == 1

    def test_a_comment_in_the_code_cannot_be_the_proof_either(self):
        # a real review lost a true finding because a header comment said the behaviour was "deliberately kept in lockstep"
        text = PY_NEW + "# the caller never passes an empty list, so this is deliberate\n"
        ado = FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": text, "old-/scripts/report.py": PY_OLD})
        comment_quote = "the caller never passes an empty list, so this is deliberate"
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}, refutes={REPORT: {1: ("a comment says it is deliberate", comment_quote)}}))
        assert len(result["comments"]) == 1
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero")]}, refutes={REPORT: {1: ("only non-empty lists are passed", LINE)}}))
        assert result["comments"] == []  # code that makes the case impossible still removes it

    def test_a_trailing_comment_does_not_make_the_code_before_it_unquotable(self):
        text = PY_NEW.replace(LINE, LINE + "  # callers pass non-empty lists")
        ado = FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": text, "old-/scripts/report.py": PY_OLD})
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(17, "Division by zero", evidence=LINE)]}, refutes={REPORT: {1: ("the code guards it", LINE)}}))
        assert result["comments"] == []

    def test_the_facts_worked_out_in_code_can_be_the_proof(self):
        from test_pr_review_checks import CS_PATH, cs_finding
        result, _, _ = run(cs_pr(), FakePrModel({CS_PATH: [cs_finding()]}, refutes={CS_PATH: {1: ("the project is C# 12", "targets net8.0 (C# 12)")}}))
        assert result["comments"] == []

    def test_in_a_document_every_line_counts_because_prose_has_no_comments(self):
        ado = FakeAdo(changes=[change("/docs/guide.md", "add")], blobs={"new-/docs/guide.md": "# Title\n\nSome text that is wrong.\n"})
        said = {"docs/guide.md": [finding(3, "Wrong text", evidence="Some text that is wrong.")]}
        refuted = run(ado, FakePrModel(said, refutes={"docs/guide.md": {1: ("the heading says otherwise", "# Title")}}))[0]
        assert refuted["comments"] == []

    @pytest.mark.parametrize("line", ["-- a SQL comment", "  // a C# comment", "# a Python or PowerShell comment", "/* opens", " * inside a block", "<!-- html -->", "'''docstring", '"""docstring'])
    def test_what_counts_as_a_comment_line(self, line):
        assert pr_review._is_comment(line)

    @pytest.mark.parametrize("line", ["x = 1  # trailing comment", "SELECT 1 -- trailing", "return a / b", "    value = 'hello'", ""])
    def test_a_line_of_code_is_not_a_comment_line(self, line):
        assert not pr_review._is_comment(line)

    def test_what_a_lookup_returned_can_be_quoted(self):
        ado = cs_pr()
        lookups = {OPTIONS_PATH: [("search_code", {"text": "PollSeconds"})]}
        findings = {OPTIONS_PATH: [rename_finding()]}
        kept = run(ado, FakePrModel(findings, lookups=lookups, decide=lambda p, n, r: {1: True}, refutes={OPTIONS_PATH: {1: ("the old name is no longer used", "no line contains 'PollSeconds'")}}))[0]
        removed = run(cs_pr(settings='{"Widgets": {"RefreshSeconds": 60}}'), FakePrModel(findings, lookups=lookups, decide=lambda p, n, r: {1: True}, refutes={OPTIONS_PATH: {1: ("the old name is no longer used", "no line contains 'PollSeconds'")}}))[0]
        # in the first run the old name is still used, so the search found it and the quote is not in anything the AI was shown
        assert len(kept["comments"]) == 1
        assert removed["comments"] == []

    def test_a_refutation_that_fails_keeps_the_findings(self):
        result, _, _ = run(model=FakePrModel({REPORT: [finding(17, "Division by zero")]}, refutes={REPORT: RuntimeError("down")}))
        assert len(result["comments"]) == 1

    def test_it_runs_once_for_each_file_with_findings_and_is_told_the_case_and_the_facts(self):
        _, _, model = run(model=FakePrModel({REPORT: [finding(17, "Division by zero")]}))
        asked = model.calls_of("refute")
        assert len(asked) == 1 and asked[0].startswith(f"File: {REPORT}")
        assert "Findings to try to prove wrong:" in asked[0] and "Its case: " in asked[0] and "Today's date:" in asked[0] and "Adds a report." in asked[0]

    def test_it_is_not_called_when_no_finding_is_left(self):
        _, _, model = run()
        assert model.calls_of("refute") == []
        _, _, model = run(model=FakePrModel({REPORT: [finding(17, "Division by zero")]}, holds=lambda path, numbers: {1: False}))
        assert model.calls_of("refute") == []

    def test_a_code_finding_is_never_refuted(self):
        ado = FakeAdo(changes=[change("/tools/x.ps1", "add")], blobs={"new-/tools/x.ps1": "$status = Get-Status\nWrite-Output 'x'\n"})
        result, _, model = run(ado, FakePrModel())
        assert len(result["comments"]) == 1 and model.calls_of("refute") == []

    def test_the_prompt_makes_the_ai_argue_from_the_code(self):
        for part in ("assume it is WRONG", "how the rest of the file handles the same thing", "Argue from the code, never from opinion", "never use one of them as the reason a finding is wrong",
                     "shows what the author INTENDED, not what the code does", "quote code (or a lookup result) that makes its concrete case impossible", "wrong is false"):
            assert part in pr_review.REFUTE_SYSTEM

    def test_the_second_look_is_offered_the_lookup_tools_when_there_is_a_repository_to_read(self):
        seen = []
        original = pr_review.chat_json_with_tools
        pr_review.chat_json_with_tools = lambda model, system, user, tools, run_tool, **kw: seen.append(system.split("\n")[0]) or original(model, system, user, tools, run_tool, **kw)
        try:
            run(cs_pr(), FakePrModel({OPTIONS_PATH: [finding(3, "Setting has no default", failing_case="RefreshSeconds is 0 when the value is missing, so the window is empty.", evidence="public int RefreshSeconds { get; set; }")]}))
        finally:
            pr_review.chat_json_with_tools = original
        assert any(line.startswith("You are a sceptical senior engineer") for line in seen) and any(line.startswith("You check findings") for line in seen)

    def test_findings_can_be_refuted_directly(self):
        class Model(FakePrModel):
            pass

        model = Model(refutes={REPORT: {2: ("not so", LINE)}})
        findings = [{"title": "a", "line_number": 17, "end_line": None, "comment": "x", "failing_case": "y" * 25, "evidence": LINE, "suggestion_code": None},
                    {"title": "b", "line_number": 17, "end_line": None, "comment": "x", "failing_case": "y" * 25, "evidence": LINE, "suggestion_code": None}]
        kept, removed = refute_findings(model, view(), findings, {"title": "t", "description": "d"})
        assert [f["title"] for f in kept] == ["a"] and removed[0][0] == "b"


class TestARepeatOfACodeFinding:
    def ado(self):
        return FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": PY_NEW.replace("import json", "import json\nimport os"), "old-/scripts/report.py": PY_OLD})

    def test_the_second_check_is_told_what_the_code_already_found(self):
        _, _, model = run(self.ado(), FakePrModel({REPORT: [finding(2, "Unused import os")]}))
        assert "Findings already made by exact checks in code:\nS1: line 2: os is imported and never used" in model.calls_of("verify")[0]
        assert "already_found_by_code" in pr_review.VERIFY_SYSTEM

    def test_an_ai_finding_that_is_the_same_defect_is_dropped_and_the_code_one_stays(self):
        result, _, _ = run(self.ado(), FakePrModel({REPORT: [finding(2, "Unused import os")]}, holds=lambda path, numbers: {1: {"already_found_by_code": "S1"}}))
        assert [(c["title"], c["source"]) for c in result["comments"]] == [("os is imported and never used", "static")]
        assert any("1 finding(s) repeated a finding made by an exact check in code" in n for n in result["notes"])

    @pytest.mark.parametrize("said", [None, "S0", "S9", "banana"])
    def test_a_nonsense_reference_drops_nothing(self, said):
        result, _, _ = run(self.ado(), FakePrModel({REPORT: [finding(2, "Unused import os")]}, holds=lambda path, numbers: {1: {"already_found_by_code": said}}))
        assert len(result["comments"]) == 2

    def test_with_no_code_finding_the_second_check_is_not_told_about_any(self):
        _, _, model = run(model=FakePrModel({REPORT: [finding(17)]}))
        assert "Findings already made by exact checks" not in model.calls_of("verify")[0]


class TestNotesAboutTheDescription:
    DESCRIPTION = "Adds a report script with an average helper.\n\n- [x] Changelog updated\n"

    def gaps(self, said):
        result, _, model = run(FakeAdo(description=self.DESCRIPTION), FakePrModel(gaps=said))
        return result["clarifications"], model

    def test_a_change_the_description_covers_is_dropped_when_the_ai_quotes_the_sentence(self):
        notes, _ = self.gaps([{"change": "a quantum flux capacitor was introduced", "description_mentions": "Adds a report script with an average helper."}])
        assert notes == []

    @pytest.mark.parametrize("mention", [None, "", "A sentence the description does not contain at all."])
    def test_without_a_real_quote_the_note_stays(self, mention):
        notes, _ = self.gaps([{"change": "a quantum flux capacitor was introduced", "description_mentions": mention}])
        assert notes == ["The description does not mention: a quantum flux capacitor was introduced"]

    def test_plain_text_notes_still_work(self):
        notes, _ = self.gaps(["a quantum flux capacitor was introduced"])
        assert notes == ["The description does not mention: a quantum flux capacitor was introduced"]

    def test_the_prompt_asks_for_the_covering_sentence_and_counts_a_rename_with_its_references(self):
        assert "description_mentions" in pr_review.DESCRIPTION_SYSTEM and "a rename of a file also covers the references that were updated for it" in pr_review.DESCRIPTION_SYSTEM


class TestWhatTheNotesSayAboutTheWork:
    def test_how_many_findings_the_ai_proposed_and_how_many_survived(self):
        guess = finding(14, "A guess", failing_case="It may fail for some input and then it breaks.")
        result, _, _ = run(model=FakePrModel({REPORT: [finding(17, "Division by zero"), guess]}))
        assert result["notes"][0] == "The AI proposed 2 findings in 3 files; 1 was removed by the rules or the checks; 1 from the AI and 0 from exact checks in code is shown."

    def test_a_clean_review_has_no_such_line(self):
        result, _, _ = run()
        assert not any(n.startswith("The AI proposed") for n in result["notes"])

    def test_a_quote_shown_with_a_finding_is_short_but_was_checked_whole(self):
        long_line = "value = '" + "ab" * 350 + "'"
        long_view = build_view("a.py", "Python", "add", "", long_line + "\n")
        kept, removed = clean_findings([finding(1, "Long", failing_case="x" * 25, evidence=long_line)], long_view)
        assert removed == [] and len(kept[0]["evidence"]) <= pr_review.EVIDENCE_SHOWN_CHARS and kept[0]["evidence"].endswith("…")
        kept, removed = clean_findings([finding(1, "Long", failing_case="x" * 25, evidence=long_line + "tail that is not in the file")], long_view)
        assert kept == [] and removed[0][1] == "the code it quoted is not in the file"

    def test_a_line_cut_in_a_lookup_says_so(self):
        reader = pr_lookup.RepoReader(FakeAdo(repo_files={"a.json": "x" * 2000 + "\nshort\n"}), "p", "r", "c" * 40)
        text = reader.read_lines("a.json")
        assert "(line cut at 1500 characters)" in text and "short" in text and text.count("x") == 1500


class TestAlertTimingFacts:
    def alert(self, query, frequency="PT5M", window="PT30M", **over):
        return {"evaluation_frequency": frequency, "window_size": window, "query": query, "condition": {"failing_periods": None}, "override_query_time_range": None, **over}

    def text(self, **kw):
        return "\n".join(timing_facts(self.alert(**kw)))

    def test_a_filter_the_alert_sees_on_several_runs(self):
        text = self.text(query="T | where a > ago(10m) or b > ago(5m)")
        assert "the alert runs every 5 minutes and each run reads the last 30 minutes of data. The query has time filters ago(5 minutes), ago(10 minutes)." in text
        assert "ago(10 minutes) is not shorter than the time between runs: an event passes it on about 2.0 runs, so at least one run sees it." in text
        assert "ago(5 minutes) is not shorter than the time between runs: an event passes it on about 1.0 runs" in text
        assert "An event that is outside this filter on a later run was already seen by an earlier run." in text

    def test_a_filter_shorter_than_the_time_between_runs_can_skip_events(self):
        assert "ago(2 minutes) is shorter than the 5 minutes between runs: an event can fall between two runs and never pass this filter." in self.text(query="T | where a > ago(2m)")

    def test_a_filter_longer_than_what_a_run_reads_is_cut_by_the_window(self):
        assert "ago(1 hour) is longer than what a run reads: a run never sees further back than 30 minutes." in self.text(query="T | where a > ago(1h)")

    def test_failing_periods_widen_what_a_run_reads(self):
        text = self.text(query="T | where a > ago(1h)", condition={"failing_periods": {"evaluation_periods": 4, "min_failing": 2}})
        assert "reads the last 2 hours of data" in text and "is not shorter than the time between runs" in text

    def test_an_override_of_the_query_time_range_is_what_a_run_reads(self):
        text = self.text(query="T | where a > ago(1h)", override_query_time_range="PT3H")
        assert "reads the last 3 hours of data (the rule sets overrideQueryTimeRange)" in text

    @pytest.mark.parametrize("kwargs", [
        {"query": "T | where a > 5"}, {"query": ""}, {"query": "T | where a > ago(5m)", "frequency": None}, {"query": "T | where a > ago(5m)", "window": "not a duration"},
    ])
    def test_no_filter_or_no_timing_means_no_facts(self, kwargs):
        assert timing_facts(self.alert(**kwargs)) == []

    def test_units_are_understood(self):
        text = self.text(query="T | where a > ago(30s) or b > ago(1d)", frequency="PT1M", window="P2D")
        assert "ago(30 seconds) is shorter than the 1 minute between runs" in text and "ago(1 day) is not shorter" in text

    def test_durations(self):
        assert [duration_minutes(v) for v in ("PT5M", "PT1H30M", "P1D", "PT30S", "PT0M", "x", None, "")] == [5.0, 90.0, 1440.0, 0.5, 0.0, None, None, None]
        assert timing_facts({"evaluation_frequency": "PT0M", "window_size": "PT5M", "query": "T | where a > ago(1m)", "condition": {}}) == []  # a zero interval is no timing

    def test_the_alert_in_words_carries_the_facts_so_every_call_sees_them(self):
        text = arm_context(None, (FIXTURES / "vpn_log_alert.arm.json").read_text(encoding="utf-8"))
        assert "Timing facts (worked out from the template, not guesses): the alert runs every 5 minutes and each run reads the last 10 minutes of data." in text
        assert "ago(10 minutes) is not shorter than the time between runs" in text

    def test_the_guidance_no_longer_invites_the_mistake_and_says_what_is_normal(self):
        guide = pr_review.ARM_GUIDE
        assert "shorter or longer than the window" not in guide
        assert "A time filter that is shorter than the window is normal" in guide and "was already seen by an earlier run" in guide and "Use the timing facts you are given" in guide
        assert "shorter than the time between runs can skip events" in guide


class TestSqlAndTheFilesOwnConvention:
    def test_sql_has_its_own_guidance_that_says_to_follow_the_querys_labels(self):
        assert pr_review.GUIDES["SQL"] is pr_review.SQL_GUIDE
        assert "find how the rest of the query labels the same thing and follow that convention" in pr_review.SQL_GUIDE and "UPDATE or DELETE without a WHERE" in pr_review.SQL_GUIDE

    def test_every_language_is_told_to_follow_the_files_own_convention_and_not_to_review_moved_code(self):
        assert "follow the file's own convention" in pr_review.FILE_SYSTEM
        assert "only moved, renamed or brought into the repository and its logic is unchanged, do not report problems in that logic" in pr_review.FILE_SYSTEM

    def test_a_sql_file_gets_the_sql_guidance(self):
        ado = FakeAdo(changes=[change("/db/p.sql", "add")], blobs={"new-/db/p.sql": "SELECT 1 AS a;\n"})
        _, _, model = run(ado)
        assert "SQL: look for these when the changed code has them" in model.calls[0][0]

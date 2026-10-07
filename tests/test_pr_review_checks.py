"""What the review learned from real pull requests: stricter gates, lookups in the repository, exact checks made in code, less noise, progress.

All the code, names and settings in this file are made up.
"""
from __future__ import annotations

import pytest

from app.services import pr_review
from app.services.pr_diff import build_view
from app.services.pr_review import PullRequestReviewService, ReviewFailed, clean_findings
from pr_support import CSPROJ, PY_NEW, PY_OLD, SILENT, FakeAdo, FakePrModel, change, decoded, finding, thread

REPORT = "scripts/report.py"
CS_PATH = "src/Api/Models/Counts.cs"
CS_OLD = "namespace Demo.Api.Models;\n\npublic class Counts\n{\n    public int Total { get; set; }\n}\n"
CS_NEW = "namespace Demo.Api.Models;\n\npublic class Counts\n{\n    public int Total { get; set; }\n    public List<int> Items { get; set; } = [];\n}\n"
CS_LINE = "public List<int> Items { get; set; } = [];"
OPTIONS_PATH = "src/Api/RefreshOptions.cs"
OPTIONS_OLD = "public class RefreshOptions\n{\n    public int PollSeconds { get; set; }\n}\n"
OPTIONS_NEW = "public class RefreshOptions\n{\n    public int RefreshSeconds { get; set; }\n}\n"
SETTINGS_OLD_NAME = '{\n  "Refresh": {\n    "PollSeconds": 60\n  }\n}\n'
SETTINGS_NEW_NAME = '{\n  "Refresh": {\n    "RefreshSeconds": 60\n  }\n}\n'
RENAME_CASE = "If appsettings.json still uses the old name PollSeconds, the value is never bound and the default is used."


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)


def run(ado=None, model=None):
    ado, model = ado or FakeAdo(), model or FakePrModel()
    return PullRequestReviewService(ado, model).review("proj", "repo", 7), ado, model


def by_path(result):
    return {f["path"]: f for f in result["files"]}


def cs_view():
    return build_view(CS_PATH, "C#", "edit", CS_OLD, CS_NEW)


def cs_finding(**over):
    base = {"line": 6, "end_line": None, "category": "correctness", "severity": "warning", "title": "Unsafe list default", "comment": "The list is shared between instances and mutated by callers.",
            "failing_case": "Two Counts objects added to the same response share one list, so one caller's Add changes the other's data.", "evidence": CS_LINE, "suggestion_code": None,
            "trace": "Items is created once for each Counts object, but the caller copies the reference, so both objects point at one list and an Add shows in both."}
    base.update(over)
    return base


def cs_pr(tfm="net8.0", settings=SETTINGS_OLD_NAME):
    """A pull request that renames a setting in an options class; the rest of the repository is in `repo_files`."""
    repo = {"src/Api/Api.csproj": CSPROJ.format(tfm=tfm), "src/Api/appsettings.json": settings, OPTIONS_PATH: OPTIONS_NEW}
    return FakeAdo(changes=[change("/" + OPTIONS_PATH), change("/" + CS_PATH)],
                   blobs={f"new-/{OPTIONS_PATH}": OPTIONS_NEW, f"old-/{OPTIONS_PATH}": OPTIONS_OLD, f"new-/{CS_PATH}": CS_NEW, f"old-/{CS_PATH}": CS_OLD},
                   description="Renames the refresh setting.", repo_files=repo)


def rename_finding(**over):
    return finding(3, "The renamed setting is not bound", comment="The property was renamed, so a configuration that still uses the old name is ignored.", failing_case=RENAME_CASE,
                   evidence="public int RefreshSeconds { get; set; }", **over)


def no_default_finding():
    return finding(3, "Setting has no default", failing_case="RefreshSeconds is 0 when the value is missing, so the refresh window is empty.", evidence="public int RefreshSeconds { get; set; }")


class TestGatesLearnedFromRealPullRequests:
    @pytest.mark.parametrize("text", [
        "This will not compile on older SDKs.", "It doesn't compile.", "That is a syntax error.", "Invalid C# syntax here.", "The compiler reports CS1002.",
        "It fails to compile.", "A compilation error follows.", "A compile error at build time.", "This is not valid C#.", "The code would not compile.", "That is invalid syntax.",
    ])
    @pytest.mark.parametrize("field", ["comment", "failing_case", "title"])
    def test_a_claim_that_the_code_does_not_compile_is_removed_because_only_the_build_can_show_it(self, text, field):
        over = {field: f"The build stops: {text}" if field == "failing_case" else text}
        kept, removed = clean_findings([cs_finding(**over)], cs_view())
        assert kept == [] and removed == [(over.get("title", "Unsafe list default"), "it claimed a compile or syntax error, which only the build can show")]

    def test_the_word_compile_in_another_sense_is_not_a_compile_claim(self):
        kept, _ = clean_findings([cs_finding(comment="The pattern is compiled on every call; compile it once, outside the loop.",
                                             failing_case="Each request builds the regular expression again, so 1,000 requests compile it 1,000 times.")], cs_view())
        assert len(kept) == 1

    def test_a_finding_that_quotes_only_code_the_pull_request_did_not_change_is_removed(self):
        kept, removed = clean_findings([cs_finding(evidence="public int Total { get; set; }")], cs_view())  # line 5 is old
        assert kept == [] and removed == [("Unsafe list default", "all the code it quoted is unchanged context")]

    def test_it_is_enough_that_one_quoted_piece_is_a_changed_line(self):
        kept, _ = clean_findings([cs_finding(evidence="public int Total { get; set; } ... public List<int> Items")], cs_view())
        assert len(kept) == 1

    def test_a_line_the_pull_request_removed_counts_as_changed(self):
        gone = build_view("a.py", "Python", "edit", "first line\nsecond line\nthird line\n", "first line\nthird line\n")
        kept, _ = clean_findings([finding(2, evidence="second line")], gone)
        assert len(kept) == 1
        kept, removed = clean_findings([finding(2, evidence="first line")], gone)
        assert kept == [] and removed[0][1] == "all the code it quoted is unchanged context"

    @staticmethod
    def two_changes_far_apart():
        """A 30-line file where the pull request adds line 3 and line 24 and nothing else."""
        old = [f"value_{n} = {n}" for n in range(1, 29)]
        new = old[:2] + ["first_added = compute(1)"] + old[2:22] + ["second_added = compute(2)"] + old[22:]
        return build_view("calc.py", "Python", "edit", "\n".join(old) + "\n", "\n".join(new) + "\n")

    def test_a_finding_that_quotes_changed_code_from_somewhere_else_than_it_points_at_is_removed(self):
        view = self.two_changes_far_apart()
        assert view.new_lines[2] == "first_added = compute(1)" and view.new_lines[23] == "second_added = compute(2)"
        kept, removed = clean_findings([finding(3, evidence="second_added = compute(2)")], view)  # real code, changed, but 21 lines from line 3
        assert kept == [] and removed == [("Problem", "the code it quoted is not where it pointed")]

    def test_the_quoted_code_may_be_a_few_lines_from_the_line_it_points_at(self):
        old = [f"value_{n} = {n}" for n in range(1, 21)]
        new = old[:2] + ["first_added = compute(1)"] + old[2:6] + ["near_added = compute(2)"] + old[6:8] + ["far_added = compute(3)"] + old[8:]
        view = build_view("calc.py", "Python", "edit", "\n".join(old) + "\n", "\n".join(new) + "\n")
        assert [view.new_lines[i] for i in (2, 7, 10)] == ["first_added = compute(1)", "near_added = compute(2)", "far_added = compute(3)"]
        assert clean_findings([finding(8, evidence="first_added = compute(1)")], view)[0]  # five lines from line 3: near enough
        kept, removed = clean_findings([finding(11, evidence="first_added = compute(1)")], view)  # eight lines from line 3
        assert kept == [] and removed == [("Problem", "the code it quoted is not where it pointed")]

    def test_one_quoted_piece_near_the_line_is_enough(self):
        kept, _ = clean_findings([finding(3, evidence="first_added = compute(1) ... second_added = compute(2)")], self.two_changes_far_apart())
        assert len(kept) == 1

    def test_removed_code_is_as_near_as_the_line_that_follows_it(self):
        old = "".join(f"step_{n}()\n" for n in range(1, 31))
        new = "".join(f"step_{n}()\n" for n in range(1, 31) if n not in (4, 5, 6))
        view = build_view("flow.py", "Python", "edit", old, new)
        assert view.removed_at == {4}
        assert clean_findings([finding(4, evidence="step_5()")], view)[0]  # the removed code is shown just before line 4
        far = build_view("flow.py", "Python", "edit", old, "".join(f"step_{n}()\n" for n in range(1, 31) if n not in (4, 25)))
        kept, removed = clean_findings([finding(4, evidence="step_25()")], far)
        assert kept == [] and removed == [("Problem", "the code it quoted is not where it pointed")]

    def test_the_new_reasons_are_grouped_for_the_notes(self):
        compile_reason, unchanged_reason = "it claimed a compile or syntax error, which only the build can show", "all the code it quoted is unchanged context"
        assert pr_review.removal_group(compile_reason) == "claimed a compile or syntax error, which only the build can show"
        assert pr_review.removal_group(unchanged_reason) == "quoted only code this pull request did not change"
        assert pr_review.removal_group(pr_review.NEEDS_LOOKUP) == "depended on code outside the file that no lookup confirmed"
        assert {pr_review.removal_group(r) for r in (compile_reason, unchanged_reason, pr_review.NEEDS_LOOKUP)} <= pr_review.GUESS_GROUPS

    @pytest.mark.parametrize("category", ["maintainability", "test_coverage"])
    @pytest.mark.parametrize("severity", ["warning", "critical"])
    def test_naming_structure_style_and_missing_tests_are_never_more_than_a_suggestion(self, category, severity):
        kept, _ = clean_findings([cs_finding(category=category, severity=severity)], cs_view())
        assert kept[0]["severity"] == "suggestion" and kept[0]["category"] == category

    @pytest.mark.parametrize("title", [
        "Header comment last modified date is earlier than created date", "New function missing docstring", "Missing comment-based help for new function", "Missing return type annotation for load",
    ])
    def test_a_documentation_fault_is_a_suggestion_even_when_the_ai_calls_it_a_warning(self, title):
        kept, _ = clean_findings([cs_finding(title=title, category="correctness", severity="warning")], cs_view())
        assert (kept[0]["category"], kept[0]["severity"]) == ("maintainability", "suggestion")

    def test_a_title_that_only_mentions_a_comment_in_passing_keeps_its_category(self):
        kept, _ = clean_findings([cs_finding(title="Retry loop never ends when the comment field is empty", severity="warning")], cs_view())
        assert (kept[0]["category"], kept[0]["severity"]) == ("correctness", "warning")

    @pytest.mark.parametrize("category", ["correctness", "security", "performance"])
    def test_the_other_categories_keep_their_severity(self, category):
        kept, _ = clean_findings([cs_finding(category=category, severity="critical")], cs_view())
        assert kept[0]["severity"] == "critical"

    @pytest.mark.parametrize("case", [
        "If the setting is not renamed elsewhere, the binder finds nothing.", "If appsettings.json still uses the old name, binding fails.", "If the type is not defined in another file, the build fails.",
        "If the two files differ, rows are lost.", "When X changes and if other files still reference it, they break.", "If the namespace is not imported in another project, calls fail.",
    ])
    def test_a_case_that_only_exists_if_other_code_is_wrong_needs_a_lookup(self, case):
        kept, _ = clean_findings([cs_finding(failing_case=f"{case} Total is then wrong for every caller.")], cs_view())
        assert kept[0]["needs_lookup"] is True

    @pytest.mark.parametrize("case", [
        "If the list is empty, average() divides by zero and raises an error for the caller.", "If the input is not a string, int() raises TypeError in the request handler.",
        "Two Counts objects added to the same response share one list, so one caller's Add changes the other's data.",
    ])
    def test_a_case_about_this_codes_own_inputs_does_not(self, case):
        kept, _ = clean_findings([cs_finding(failing_case=case)], cs_view())
        assert kept[0]["needs_lookup"] is False

    def test_a_finding_from_the_ai_says_so_and_has_looked_at_nothing_yet(self):
        kept, _ = clean_findings([cs_finding()], cs_view())
        assert (kept[0]["source"], kept[0]["checked_with"]) == ("ai", [])


class TestWhatTheAiIsToldAbout:
    def test_today_is_in_the_first_read_and_the_second_check(self, monkeypatch):
        monkeypatch.setattr(pr_review, "today", lambda: "2031-02-03")
        _, _, model = run(model=FakePrModel({REPORT: [finding(17)]}))
        assert all("Today's date: 2031-02-03" in p for p in model.calls_of("file")) and "Today's date: 2031-02-03" in model.calls_of("verify")[0]

    def test_the_real_date_is_used(self):
        from datetime import datetime, timezone
        assert pr_review.today() == datetime.now(timezone.utc).date().isoformat()

    def test_the_other_files_of_the_pull_request_are_named_but_not_the_file_itself(self):
        _, _, model = run()
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {REPORT}"))
        line = next(l for l in prompt.splitlines() if l.startswith("Other files changed in this pull request"))
        assert "you cannot see them here" in line and "scripts/totals.ps1" in line and "tests/test_report.py" in line and REPORT not in line

    def test_a_pull_request_of_one_file_has_no_such_line(self):
        _, _, model = run(FakeAdo(changes=[change("/scripts/report.py")]))
        assert "Other files changed" not in model.calls_of("file")[0]

    def test_the_list_of_other_files_is_limited(self):
        names = [f"/src/m{n:03d}.py" for n in range(pr_review.MAX_OTHER_FILES + 10)]
        _, _, model = run(FakeAdo(changes=[change(n, "add") for n in names], blobs={f"new-{n}": "x = 1\n" for n in names}))
        line = next(l for l in model.calls_of("file")[0].splitlines() if l.startswith("Other files changed"))
        assert line.count("src/m") <= pr_review.MAX_OTHER_FILES

    def test_a_csharp_file_is_told_its_projects_language_version(self):
        _, _, model = run(cs_pr(), FakePrModel())
        prompt = next(u for u in model.calls_of("file") if u.startswith(f"File: {CS_PATH}"))
        assert "Project facts: this file belongs to src/Api/Api.csproj, which targets net8.0 (C# 12)" in prompt and "do not report them as invalid" in prompt

    def test_a_file_that_is_not_csharp_gets_no_project_facts(self):
        _, _, model = run()
        assert not any("Project facts" in p for p in model.calls_of("file"))

    def test_the_second_check_gets_the_same_facts_and_the_other_files(self):
        _, _, model = run(cs_pr(), FakePrModel({CS_PATH: [cs_finding()]}))
        verify = model.calls_of("verify")[0]
        assert "net8.0 (C# 12)" in verify and "Other files changed in this pull request: " in verify and OPTIONS_PATH in verify

    def test_project_facts_that_cannot_be_read_do_not_stop_the_review(self):
        ado = cs_pr()
        ado.repo_files = {}
        result, _, _ = run(ado)
        assert any(f["status"] == "reviewed" for f in result["files"])

    def test_the_rules_about_other_files_compile_errors_and_dates_are_in_the_prompts(self):
        for part in ("You see this one file only", "Do not report that code will not compile", "a date on or before today is not in the future", "syntax that the project's language version supports is valid"):
            assert part in pr_review.FILE_SYSTEM
        assert "does not hold unless the project facts show the syntax is newer" in pr_review.VERIFY_SYSTEM

    def test_csharp_and_markdown_get_their_own_guidance_and_alert_templates_the_documented_facts(self):
        assert pr_review.GUIDES["C#"] is pr_review.CSHARP_GUIDE and "HttpClient created for each call" in pr_review.CSHARP_GUIDE and "never call it invalid" in pr_review.CSHARP_GUIDE
        assert pr_review.GUIDES["Markdown"] is pr_review.MARKDOWN_GUIDE and "Do not comment on wording" in pr_review.MARKDOWN_GUIDE
        assert "source.queryType is ResultCount" in pr_review.ARM_GUIDE and "greater than or equal to frequencyInMinutes" in pr_review.ARM_GUIDE

    def test_the_prompts_name_no_company_data(self):
        text = pr_review.CSHARP_GUIDE + pr_review.MARKDOWN_GUIDE + pr_review.ARM_GUIDE + pr_review.VERIFY_TOOLS
        assert "MDC" not in text and "dbo." not in text


class TestATraceThatTheFirstAnswerLeftOut:
    """The first answer often leaves "trace" out of a true finding. The second check then writes it; a finding nobody traced goes."""

    @staticmethod
    def untraced(**over):
        return finding(3, "Setting has no default", failing_case="RefreshSeconds is 0 when the value is missing, so the refresh window is empty.",
                       evidence="public int RefreshSeconds { get; set; }", trace="", **over)

    def review(self, **model_options):
        result, _, model = run(cs_pr(), FakePrModel({OPTIONS_PATH: [self.untraced()]}, **model_options))
        return result, model

    def test_the_gate_keeps_the_finding_and_says_it_needs_a_trace(self):
        kept, removed = clean_findings([cs_finding(trace="")], cs_view())
        assert removed == [] and kept[0]["needs_trace"] is True and kept[0]["trace"] == ""
        kept, _ = clean_findings([cs_finding()], cs_view())
        assert kept[0]["needs_trace"] is False

    def test_a_trace_that_is_too_short_counts_as_none(self):
        assert clean_findings([cs_finding(trace="it fails")], cs_view())[0][0]["needs_trace"] is True

    def test_the_second_check_is_told_to_write_it_and_what_it_writes_is_kept(self):
        result, model = self.review()
        comment = result["comments"][0]
        assert comment["verified"] is True and comment["trace"].startswith("the value is read") and "needs_trace" not in comment
        assert "Its trace: none was given, so write it yourself" in model.calls_of("verify")[0]
        assert 'write the trace yourself, in "trace"' in model.system_of("verify")[0]

    def test_a_finding_that_came_with_a_trace_is_not_asked_for_another(self):
        _, _, model = run(cs_pr(), FakePrModel({OPTIONS_PATH: [no_default_finding()]}))
        assert "none was given" not in model.calls_of("verify")[0] and "Its trace: " in model.calls_of("verify")[0]

    @pytest.mark.parametrize("said", [{"holds": True, "trace": ""}, {"holds": True, "trace": "short"}, SILENT])
    def test_a_finding_that_nobody_traced_is_removed(self, said):
        result, _ = self.review(holds=lambda path, numbers: {1: said})
        assert result["comments"] == []
        assert "Removed as a guess: src/Api/RefreshOptions.cs: Setting has no default (did not trace its case through the code)" in result["notes"]

    def test_a_finding_the_second_check_does_not_hold_is_removed_as_before(self):
        result, _ = self.review(holds=lambda path, numbers: {1: (False, "its steps end in the right result")})
        assert result["comments"] == []
        assert "Removed on a second check: src/Api/RefreshOptions.cs: Setting has no default (its steps end in the right result)" in result["notes"]

    def test_when_the_second_check_cannot_run_a_finding_without_a_trace_goes_and_one_with_a_trace_stays(self):
        traced = finding(3, "Zero refresh window", failing_case="RefreshSeconds is 0 when the value is missing, so the refresh window is empty.", evidence="public int RefreshSeconds { get; set; }")
        model = FakePrModel({OPTIONS_PATH: [self.untraced(), traced]}, holds=lambda path, numbers: RuntimeError("down"))
        result, _, _ = run(cs_pr(), model)
        assert [c["title"] for c in result["comments"]] == ["Zero refresh window"] and result["comments"][0]["verified"] is None
        assert "needs_trace" not in result["comments"][0]


class TestSecondCheckLooksThingsUp:
    SEARCH = {OPTIONS_PATH: [("search_code", {"text": "PollSeconds"})]}

    def review(self, ado=None, lookups=None, decide=None, holds=None, findings=None):
        model = FakePrModel({OPTIONS_PATH: [rename_finding()]} if findings is None else findings, lookups=lookups, decide=decide, holds=holds)
        result, _, _ = run(ado or cs_pr(), model)
        return result, model

    @staticmethod
    def still_used(path, numbers, results):
        return {1: True} if "appsettings.json:3" in results[0] else {1: (False, "nothing uses the old name any more")}

    def test_the_second_check_is_offered_the_tools_and_told_how_to_use_them(self):
        _, model = self.review(lookups=self.SEARCH, decide=self.still_used)
        assert model.tools_offered == [True]
        system = model.system_of("verify")[0]
        assert "find_files, read_file and search_code" in system and "did not search them all, finding nothing does not prove" in system
        assert "never agree with a finding only because it sounds plausible" in system.lower()

    def test_a_finding_that_a_lookup_confirms_stays_and_shows_what_was_looked_at(self):
        result, model = self.review(lookups=self.SEARCH, decide=self.still_used)
        comment = result["comments"][0]
        assert comment["verified"] is True and comment["checked_with"] == ['searched the code for "PollSeconds"'] and comment["source"] == "ai"
        assert "needs_lookup" not in comment
        assert "appsettings.json:3:" in model.tool_results[0] and "Searched 3 of 3 candidate file(s)" in model.tool_results[0]

    def test_a_finding_that_a_lookup_contradicts_is_removed_and_the_reason_is_listed(self):
        result, _ = self.review(cs_pr(settings=SETTINGS_NEW_NAME), lookups=self.SEARCH, decide=self.still_used)
        assert result["comments"] == []
        assert "Removed on a second check: src/Api/RefreshOptions.cs: The renamed setting is not bound (nothing uses the old name any more)" in result["notes"]

    def test_a_finding_that_depends_on_other_files_is_removed_when_nothing_was_looked_up(self):
        result, _ = self.review()  # the second check answers "holds" without a single lookup
        assert result["comments"] == []
        assert "Removed as a guess: src/Api/RefreshOptions.cs: The renamed setting is not bound (depended on code outside this file, and no lookup confirmed it)" in result["notes"]
        assert any("depended on code outside the file that no lookup confirmed" in n for n in result["notes"])
        assert not any(n.startswith("Removed on a second check") for n in result["notes"])  # said once, with the guesses

    def test_a_finding_that_does_not_depend_on_other_files_needs_no_lookup(self):
        result, _ = self.review(findings={OPTIONS_PATH: [no_default_finding()]})
        comment = result["comments"][0]
        assert comment["verified"] is True and comment["checked_with"] == []

    def test_a_second_check_that_says_nothing_about_a_finding_that_needs_a_lookup_removes_it_but_keeps_one_that_does_not(self):
        result, _ = self.review(findings={OPTIONS_PATH: [rename_finding(), no_default_finding()]}, lookups=self.SEARCH, decide=lambda path, numbers, results: {1: SILENT}, holds=lambda path, numbers: {1: SILENT})
        assert [c["title"] for c in result["comments"]] == ["Setting has no default"] and result["comments"][0]["verified"] is True
        assert any("depended on code outside" in n for n in result["notes"])

    def test_what_was_read_is_listed_in_the_notes(self):
        lookups = {OPTIONS_PATH: [("read_file", {"path": "src/Api/Api.csproj"}), ("read_file", {"path": "/src/Api/appsettings.json"}), ("search_code", {"text": "PollSeconds"})]}
        result, _ = self.review(lookups=lookups, decide=lambda path, numbers, results: {1: True})
        assert "While checking findings, the second check read 2 file(s) of the repository: src/Api/Api.csproj, src/Api/appsettings.json." in result["notes"]
        assert result["comments"][0]["checked_with"] == ["read src/Api/Api.csproj", "read src/Api/appsettings.json", 'searched the code for "PollSeconds"']

    def test_without_a_commit_to_read_the_tools_are_not_offered_and_a_finding_that_needs_them_is_removed(self):
        ado = cs_pr()
        ado.get_pull_request_iterations = lambda *args: [{"id": 1, "sourceRefCommit": {}, "commonRefCommit": {"commitId": "b" * 40}}]
        result, model = self.review(ado)
        assert model.tools_offered == [False] and "find_files" not in model.system_of("verify")[0]
        assert result["comments"] == []

    def test_when_the_second_check_fails_a_finding_that_needs_a_lookup_is_removed_and_the_others_stay(self):
        result, _ = self.review(findings={OPTIONS_PATH: [rename_finding(), no_default_finding()]}, holds=lambda path, numbers: RuntimeError("down"))
        assert [c["title"] for c in result["comments"]] == ["Setting has no default"] and result["comments"][0]["verified"] is None
        assert any("The second check could not run" in n for n in result["notes"])
        assert any("depended on code outside" in n for n in result["notes"])

    def test_the_lookups_only_read_files_of_the_repository(self):
        ado = cs_pr()
        self.review(ado, lookups=self.SEARCH, decide=self.still_used)
        assert ado.item_calls and set(ado.item_calls) <= {"/" + p for p in ado.repo_files}

    def test_the_repository_is_listed_once_for_the_whole_review(self):
        ado = cs_pr()
        calls = []
        original = ado.list_repository_files
        ado.list_repository_files = lambda *args, **kwargs: calls.append(1) or original(*args, **kwargs)
        self.review(ado, lookups=self.SEARCH, decide=self.still_used)
        assert len(calls) == 1

    def test_an_unreadable_repository_listing_does_not_stop_the_review(self):
        ado = cs_pr()
        ado.tree_unreadable = True
        result, model = self.review(ado, lookups=self.SEARCH, decide=lambda path, numbers, results: {1: True})
        assert "file list could not be read" in model.tool_results[0] and len(result["comments"]) == 1


class TestStaticFindingsInTheReview:
    @staticmethod
    def ps_pr(**kwargs):
        return FakeAdo(changes=[change("/tools/x.ps1", "add")], blobs={"new-/tools/x.ps1": "$status = Get-Status\nWrite-Output 'x'\n"}, description="Adds a script.", **kwargs)

    def test_an_exact_finding_is_shown_marked_as_static_and_is_not_sent_to_the_second_check(self):
        result, _, model = run(self.ps_pr())
        assert [(c["title"], c["source"], c["verified"], c["severity"], c["file_path"], c["line_number"]) for c in result["comments"]] == \
            [("$status is assigned and never used", "static", None, "suggestion", "tools/x.ps1", 1)]
        assert model.calls_of("verify") == [] and result["verdict"] == "APPROVED_WITH_SUGGESTIONS" and "1 finding: 1 suggestion." in result["summary"]

    def test_the_notes_say_how_many_came_from_code(self):
        result, _, _ = run(self.ps_pr())
        assert "1 finding(s) come from static checks made in code, without the AI (marked \"static check\")." in result["notes"]
        assert not any("The second check could not run" in n for n in result["notes"])

    def test_a_comment_people_already_made_on_that_line_is_noticed(self):
        result, _, _ = run(self.ps_pr(threads=[thread("tools/x.ps1", 1, "Drop this variable", status="active", author="Alex")]))
        assert result["comments"][0]["existing_thread"] == "Already raised by Alex (open)"

    def test_static_findings_are_mixed_in_with_the_ais_by_severity(self):
        ado = FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": PY_NEW.replace("import json", "import json\nimport os"), "old-/scripts/report.py": PY_OLD})
        result, _, _ = run(ado, FakePrModel({REPORT: [finding(18, "Division by zero")]}))
        assert [(c["title"], c["source"]) for c in result["comments"]] == [("Division by zero", "ai"), ("os is imported and never used", "static")]

    def test_a_static_finding_stays_when_the_ai_found_nothing_to_add(self):
        result, _, _ = run(self.ps_pr(), FakePrModel())
        assert len(result["comments"]) == 1

    def test_the_file_that_lost_its_utf8_encoding_is_reported(self):
        old = decoded("name = 'café'\nother = 1\n")
        new = decoded("name = 'caf�'\nother = 2\n", bad_line=1, bad_count=1)
        ado = FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": new, "old-/scripts/report.py": old})
        result, _, _ = run(ado)
        comment = result["comments"][0]
        assert (comment["title"], comment["severity"], comment["line_number"], comment["source"]) == ("The file is no longer valid UTF-8", "warning", 1, "static")
        assert result["verdict"] == "APPROVED_WITH_SUGGESTIONS"

    def test_the_ai_is_shown_the_replacement_character_as_it_is_in_the_file(self):
        old = decoded("name = 'café'\n")
        new = decoded("name = 'caf�'\n", bad_line=1, bad_count=1)
        ado = FakeAdo(changes=[change("/scripts/report.py")], blobs={"new-/scripts/report.py": new, "old-/scripts/report.py": old})
        _, _, model = run(ado)
        assert "caf�" in model.calls_of("file")[0]


class TestMarkdownIsReviewed:
    GUIDE = "| name | value |\n|---|---|\n| a | 1 |\n"

    def ado(self, new, old=GUIDE):
        return FakeAdo(changes=[change("/docs/guide.md")], blobs={"new-/docs/guide.md": new, "old-/docs/guide.md": old}, description="Updates the guide.")

    def test_a_markdown_file_is_read_with_its_own_guidance(self):
        result, _, model = run(self.ado(self.GUIDE + "| b | 2 |\n"))
        row = by_path(result)["docs/guide.md"]
        assert (row["status"], row["language"]) == ("reviewed", "Markdown")
        system = model.calls[0][0]
        assert "Markdown: look for content this change removed" in system and "Do not comment on wording" in system and "PowerShell:" not in system

    def test_a_table_row_with_the_wrong_number_of_cells_is_reported_by_the_code(self):
        result, _, _ = run(self.ado(self.GUIDE + "| b |\n"))
        assert [(c["title"], c["line_number"], c["source"]) for c in result["comments"]] == [("Table row has 1 cell, the header has 2 cells", 4, "static")]

    def test_a_changelog_is_still_not_reviewed(self):
        ado = FakeAdo(changes=[change("/CHANGELOG.md"), change("/docs/guide.md")],
                      blobs={"new-/CHANGELOG.md": "# x\n", "old-/CHANGELOG.md": "", "new-/docs/guide.md": self.GUIDE + "| b | 2 |\n", "old-/docs/guide.md": self.GUIDE})
        result, _, model = run(ado)
        assert by_path(result)["CHANGELOG.md"]["status"] == "skipped" and len(model.calls_of("file")) == 1

    def test_markdown_is_reviewed_last_when_there_is_not_room_for_everything(self):
        names = [f"/src/m{n:02d}.py" for n in range(pr_review.MAX_FILES)]
        ado = FakeAdo(changes=[change(n, "add") for n in names] + [change("/README.md", "add")], blobs={**{f"new-{n}": "x = 1\n" for n in names}, "new-/README.md": "# Hi\n"})
        rows = by_path(run(ado)[0])
        assert rows["README.md"]["status"] == "skipped" and "over the limit" in rows["README.md"]["reason"]


class TestLessNoise:
    DESCRIPTION = "Adds a report script with an average helper. Also a retry loader for the input files.\n\n- [x] Changelog updated\n"

    def test_a_note_about_something_the_description_already_says_is_dropped(self):
        gaps = ["a retry mechanism was added to the loader", "a new caching layer for results"]
        result, _, _ = run(FakeAdo(description=self.DESCRIPTION), FakePrModel(gaps=gaps))
        assert result["clarifications"] == ["The description does not mention: a new caching layer for results"]

    @pytest.mark.parametrize("gap,description,covered", [
        ("validation of the input was added", "Adds input validation.", True),
        ("a new caching layer for results", "Adds a report.", False),
        ("a b c", "anything at all", False),
        ("the retry loader changed", "retry loader", True),
        ("the retry loader and a cache and a queue and a topic", "retry loader", False),
    ])
    def test_when_the_description_covers_a_note(self, gap, description, covered):
        assert pr_review.covered_by(gap, description) is covered

    def test_template_text_left_in_the_description_is_pointed_out(self):
        description = "Fixes the loader.\n\nRun: [Insert Pipeline Link]\nResults: <insert results here>\n"
        result, _, _ = run(FakeAdo(description=description))
        check = next(c for c in result["checklist"] if c["item"] == "Template text left in the description")
        assert check["status"] == "open" and check["checked"] is None and '"[Insert Pipeline Link]"' in check["evidence"] and '"<insert results here>"' in check["evidence"]

    def test_a_real_link_or_ordinary_brackets_are_not_template_text(self):
        description = "See [Insert docs](https://example.com/docs) and [the wiki](https://example.com) for the list [1, 2].\n"
        result, _, _ = run(FakeAdo(description=description))
        assert not any(c["item"] == "Template text left in the description" for c in result["checklist"])

    def test_the_same_note_is_not_said_twice(self, monkeypatch):
        def twice(self, notes, what, call):
            notes.extend([f"{what} could not be read", f"{what} could not be read"])
            return None

        monkeypatch.setattr(PullRequestReviewService, "_optional", twice)
        result, _, _ = run()
        assert result["notes"].count("The existing comments could not be read") == 1


class TestProgressAndTheTimeAllowed:
    def test_progress_is_reported_from_reading_to_the_summary(self):
        told = []
        PullRequestReviewService(FakeAdo(), FakePrModel()).review("proj", "repo", 7, progress=lambda done, total, message: told.append((done, total, message)))
        assert told[0] == (0, 0, "Reading the pull request") and told[-1] == (1, 1, "Writing the summary")
        assert (0, 3, "Reviewing 3 files") in told and told[-2] == (3, 3, "Reviewed 3 of 3 files")
        assert [done for done, total, message in told if message.startswith("Reviewed ")] == [1, 2, 3]

    def test_the_review_works_without_a_progress_listener(self):
        assert PullRequestReviewService(FakeAdo(), FakePrModel()).review("proj", "repo", 7)["pull_request_id"] == 7

    def test_the_seconds_allowed_can_be_given_and_a_review_out_of_time_fails_plainly(self):
        with pytest.raises(ReviewFailed) as error:
            PullRequestReviewService(FakeAdo(), FakePrModel()).review("proj", "repo", 7, budget=-1)
        assert "not reached in the time allowed" in str(error.value) and "Nothing was reviewed" in str(error.value)

    def test_a_review_in_the_background_has_more_time_than_one_inside_a_web_request(self):
        assert pr_review.REVIEW_BUDGET_SECONDS < 230 < pr_review.BACKGROUND_BUDGET_SECONDS

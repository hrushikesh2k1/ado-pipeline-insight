"""The team's own checks in a review: what the AI is given, what comes back, and how it is reported. The code in this file is made up."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import create_app
from app.services import pr_review, pr_review_jobs
from app.services.pr_review import PullRequestReviewService, clean_findings
from app.services.pr_review_jobs import ReviewJobs
from pr_support import FakeAdo, FakePrModel, finding

REPORT = "scripts/report.py"
TOTALS = "scripts/totals.ps1"
CHECKS = """# my checks
[PowerShell] Avoid `Write-Host` in scripts
[Python] Public functions need a docstring
[SQL] Never SELECT *
[PR] The description names the design reviewer
"""


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)


def run(knowledge="", ado=None, model=None):
    ado, model = ado or FakeAdo(), model or FakePrModel()
    return PullRequestReviewService(ado, model).review("proj", "repo", 7, knowledge=knowledge), ado, model


def write_host_finding(**over):
    return finding(7, "Write-Host in a script", "suggestion", category="correctness", comment="Write-Host writes to the host, so a caller cannot capture the message.",
                    failing_case="A caller that pipes the script's output gets nothing for the message that Write-Host printed.", kb=1, **over)


def prompt_for(model, path):
    return next(u for u in model.calls_of("file") if u.startswith(f"File: {path}"))


class TestWhatTheReviewerIsGiven:
    def test_a_check_for_powershell_is_given_for_powershell_files_only(self):
        _, _, model = run("[PowerShell] Avoid `Write-Host` in scripts")
        assert "The team's own checks for this kind of file" in prompt_for(model, TOTALS) and "1. Avoid `Write-Host` in scripts" in prompt_for(model, TOTALS)
        assert "The team's own checks" not in prompt_for(model, REPORT)

    def test_a_check_with_no_scope_is_given_for_every_reviewed_file(self):
        _, _, model = run("No `TODO` left behind")
        assert all("1. No `TODO` left behind" in p for p in model.calls_of("file")) and len(model.calls_of("file")) == 3

    def test_a_check_about_the_pull_request_is_not_given_for_files(self):
        _, _, model = run("[PR] The description names the design reviewer")
        assert not any("The team's own checks" in p for p in model.calls_of("file"))

    def test_no_knowledge_means_no_block_and_no_report(self):
        for knowledge in ("", "   ", "# only a note"):
            result, _, model = run(knowledge)
            assert not any("The team's own checks" in p for p in model.calls_of("file")) and result["knowledge_checks"] == [] and model.calls_of("team") == []

    def test_where_a_named_term_appears_in_the_changed_lines_is_shown_to_the_reviewer(self):
        _, _, model = run("[PowerShell] Avoid `Write-Host` in scripts")
        assert "- check 1, `Write-Host`: line 7: Write-Host \"done\"" in prompt_for(model, TOTALS)

    def test_the_system_prompt_lets_a_finding_name_its_check(self):
        assert '"kb": null' in pr_review.FILE_SYSTEM and '"kb" is the number of the team\'s check' in pr_review.FILE_SYSTEM


class TestFindingsFromTheTeamsChecks:
    def test_a_finding_that_names_a_check_carries_it_and_the_second_check_is_told(self):
        result, _, model = run("[PowerShell] Avoid `Write-Host` in scripts", model=FakePrModel({TOTALS: [write_host_finding()]}))
        comment = result["comments"][0]
        assert (comment["knowledge"], comment["knowledge_number"]) == ("Avoid `Write-Host` in scripts", 1)
        assert "Team check: Avoid `Write-Host` in scripts" in model.calls_of("verify")[0]
        assert "Some findings come from \"Team check\" lines" in pr_review.VERIFY_SYSTEM

    def test_a_finding_that_names_no_check_has_none(self):
        result, _, _ = run("[PowerShell] Avoid `Write-Host` in scripts", model=FakePrModel({REPORT: [finding(17)]}))
        assert result["comments"][0]["knowledge"] is None and result["comments"][0]["knowledge_number"] is None

    @pytest.mark.parametrize("kb", [5, 0, -1, "two", None, True])
    def test_a_number_the_reviewer_was_not_given_is_ignored(self, kb):
        result, _, _ = run("[PowerShell] Avoid `Write-Host` in scripts", model=FakePrModel({TOTALS: [{**write_host_finding(), "kb": kb}]}))
        assert result["comments"][0]["knowledge"] is None

    def test_a_check_for_another_language_cannot_be_named(self):
        # check 1 is for Python: the PowerShell file was never given it
        result, _, _ = run("[Python] Public functions need a docstring", model=FakePrModel({TOTALS: [write_host_finding()]}))
        assert result["comments"][0]["knowledge"] is None

    def test_a_finding_from_a_check_still_has_to_follow_every_rule(self):
        guessed = {**write_host_finding(), "failing_case": "The message may be lost for a caller."}
        quoteless = {**write_host_finding(), "evidence": "Write-Host 'a line that is not in the file'"}
        result, _, _ = run("[PowerShell] Avoid `Write-Host` in scripts", model=FakePrModel({TOTALS: [guessed, quoteless]}))
        assert result["comments"] == []
        assert "Removed as a guess: scripts/totals.ps1: Write-Host in a script (its case was a guess ('may'))" in result["notes"]

    def test_clean_findings_links_the_check_when_it_is_given_the_checks(self):
        from pr_support import PS_NEW
        from app.services.pr_diff import build_view
        view = build_view(TOTALS, "PowerShell", "add", "", PS_NEW)
        kept, _ = clean_findings([{**write_host_finding(), "evidence": 'Write-Host "done"'}], view, {1: {"number": 1, "text": "Avoid Write-Host"}})
        assert kept[0]["knowledge"] == "Avoid Write-Host"
        kept, _ = clean_findings([{**write_host_finding(), "evidence": 'Write-Host "done"'}], view)
        assert kept[0]["knowledge"] is None


class TestWhatHappenedToEachCheck:
    TEAM_CHECK = {4: (True, "the description never names a design reviewer", "Adds a report.")}

    def report(self, knowledge=CHECKS, model=None):
        result, _, m = run(knowledge, model=model or FakePrModel({TOTALS: [write_host_finding()]}, team_checks=self.TEAM_CHECK))
        return {c["number"]: c for c in result["knowledge_checks"]}, result, m

    def test_each_check_says_what_became_of_it(self):
        checks, _, _ = self.report()
        assert {n: (c["status"], c["files"], c["findings"], c["scope"]) for n, c in checks.items()} == {
            1: ("raised", 1, 1, "PowerShell"),
            2: ("nothing_reported", 2, 0, "Python"),  # given for the two Python files, nothing was reported
            3: ("not_applicable", 0, 0, "SQL"),  # no SQL file in this pull request
            4: ("raised", 0, 1, "the pull request"),
        }
        assert checks[1]["text"] == "Avoid `Write-Host` in scripts"

    def test_where_the_named_terms_appear_is_reported_with_the_file_and_line(self):
        checks, _, _ = self.report()
        assert checks[1]["hits"] == [{"item": 1, "term": "Write-Host", "path": TOTALS, "line": 7, "text": 'Write-Host "done"'}]
        assert checks[2]["hits"] == []

    def test_a_term_in_old_code_is_not_a_hit(self):
        checks, _, _ = self.report("[Python] Watch `json.load`", model=FakePrModel())  # line 7 of the report script is old code
        assert checks[1]["hits"] == []
        checks, _, _ = self.report("[Python] Watch `def average`", model=FakePrModel())
        assert [(h["path"], h["line"]) for h in checks[1]["hits"]] == [(REPORT, 16)]

    def test_a_check_about_the_pull_request_that_is_broken_becomes_a_note_with_its_reason(self):
        _, result, model = self.report()
        assert "Your knowledge base, check 4: the description never names a design reviewer" in result["clarifications"]
        asked = model.calls_of("team")
        assert len(asked) == 1 and "4. The description names the design reviewer" in asked[0] and "Adds a report." in asked[0] and REPORT in asked[0]  # it keeps its number in the list

    @pytest.mark.parametrize("said", [
        {4: (False, "it does", "Adds a report.")}, {4: (None, "cannot tell", "")}, {4: (True, "it is missing", "words that are not in the description")},
        {4: (True, "it may be missing", "Adds a report.")}, {4: (True, "please confirm the reviewer", "Adds a report.")}, {4: (True, "", "Adds a report.")}, {9: (True, "no such check", "Adds a report.")},
    ])
    def test_a_check_about_the_pull_request_needs_a_real_quote_and_no_guess(self, said):
        checks, result, _ = self.report(model=FakePrModel(team_checks=said))
        assert checks[4]["status"] == "nothing_reported" and not any(c.startswith("Your knowledge base") for c in result["clarifications"])

    def test_the_words_of_the_quote_may_come_from_a_file_path_or_a_comment(self):
        checks, result, _ = self.report("[PR] No tests added", model=FakePrModel(team_checks={1: (True, "no test file is in the pull request", "scripts/report.py")}))
        assert checks[1]["status"] == "raised"

    def test_when_the_ai_cannot_check_the_pull_request_the_page_is_told(self):
        checks, result, _ = self.report(model=FakePrModel(team_checks=RuntimeError("down")))
        assert checks[4]["status"] == "could_not_check" and result["pull_request_id"] == 7

    def test_no_check_about_the_pull_request_means_no_such_call(self):
        _, _, model = run("[PowerShell] Avoid `Write-Host`")
        assert model.calls_of("team") == []

    def test_a_check_for_a_file_is_not_applicable_when_the_ai_failed_for_those_files(self):
        model = FakePrModel({TOTALS: RuntimeError("down")})
        result, _, _ = run("[PowerShell] Avoid `Write-Host` in scripts", model=model)
        assert result["knowledge_checks"][0]["status"] == "not_applicable" and result["knowledge_checks"][0]["files"] == 0

    def test_a_long_knowledge_text_is_cut_to_the_limit_and_many_checks_are_capped(self):
        many = "\n".join(f"check number {n}" for n in range(100))
        result, _, _ = run(many)
        assert len(result["knowledge_checks"]) == 40


@pytest.fixture
def api(monkeypatch):
    state = {"ado": FakeAdo(), "model": FakePrModel()}
    monkeypatch.setattr(routes, "AzureDevOpsClient", lambda organization, pat: state["ado"])
    monkeypatch.setattr(pr_review, "get_model_client", lambda *choice: state["model"])
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)
    monkeypatch.setattr(pr_review_jobs, "jobs", ReviewJobs())
    return TestClient(create_app(), raise_server_exceptions=False), state


PAYLOAD = {"organization": "myorg", "project": "myproj", "repository_id": "repo-1", "pull_request_id": 101, "pat": "fake-pat"}


def finish(client, job_id, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/v1/ado/pullrequests/review/status/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("the review did not finish")


class TestOverHttp:
    def test_the_direct_review_uses_the_knowledge_and_returns_the_report(self, api):
        client, state = api
        state["model"] = FakePrModel({TOTALS: [write_host_finding()]})
        data = client.post("/api/v1/ado/pullrequests/review", json={**PAYLOAD, "knowledge": "[PowerShell] Avoid `Write-Host` in scripts"}).json()
        assert "1. Avoid `Write-Host` in scripts" in prompt_for(state["model"], TOTALS)
        assert data["comments"][0]["knowledge"] == "Avoid `Write-Host` in scripts" and data["knowledge_checks"][0]["status"] == "raised"
        assert data["knowledge_checks"][0]["hits"][0]["line"] == 7

    def test_the_background_review_uses_it_too(self, api):
        client, state = api
        state["model"] = FakePrModel({TOTALS: [write_host_finding()]})
        started = client.post("/api/v1/ado/pullrequests/review/start", json={**PAYLOAD, "knowledge": "[PowerShell] Avoid `Write-Host` in scripts"}).json()
        done = finish(client, started["job_id"])
        assert done["result"]["knowledge_checks"][0]["status"] == "raised" and done["result"]["comments"][0]["knowledge_number"] == 1

    def test_a_request_with_no_knowledge_is_a_review_as_before(self, api):
        client, _ = api
        data = client.post("/api/v1/ado/pullrequests/review", json=PAYLOAD).json()
        assert data["knowledge_checks"] == [] and data["pull_request_id"] == 101

    @pytest.mark.parametrize("path", ["/api/v1/ado/pullrequests/review", "/api/v1/ado/pullrequests/review/start"])
    def test_a_knowledge_text_over_the_limit_is_refused(self, api, path):
        client, _ = api
        assert client.post(path, json={**PAYLOAD, "knowledge": "x" * 6001}).status_code == 422
        assert client.post(path, json={**PAYLOAD, "knowledge": "x" * 6000}).status_code in {200, 202}

    def test_another_set_of_checks_is_another_review_but_a_change_of_spacing_is_not(self, api):
        import threading
        client, state = api
        release = threading.Event()

        class Slow(FakePrModel):
            def _create(self, *args, **kwargs):
                release.wait(5)
                return super()._create(*args, **kwargs)

        state["model"] = Slow()
        start = lambda text: client.post("/api/v1/ado/pullrequests/review/start", json={**PAYLOAD, "knowledge": text}).json()["job_id"]
        first = start("one check")
        assert start("  one   check \n\n") == first
        assert start("another check") != first
        release.set()
        finish(client, first)

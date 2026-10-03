"""Template diagnostics, diff validation, the full-file prompt payload, and the 'every insight is complete' end-to-end guarantees."""
import pytest
import requests

import app.services.ai_service as ai_module
from app.services import pipeline_yaml as py
from app.services.ai_service import AIService
from core.models import Finding, RecommendationResponse
from test_pipeline_yaml import (
    MAIN_WITH_TEMPLATE,
    MONITORING_TEMPLATE,
    NPM_PIPELINE,
    FakeRepo,
    _settings,
    ctx_for,
)


class TestTemplateDiagnostics:
    """When a template cannot be read, the result says exactly why (not found / no access / unsupported / expression)."""

    def parse(self, ref, repo, resources=""):
        text = f"{resources}steps:\n  - template: {ref}\n"
        loader = py.make_template_loader(repo, "Proj", "repo-1", "main", py._repository_resources(py._safe_load(text)))
        return py.parse_pipeline_yaml(text, "azure-pipelines.yml", loader)

    def test_a_missing_file_says_which_repository_branch_and_path(self):
        facts = self.parse("templates/x.yml", FakeRepo({}))
        assert "'templates/x.yml' was not found in repository 'Proj/repo-1' at branch 'main'" in facts.template_errors["templates/x.yml"]

    def test_no_access_says_the_scope_and_repository(self):
        class Denied(FakeRepo):
            def get_repository_file(self, *args, **kwargs):
                response = requests.Response()
                response.status_code = 403
                raise requests.HTTPError(response=response)

        reason = self.parse("templates/x.yml", Denied({})).template_errors["templates/x.yml"]
        assert "the token cannot read repository 'Proj/repo-1'" in reason and "Code (Read)" in reason

    def test_an_undeclared_alias_an_unsupported_type_and_an_expression_each_have_their_own_reason(self):
        assert "repository alias 'nope' is not declared" in self.parse("a.yml@nope", FakeRepo({})).template_errors["a.yml@nope"]
        github = "resources:\n  repositories:\n    - repository: gh\n      type: github\n      name: org/repo\n"
        assert "is of type 'github'" in self.parse("a.yml@gh", FakeRepo({}), github).template_errors["a.yml@gh"]
        assert "pipeline expression" in self.parse("${{ parameters.t }}.yml", FakeRepo({})).template_errors["${{ parameters.t }}.yml"]
        assert "outside the repository" in self.parse("../../x.yml", FakeRepo({})).template_errors["../../x.yml"]

    def test_the_context_lists_every_unread_template_with_its_reason(self):
        text = "steps:\n  - template: a.yml\n  - template: b.yml@nope\n"
        ctx = ctx_for(text, loader=py.make_template_loader(FakeRepo({}), "Proj", "r", "main", {}))
        listed = ctx.unresolved_with_reasons
        assert len(listed) == 2 and listed[0].startswith("a.yml (") and "was not found" in listed[0] and "not declared" in listed[1]

    def test_tags_and_commits_are_read_as_tags_and_commits_not_branches(self):
        sha = "a" * 40
        resources = ("resources:\n  repositories:\n    - repository: tagged\n      type: git\n      name: Plat/shared\n      ref: refs/tags/v1.2\n"
                     f"    - repository: pinned\n      type: git\n      name: shared2\n      ref: {sha}\n")
        repo = FakeRepo({"s.yml": "steps: []\n"})
        self.parse("s.yml@tagged", repo, resources)
        self.parse("s.yml@pinned", repo, resources)
        assert repo.calls == [("Plat", "shared", "s.yml", "v1.2", "tag"), ("Proj", "shared2", "s.yml", sha, "commit")]

    def test_split_ref(self):
        assert py.split_ref("refs/heads/release/1") == ("release/1", "branch") and py.split_ref("refs/tags/v1") == ("v1", "tag")
        assert py.split_ref("main") == ("main", "branch") and py.split_ref(None) == (None, "branch") and py.split_ref("") == (None, "branch")


class TestDiffValidation:
    FILES = {"azure-pipelines.yml": NPM_PIPELINE}
    GOOD = ("--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@ -9,3 +9,4 @@\n"
            "           - script: npm ci\n             displayName: Install packages\n+            retryCountOnTaskFailure: 2\n           - script: npm run build")

    def test_a_diff_whose_lines_exist_in_the_file_is_accepted_whatever_its_line_numbers(self):
        assert py.check_diff(self.GOOD, self.FILES)
        assert py.check_diff(self.GOOD.replace("@@ -9,3 +9,4 @@", "@@ -1,1 +1,1 @@"), self.FILES)  # numbers are ignored; content has to match

    def test_the_generated_diffs_always_pass_their_own_check(self):
        diff = py.diff_add_retry(NPM_PIPELINE, "Install packages", "azure-pipelines.yml")
        assert py.check_diff(diff, self.FILES)
        assert py.check_diff(py.diff_add_cache(NPM_PIPELINE, "Install packages", "npm", "azure-pipelines.yml"), self.FILES)

    @pytest.mark.parametrize("bad", [
        "--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@\n   - script: this line is not in the file\n+  retryCountOnTaskFailure: 2",
        "--- a/other.yml\n+++ b/other.yml\n@@\n           - script: npm ci\n+x: y",
        "--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@\n+retryCountOnTaskFailure: 2",
        "+retryCountOnTaskFailure: 2",
        "",
    ])
    def test_invented_or_misaligned_diffs_are_rejected(self, bad):
        assert not py.check_diff(bad, self.FILES)

    def test_a_template_file_is_found_by_its_name(self):
        files = {"azure-pipelines.yml": "x: y", "templates/t.yml": MONITORING_TEMPLATE}
        diff = "--- a/templates/t.yml\n+++ b/templates/t.yml\n@@\n     displayName: Install MDC chart\n+    retryCountOnTaskFailure: 2"
        assert py.check_diff(diff, files)

    @staticmethod
    def finding_with(diff, category="flaky_step"):
        return {"category": category, "recommendation": f"**Remediation**: r\n\n```diff\n{diff}\n```"}

    FAKE = "--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml\n@@\n   - script: invented\n+  retryCountOnTaskFailure: 2"

    def test_a_real_diff_is_kept_and_a_fake_one_for_another_kind_of_finding_becomes_a_labelled_example_of_only_its_new_lines(self):
        ctx = ctx_for(NPM_PIPELINE)
        kept = py.validate_model_snippets([self.finding_with(self.GOOD)], ctx)[0]["recommendation"]
        assert "```diff" in kept and "# example" not in kept
        out = py.validate_model_snippets([self.finding_with(self.FAKE, "caching_opportunity")], ctx)[0]["recommendation"]
        assert "```diff" not in out and "```yaml" in out and "# example, not from your file (the suggested diff could not be matched" in out
        assert "  retryCountOnTaskFailure: 2" in out and "invented" not in out

    def test_a_diff_that_does_not_match_is_removed_from_a_failing_step_instead_of_shown_as_an_example(self):
        out = py.validate_model_snippets([self.finding_with(self.FAKE)], ctx_for(NPM_PIPELINE))[0]["recommendation"]
        assert "```" not in out and "retryCountOnTaskFailure" not in out and "invented" not in out

    def test_without_any_pipeline_files_every_diff_is_only_an_example(self):
        out = py.validate_model_snippets([self.finding_with(self.GOOD, "caching_opportunity")], None)[0]["recommendation"]
        assert "```diff" not in out and "your pipeline files were not available" in out

    def test_without_any_pipeline_files_a_failing_steps_diff_is_removed(self):
        assert "```" not in py.validate_model_snippets([self.finding_with(self.GOOD)], None)[0]["recommendation"]

    def test_added_lines_helper(self):
        assert py.diff_added_lines(self.GOOD) == ["            retryCountOnTaskFailure: 2"]


class TestFullFileForTheModel:
    def test_the_whole_pipeline_file_and_every_template_are_sent_with_the_reasons_for_the_unread_ones(self):
        main = MAIN_WITH_TEMPLATE + "# padding\n" * 1500
        repo = FakeRepo({"templates/deploy-monitoring.yml": MONITORING_TEMPLATE})
        ctx = ctx_for(main + "      - template: missing.yml\n", loader=repo.loader(main))
        payload = py.yaml_for_prompt(ctx)
        assert payload["content"] == ctx.content and payload["truncated"] is False  # ~15 KB: the whole file, not a 12 KB excerpt
        assert payload["templates"][0]["content"] == MONITORING_TEMPLATE
        assert "missing.yml" in payload["templates_not_expanded"] and "was not found" in payload["template_errors"]["missing.yml"]

    def test_only_a_file_larger_than_the_cap_is_cut_and_the_model_is_told(self):
        huge = "steps:\n" + "  - script: echo hi\n" * 5000
        assert len(huge) > py.MAIN_PROMPT_CHARS and py.yaml_for_prompt(ctx_for(huge))["truncated"] is True


def _task(name, fail, error, duration=200):
    return {"name": name, "avg_duration_s": duration, "pct_of_parent_duration": 50, "failure_rate_pct": fail, "retry_rate_pct": 0, "error_excerpt": error}


class TestEveryInsightIsComplete:
    """End to end: whatever the model answers, each stored finding has a root cause, a remediation and a YAML block."""

    @pytest.fixture
    def run(self, monkeypatch):
        from types import SimpleNamespace
        saved = {}

        def go(summary, model_findings, repo_files=None, recommend=None):
            monkeypatch.setattr(ai_module, "get_settings", _settings)
            monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: summary)
            monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(
                count_runs=lambda pid, days: 10, get_pipeline_metrics=lambda pid, days: [], upsert_recommendations=lambda pid, f: saved.update(f=f)))
            monkeypatch.setattr(ai_module, "fetch_one", lambda q, p=(): {"organization_name": "org", "project_name": "proj"})
            repo = FakeRepo(repo_files or {})
            repo.get_build_definition = lambda project, pid: {"process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
                                                              "repository": {"id": "r1", "type": "TfsGit", "defaultBranch": "refs/heads/main"}}
            monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: repo)
            calls = []

            class Model:
                def __init__(self, *a, **k):
                    pass

                def recommend(self, s):
                    calls.append(dict(s))
                    return recommend(s) if recommend else RecommendationResponse(findings=model_findings)

            monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Model)
            return AIService().analyze(7, 30, resolve_pat=lambda org: "token"), calls, saved

        return go

    def test_the_screenshot_pipeline_end_to_end(self, run):
        """The step lives in a template that cannot be read; the model invented a HelmDeploy snippet and over-claimed."""
        variable_error = "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group 'rg' was not found."
        s = {"stages": [{"name": "Deploy monitoring", "avg_duration_s": 300, "failure_rate_pct": 38, "tasks": [
            _task("Install MDC chart", 31.8, "##[error]Script failed with exit code: 1"), _task("Remove access", 27.3, variable_error, 7)]}]}
        model = [Finding("flaky_step", "high", "Deploy monitoring", "Install MDC chart", (
            "**Diagnosis**: This is a deterministic failure.\n**Remediation**: Add a retry.\n\n```yaml\n- task: HelmDeploy@0\n  retryCountOnTaskFailure: 2\n```\n"
            "**Impact**: Eliminates ~31.8% failure rate."), "e")]
        result, _calls, saved = run(s, model, {"azure-pipelines.yml": MAIN_WITH_TEMPLATE})
        assert len(result["findings"]) == 2 and saved["f"] == result["findings"]
        by_task = {f["task_name"]: f for f in result["findings"]}
        mdc, access = by_task["Install MDC chart"], by_task["Remove access"]
        assert "HelmDeploy@0" not in mdc["recommendation"] and "Eliminates" not in mdc["recommendation"] and "deterministic" not in mdc["recommendation"]
        assert "system.debug: true" in mdc["recommendation"]  # a derived, labelled block replaced the invented one
        assert "`$(storageAccountName)`" in access["recommendation"] and "- name: storageAccountName" in access["recommendation"]
        assert "Templates that could not be read: templates/deploy-monitoring.yml (" in result["message"]
        for f in result["findings"]:
            assert all(part in f["recommendation"] for part in ("**Diagnosis**", "**Remediation**", "**Impact**", "```yaml"))
            assert f["severity"] == "high" and "% of runs in the analysed window" in f["recommendation"]

    def test_five_stages_with_the_same_error_become_one_card(self, run):
        error = "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group 'rg' was not found."
        s = {"stages": [{"name": f"Stage {i}", "avg_duration_s": 100, "tasks": [_task("Remove access", 20 + i, error, 7)]} for i in range(5)]}
        result, _c, _s = run(s, [])
        assert len(result["findings"]) == 1 and "4 duplicate finding(s)" in result["message"]
        assert "'Stage 0' (20%)" in result["findings"][0]["recommendation"]

    def test_the_model_sees_the_whole_file_and_its_templates(self, run):
        files = {"azure-pipelines.yml": MAIN_WITH_TEMPLATE, "templates/deploy-monitoring.yml": MONITORING_TEMPLATE}
        _r, calls, _s = run({"stages": []}, [], files)
        sent = calls[0]["pipeline_yaml"]
        assert sent["content"] == MAIN_WITH_TEMPLATE and sent["templates"][0]["content"] == MONITORING_TEMPLATE

    def test_a_request_the_model_rejects_for_size_is_repeated_without_the_yaml_and_says_so(self, run):
        def recommend(s):
            if "pipeline_yaml" in s:
                raise ValueError("Azure OpenAI failed after retries")
            return RecommendationResponse(findings=[Finding("flaky_step", "high", "S", "Step", "**Diagnosis**: d\n**Remediation**: r\n**Impact**: i", "e")])

        s = {"stages": [{"name": "S", "avg_duration_s": 10, "tasks": [_task("Step", 40, "i/o timeout", 5)]}]}
        result, calls, _s = run(s, [], {"azure-pipelines.yml": NPM_PIPELINE}, recommend=recommend)
        assert len(calls) == 2 and "pipeline_yaml" in calls[0] and "pipeline_yaml" not in calls[1]
        assert "was rejected, so it was repeated without the YAML" in result["message"] and len(result["findings"]) == 1

    def test_a_model_failure_that_has_nothing_to_do_with_the_yaml_is_still_raised(self, run):
        def recommend(s):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            run({"stages": []}, [], {}, recommend=recommend)

"""Where a step is, said honestly: file and line, template origin, no raw expressions, no 'not found' note for a step that was found."""
import pytest

import app.services.ai_service as ai_module
from app.services import pipeline_yaml as py
from app.services.ai_service import AIService
from core.models import Finding, RecommendationResponse
from test_pipeline_yaml import FakeRepo, ctx_for

# Shaped like the real monitoring pipeline: stages come from a job template in another repository, whose job names are
# template expressions, and the same step ("Remove build agent's access") is used by every stage.
MAIN = """\
resources:
  repositories:
    - repository: OnCallMonitoring
      type: git
      name: Cloud Technologies/OnCallMonitoring
      ref: refs/heads/main
stages:
  - stage: DeployA
    jobs:
      - template: pipelines/job-templates/default-monitoring.yml@OnCallMonitoring
  - stage: DeployB
    jobs:
      - template: pipelines/job-templates/default-monitoring.yml@OnCallMonitoring
"""
JOB_TEMPLATE = """\
jobs:
  - job: deploy_${{ replace(parameters.stampName, '-', '_') }}
    steps:
      - template: ../task-templates/check-kv-access.yaml
      - template: ../task-templates/validate-inputs.yml
"""
CHECK_KV = """\
steps:
  - script: echo checking
    displayName: Check
  - task: AzureCLI@2
    displayName: Remove build agent's access to storage account
    inputs:
      scriptType: bash
"""


def repo_with(files):
    return FakeRepo(files)


def context(files):
    repo = repo_with(files)
    return ctx_for(MAIN, "monitoring/pipeline.yml", repo.loader(MAIN, project="Cloud Technologies")), repo


class TestWhere:
    def test_a_step_in_an_external_template_names_the_file_the_repository_and_the_line(self):
        ctx, repo = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        loc = py.locate_step(ctx.facts, "DeployA", "Remove build agent's access to storage account")
        text = py.where_text(ctx, loc)
        assert "`pipelines/task-templates/check-kv-access.yaml` (a template from repository `OnCallMonitoring`, used by `monitoring/pipeline.yml`)" in text
        assert 'step "Remove build agent\'s access to storage account" (line 5)' in text

    def test_a_template_expression_is_never_printed_as_a_job_name(self):
        ctx, _ = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        loc = py.locate_step(ctx.facts, None, "Check")
        assert "${{" not in py.where_text(ctx, loc) and "replace(" not in py.where_text(ctx, loc)

    def test_a_step_shared_by_several_stages_does_not_pretend_to_know_which_one_failed(self):
        ctx, _ = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        text = py.where_text(ctx, py.locate_step(ctx.facts, "Some other stage name", "Remove build agent's access to storage account"))
        assert "used by 2 stages" in text and "stage `DeployA`" not in text and "stage `DeployB`" not in text

    def test_a_step_used_once_still_names_its_stage_and_job(self):
        text = py.where_text(ctx_for("stages:\n  - stage: Build\n    jobs:\n      - job: j\n        steps:\n          - script: x\n            displayName: Only\n"),
                             py.locate_step(py.parse_pipeline_yaml("stages:\n  - stage: Build\n    jobs:\n      - job: j\n        steps:\n          - script: x\n            displayName: Only\n", "p.yml"), None, "Only"))
        assert "stage `Build`" in text and "job `j`" in text


class TestNoContradiction:
    def test_a_found_step_never_carries_the_step_was_not_found_note_even_when_other_templates_are_unread(self):
        # check-kv-access is readable, validate-inputs is not: the unread one must not undermine the found step.
        ctx, _ = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        assert ctx.unresolved  # a template really is unread
        text = py.investigate_remediation("Remove build agent's access to storage account",
                                          "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group 'rg' was not found.", "persistent", ctx)
        assert "check-kv-access.yaml" in text and "was not found in the files that could be read" not in text and "could not be read" not in text

    def test_a_step_that_really_is_missing_still_says_so_and_names_the_unread_templates(self):
        ctx, _ = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        text = py.investigate_remediation("A step that is nowhere", GENERIC, "unknown", ctx)
        assert "was not found in the files that could be read" in text and "validate-inputs.yml" in text and "the analysis message says why" in text

    def test_the_note_names_at_most_three_templates(self):
        text = "steps:\n" + "".join(f"  - template: t{i}.yml\n" for i in range(6))
        ctx = ctx_for(text, loader=FakeRepo({}).loader("steps: []"))
        note = py.investigate_remediation("nope", GENERIC, "unknown", ctx)
        assert "`t0.yml`, `t1.yml`, `t2.yml` and 3 more;" in note and "t3.yml" not in note


GENERIC = "##[error]Script failed with exit code: 1"


class TestUnreadTemplatesAreNamedByThePathThatWasTried:
    def test_a_relative_reference_is_reported_as_the_file_it_resolved_to_not_as_dot_dot(self):
        ctx, _ = context({"pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE, "pipelines/task-templates/check-kv-access.yaml": CHECK_KV})
        names = ctx.unresolved
        assert names == ["pipelines/task-templates/validate-inputs.yml@OnCallMonitoring"]
        assert "was not found in repository 'Cloud Technologies/OnCallMonitoring' at branch 'main'" in ctx.facts.template_errors[names[0]]

    def test_the_same_relative_name_from_two_places_is_two_different_files(self):
        files = {"a/x.yml": "steps:\n  - template: ../shared/s.yml\n", "b/y.yml": "steps:\n  - template: ../shared/s.yml\n", "shared/s.yml": "steps:\n  - script: s\n    displayName: S\n"}
        text = "steps:\n  - template: a/x.yml\n  - template: b/y.yml\n"
        facts = py.parse_pipeline_yaml(text, "p.yml", FakeRepo(files).loader("steps: []"))
        assert facts.templates == [] and py.locate_step(facts, None, "S") is not None  # both resolve to shared/s.yml: read once, nothing reported unread

    def test_a_larger_pipeline_than_before_is_read_completely(self):
        files = {f"t{i}.yml": f"steps:\n  - script: s{i}\n    displayName: S{i}\n" for i in range(40)}
        text = "steps:\n" + "".join(f"  - template: t{i}.yml\n" for i in range(40))
        facts = py.parse_pipeline_yaml(text, "p.yml", FakeRepo(files).loader("steps: []"))
        assert facts.templates == [] and len(facts.files) == 41


class TestOurOwnBlocksAreNotStripped:
    """The card-3 case: step in an unread template, the model advised a retry. Our replacement block must survive intact."""

    @pytest.fixture
    def result(self, monkeypatch):
        from types import SimpleNamespace
        s = {"stages": [{"name": "Dispatch", "avg_duration_s": 300, "failure_rate_pct": 34, "tasks": [
            {"name": "Install MDC chart", "avg_duration_s": 160, "pct_of_parent_duration": 50, "failure_rate_pct": 34.3, "retry_rate_pct": 0, "error_excerpt": GENERIC}]}]}
        monkeypatch.setattr(ai_module, "get_settings", lambda: SimpleNamespace(
            sql_connection_string="c", min_history_runs=1, azure_openai_endpoint="https://x", azure_openai_deployment="d", azure_openai_api_version="v", azure_openai_api_key=""))
        monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: s)
        monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(count_runs=lambda pid, days: 9, get_pipeline_metrics=lambda pid, days: [], upsert_recommendations=lambda pid, f: None))
        monkeypatch.setattr(ai_module, "fetch_one", lambda q, p=(): {"organization_name": "org", "project_name": "Cloud Technologies"})
        repo = FakeRepo({"monitoring/pipeline.yml": MAIN, "pipelines/job-templates/default-monitoring.yml": JOB_TEMPLATE})
        repo.get_build_definition = lambda project, pid: {"process": {"type": 2, "yamlFilename": "monitoring/pipeline.yml"},
                                                          "repository": {"id": "r", "type": "TfsGit", "defaultBranch": "refs/heads/main"}}
        monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: repo)

        class Model:
            def __init__(self, *a, **k):
                pass

            def recommend(self, summary):
                return RecommendationResponse(findings=[Finding("flaky_step", "high", "Dispatch", "Install MDC chart", (
                    "**Diagnosis**: Script failure.\n**Remediation**: Add `retryCountOnTaskFailure: 2`.\n\n```yaml\n- task: HelmDeploy@0\n  retryCountOnTaskFailure: 2\n```\n**Impact**: Eliminates 34%."), "e")])

        monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Model)
        return AIService().analyze(1, 30, resolve_pat=lambda org: "t")

    def test_no_misleading_removed_snippet_note_and_the_block_is_ours_and_labelled(self, result):
        text = result["findings"][0]["recommendation"]
        assert "snippet was removed" not in text and "HelmDeploy@0" not in text and "Eliminates" not in text
        assert "# example, not from your file" in text and "system.debug: true" in text
        assert text.count("```") == 2  # exactly one block to paste

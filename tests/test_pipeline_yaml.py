"""Pipeline YAML awareness: parse the real file and its templates, locate steps, skip what is already applied, diff against the file."""
import pytest
import requests

import app.services.ai_service as ai_module
from app.services import pipeline_yaml as py
from app.services.ai_service import AIService, _telemetry_fallback
from core.models import Finding, RecommendationResponse

NPM_PIPELINE = """\
trigger:
  - main
stages:
  - stage: Build
    displayName: Build and test
    jobs:
      - job: build
        steps:
          - checkout: self
          - script: npm ci
            displayName: Install packages
          - script: npm run build
            displayName: Compile
  - stage: Deploy
    dependsOn: Build
    jobs:
      - deployment: release
        strategy:
          runOnce:
            deploy:
              steps:
                - task: AzureCLI@2
                  displayName: Helm Upgrade
                  retryCountOnTaskFailure: 3
                  inputs:
                    scriptType: bash
"""

CACHED_PIPELINE = """\
jobs:
  - job: build
    steps:
      - task: Cache@2
        displayName: Cache npm
        inputs:
          key: 'npm | package-lock.json'
          path: .npm
      - script: npm ci
        displayName: Install packages
"""

TRANSIENT_ERROR = "dial tcp 10.0.0.4:443: i/o timeout"
GENERIC_ERROR = "Process completed with exit code 1."


def facts_of(text, path="azure-pipelines.yml", loader=None):
    facts = py.parse_pipeline_yaml(text, path, loader)
    assert facts is not None
    return facts


def ctx_for(text, path="azure-pipelines.yml", loader=None):
    return py.YamlContext(True, path=path, branch="main", content=text, facts=facts_of(text, path, loader))


class TestParsing:
    def test_reads_stages_jobs_steps_including_deployment_jobs(self):
        facts = facts_of(NPM_PIPELINE)
        assert [s.name for s in facts.stages] == ["Build", "Deploy"]
        build = facts.stages[0].jobs[0]
        assert build.name == "build" and len(build.steps) == 3 and build.steps[1].label == "Install packages"
        deploy_step = facts.stages[1].jobs[0].steps[0]
        assert deploy_step.task == "AzureCLI@2" and deploy_step.retry == 3

    def test_detects_ecosystems_and_cache(self):
        facts = facts_of(NPM_PIPELINE)
        assert facts.stages[0].jobs[0].steps[1].ecosystem == "npm"
        assert not facts.stages[0].jobs[0].has_cache
        assert facts_of(CACHED_PIPELINE).stages[0].jobs[0].has_cache

    def test_top_level_jobs_and_steps_shapes(self):
        assert facts_of("steps:\n  - script: pip install -r r.txt\n    displayName: deps\n").stages[0].jobs[0].steps[0].ecosystem == "pip"
        assert facts_of(CACHED_PIPELINE).stages[0].name == ""

    def test_conditions_are_flattened_and_unread_templates_reported(self):
        text = "steps:\n  - ${{ if eq(variables.x, 1) }}:\n      - script: mvn package\n        displayName: Package\n  - template: shared/steps.yml\n"
        facts = facts_of(text)
        assert facts.stages[0].jobs[0].steps[0].ecosystem == "maven"
        assert facts.templates == ["shared/steps.yml"]  # no loader: reported, never guessed

    @pytest.mark.parametrize("bad", ["", "just a string", "- a\n- b\n", "key: [unclosed", "a: b: c"])
    def test_garbage_is_not_a_pipeline(self, bad):
        assert py.parse_pipeline_yaml(bad) is None


MAIN_WITH_TEMPLATE = """\
resources:
  repositories:
    - repository: shared
      type: git
      name: Platform/shared-pipelines
      ref: refs/heads/main
    - repository: gh
      type: github
      name: org/repo
stages:
  - stage: Deploy
    jobs:
      - job: monitoring
        steps:
          - template: templates/deploy-monitoring.yml
            parameters:
              env: dev
          - script: echo done
            displayName: Done
"""

MONITORING_TEMPLATE = """\
parameters:
  - name: env
steps:
  - task: HelmDeploy@0
    displayName: Install MDC chart
    inputs:
      command: upgrade
"""


class FakeRepo:
    """Serves files by path like Azure Repos; records how it was asked."""

    def __init__(self, files):
        self.files, self.calls = files, []

    def get_repository_file(self, project, repo, path, branch, version_type="branch"):
        self.calls.append((project, repo, path, branch) if version_type == "branch" else (project, repo, path, branch, version_type))
        if path not in self.files:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return self.files[path]

    def loader(self, text=MAIN_WITH_TEMPLATE, project="Proj"):
        resources = py._repository_resources(py._safe_load(text))
        return py.make_template_loader(self, project, "repo-1", "main", resources)


class TestTemplates:
    def test_a_step_defined_in_a_template_is_found_and_attributed_to_that_file(self):
        repo = FakeRepo({"templates/deploy-monitoring.yml": MONITORING_TEMPLATE})
        facts = facts_of(MAIN_WITH_TEMPLATE, loader=repo.loader())
        stage, job, step = py.locate_step(facts, "Deploy", "install mdc chart")
        assert (stage.name, job.name, step.display, step.file) == ("Deploy", "monitoring", "Install MDC chart", "templates/deploy-monitoring.yml")
        assert facts.templates == [] and set(facts.files) == {"azure-pipelines.yml", "templates/deploy-monitoring.yml"}
        assert [s.label for s in job.steps] == ["Install MDC chart", "Done"]  # spliced in, in order

    def test_advice_is_a_diff_against_the_template_not_the_main_file(self):
        repo = FakeRepo({"templates/deploy-monitoring.yml": MONITORING_TEMPLATE})
        ctx = ctx_for(MAIN_WITH_TEMPLATE, loader=repo.loader())
        text = py.retry_remediation("Install MDC chart", ctx, TRANSIENT_ERROR)
        assert "`templates/deploy-monitoring.yml` (a template used by `azure-pipelines.yml`)" in text
        assert "--- a/templates/deploy-monitoring.yml" in text and "+    retryCountOnTaskFailure: 2" in text

    def test_unreadable_template_is_reported_not_guessed(self):
        facts = facts_of(MAIN_WITH_TEMPLATE, loader=FakeRepo({}).loader())
        assert facts.templates == ["templates/deploy-monitoring.yml"]
        assert py.locate_step(facts, "Deploy", "Install MDC chart") is None
        assert [s.label for s in facts.stages[0].jobs[0].steps] == ["Done"]

    def test_relative_paths_resolve_from_the_including_file_and_rooted_paths_from_the_repo_root(self):
        repo = FakeRepo({
            "templates/a.yml": "steps:\n  - template: b.yml\n  - template: /common/c.yml\n",
            "templates/b.yml": "steps:\n  - script: echo b\n    displayName: B\n",
            "common/c.yml": "steps:\n  - script: echo c\n    displayName: C\n",
        })
        facts = facts_of("steps:\n  - template: templates/a.yml\n", loader=repo.loader("steps: []"))
        assert [(s.label, s.file) for s in facts.stages[0].jobs[0].steps] == [("B", "templates/b.yml"), ("C", "common/c.yml")]

    def test_templates_in_another_repository_use_its_name_ref_and_root(self):
        repo = FakeRepo({"steps/x.yml": "steps:\n  - script: echo x\n    displayName: X\n    retryCountOnTaskFailure: 1\n"})
        text = MAIN_WITH_TEMPLATE.replace("templates/deploy-monitoring.yml", "steps/x.yml@shared")
        facts = facts_of(text, loader=repo.loader(text))
        assert repo.calls == [("Platform", "shared-pipelines", "steps/x.yml", "main")]
        step = py.locate_step(facts, None, "X")[2]
        assert step.file == "steps/x.yml@shared" and step.retry == 1

    def test_non_azure_repos_and_expression_references_are_never_fetched(self):
        repo = FakeRepo({})
        for ref in ("steps/x.yml@gh", "steps/x.yml@unknown", "${{ parameters.tpl }}.yml"):
            text = MAIN_WITH_TEMPLATE.replace("templates/deploy-monitoring.yml", ref)
            assert facts_of(text, loader=repo.loader(text)).templates == [ref]
        assert repo.calls == []

    def test_cycles_and_deep_chains_terminate(self):
        loop = FakeRepo({"loop.yml": "steps:\n  - template: loop.yml\n  - script: echo\n    displayName: Once\n"})
        facts = facts_of("steps:\n  - template: loop.yml\n", loader=loop.loader("steps: []"))
        assert [s.label for s in facts.stages[0].jobs[0].steps] == ["Once"]
        chain = FakeRepo({f"t{i}.yml": f"steps:\n  - template: t{i + 1}.yml\n" for i in range(30)})
        deep = facts_of("steps:\n  - template: t0.yml\n", loader=chain.loader("steps: []"))
        assert len(deep.files) <= py.MAX_TEMPLATE_FILES + 1 and deep.templates  # stopped, and said what it could not read

    def test_extends_template_is_read_as_the_pipeline_body(self):
        repo = FakeRepo({"pipeline.yml": "stages:\n  - stage: S\n    jobs:\n      - job: j\n        steps:\n          - script: npm ci\n            displayName: Install\n"})
        facts = facts_of("extends:\n  template: pipeline.yml\n", loader=repo.loader("steps: []"))
        assert py.locate_step(facts, "S", "Install")[2].ecosystem == "npm"

    def test_fetch_reads_the_main_file_and_its_templates(self):
        files = {"azure-pipelines.yml": MAIN_WITH_TEMPLATE, "templates/deploy-monitoring.yml": MONITORING_TEMPLATE}
        repo = FakeRepo(files)
        repo.get_build_definition = lambda project, pid: {"process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
                                                          "repository": {"id": "r1", "type": "TfsGit", "defaultBranch": "refs/heads/main"}}
        ctx = py.fetch_pipeline_yaml(repo, "Proj", 9)
        assert ctx.ok and set(ctx.facts.files) == set(files) and ctx.unresolved == []
        prompt = py.yaml_for_prompt(ctx)
        assert prompt["file"] == "azure-pipelines.yml" and [t["file"] for t in prompt["templates"]] == ["templates/deploy-monitoring.yml"]

    def test_prompt_payload_caps_every_file(self):
        big = "steps:\n" + "  - script: echo hi\n" * 5000
        repo = FakeRepo({"templates/deploy-monitoring.yml": big})
        ctx = ctx_for(MAIN_WITH_TEMPLATE, loader=repo.loader())
        payload = py.yaml_for_prompt(ctx)
        assert len(payload["templates"][0]["content"]) == py.TEMPLATE_PROMPT_CHARS and payload["truncated"] is True


class TestLocate:
    def test_matches_display_name_task_and_script_line_case_insensitively(self):
        facts = facts_of(NPM_PIPELINE)
        assert py.locate_step(facts, "Deploy", "helm upgrade")[2].task == "AzureCLI@2"
        assert py.locate_step(facts, None, "Install packages")[1].name == "build"
        assert py.locate_step(facts, None, "npm run build")[2].display == "Compile"
        assert py.locate_step(facts, None, "no such step") is None
        assert py.locate_step(None, None, "x") is None

    def test_same_step_name_in_two_stages_prefers_the_named_stage(self):
        text = ("stages:\n  - stage: A\n    jobs:\n      - job: j1\n        steps:\n          - script: x\n            displayName: Run\n"
                "  - stage: B\n    jobs:\n      - job: j2\n        steps:\n          - script: y\n            displayName: Run\n")
        assert py.locate_step(facts_of(text), "B", "Run")[1].name == "j2"


def _apply(text, new_lines, before_display):
    lines = text.splitlines()
    _at, _col, start = py._find_step_lines(lines, before_display)
    return "\n".join(lines[:start] + new_lines + lines[start:]) + "\n"


class TestDiffs:
    def test_retry_diff_inserts_the_property_with_the_steps_own_indentation(self):
        diff = py.diff_add_retry(NPM_PIPELINE, "Install packages", "azure-pipelines.yml")
        assert diff.startswith("--- a/azure-pipelines.yml\n+++ b/azure-pipelines.yml")
        assert "+            retryCountOnTaskFailure: 2" in diff
        assert not any(line.startswith("-") and not line.startswith("---") for line in diff.splitlines()), "the edit only adds lines"

    def test_cache_diff_inserts_a_whole_step_before_the_restore_step(self):
        diff = py.diff_add_cache(NPM_PIPELINE, "Install packages", "npm", "azure-pipelines.yml")
        assert "+          - task: Cache@2" in diff and "+              path: $(Pipeline.Workspace)/.npm" in diff
        patched = _apply(NPM_PIPELINE, py.cache_step_lines("npm", 10), before_display="Install packages")
        assert py.parse_pipeline_yaml(patched).stages[0].jobs[0].has_cache  # still valid YAML, now with a cache step

    def test_unlocatable_step_gives_no_diff(self):
        assert py.diff_add_retry(NPM_PIPELINE, "Nope", "p.yml") is None
        assert py.diff_add_retry(NPM_PIPELINE, "", "p.yml") is None
        assert py.diff_add_cache(NPM_PIPELINE, "Install packages", "docker", "p.yml") is None


class _Client:
    def __init__(self, definition=None, content=NPM_PIPELINE, error=None):
        self.definition = definition or {"process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
                                         "repository": {"id": "r1", "type": "TfsGit", "defaultBranch": "refs/heads/dev"}}
        self.content, self.error, self.asked = content, error, None

    def get_build_definition(self, project, pipeline_id):
        return self.definition

    def get_repository_file(self, project, repo_id, path, branch, version_type="branch"):
        self.asked = (repo_id, path, branch)
        if self.error:
            raise self.error
        return self.content


class TestFetch:
    def test_reads_the_default_branch_file(self):
        client = _Client()
        ctx = py.fetch_pipeline_yaml(client, "proj", 7)
        assert ctx.ok and ctx.path == "azure-pipelines.yml" and ctx.branch == "dev"
        assert client.asked == ("r1", "azure-pipelines.yml", "dev")

    def test_explains_every_way_it_can_fail_and_never_raises(self):
        classic = _Client({"process": {"type": 1}, "repository": {}})
        assert "classic" in py.fetch_pipeline_yaml(classic, "p", 1).reason
        github = _Client({"process": {"type": 2, "yamlFilename": "a.yml"}, "repository": {"type": "GitHub"}})
        assert "GitHub" in py.fetch_pipeline_yaml(github, "p", 1).reason
        response = requests.Response()
        response.status_code = 403
        assert "Code (Read)" in py.fetch_pipeline_yaml(_Client(error=requests.HTTPError(response=response)), "p", 1).reason
        response.status_code = 404
        assert "not found" in py.fetch_pipeline_yaml(_Client(error=requests.HTTPError(response=response)), "p", 1).reason
        assert "could not be read" in py.fetch_pipeline_yaml(_Client(error=RuntimeError("boom")), "p", 1).reason
        assert "could not be parsed" in py.fetch_pipeline_yaml(_Client(content="key: [oops"), "p", 1).reason

    def test_prompt_payload_is_absent_without_a_file(self):
        assert py.yaml_for_prompt(py.YamlContext(False, "no")) is None


class TestAdvice:
    def test_transient_failure_gets_a_real_diff_naming_the_location(self):
        text = py.retry_remediation("Install packages", ctx_for(NPM_PIPELINE), TRANSIENT_ERROR)
        assert '`azure-pipelines.yml` (main) → stage `Build` → job `build` → step "Install packages" (line 11)' in text
        assert "```diff" in text and "retryCountOnTaskFailure: 2" in text

    def test_a_step_that_already_retries_is_not_told_to_retry_more(self):
        text = py.retry_remediation("Helm Upgrade", ctx_for(NPM_PIPELINE), TRANSIENT_ERROR)
        assert "already retries 3 time(s)" in text and "retryCountOnTaskFailure: 2" not in text

    def test_a_step_seen_succeeding_on_retry_counts_as_intermittent(self):
        assert "```diff" in py.retry_remediation("Install packages", ctx_for(NPM_PIPELINE), GENERIC_ERROR, intermittent=True)

    @pytest.mark.parametrize("error,expect", [(GENERIC_ERROR, "does not say whether"), ("Error: chart not found", "real fault, not an intermittent one"), (None, "only shows a generic exit code")])
    def test_no_retry_advice_unless_the_failure_looks_transient(self, error, expect):
        text = py.retry_remediation("Install packages", ctx_for(NPM_PIPELINE), error)
        assert expect in text and "retryCountOnTaskFailure: 2" not in text
        assert "In `azure-pipelines.yml`" in text  # still says where the step is
        assert "system.debug: true" in text and "# example, not from your file" in text  # and still gives something to paste: verbose logging

    def test_no_yaml_means_an_honest_labelled_example_not_an_invented_step(self):
        text = py.retry_remediation("Helm Upgrade", py.YamlContext(False, "classic pipeline"), TRANSIENT_ERROR)
        assert "was not used: classic pipeline" in text and "example, not from your file" in text
        assert "AzureCLI" not in text and "helm upgrade --install" not in text.lower() and "--timeout" not in text

    def test_unread_template_is_named_in_the_advice(self):
        ctx = ctx_for(MAIN_WITH_TEMPLATE, loader=FakeRepo({}).loader())
        text = py.retry_remediation("Install MDC chart", ctx, TRANSIENT_ERROR)
        assert "`templates/deploy-monitoring.yml`" in text and "could not be read" in text

    def test_cache_advice_is_skipped_when_the_job_already_caches(self):
        assert py.cache_remediation("Install packages", "npm", ctx_for(CACHED_PIPELINE)) is None

    def test_cache_advice_uses_the_detected_tool_and_states_its_assumption(self):
        text = py.cache_remediation("Install packages", None, ctx_for(NPM_PIPELINE))
        assert "```diff" in text and "$(Pipeline.Workspace)/.npm" in text and "package-lock.json" in text and "change it if yours differs" in text

    def test_unknown_tool_gets_a_labelled_placeholder_example(self):
        text = py.cache_remediation("Pull base images", None, None)
        assert "```yaml" in text and "# example, not from your file" in text and "replace the placeholders" in text


class TestReconcileModelFindings:
    def finding(self, **kw):
        base = dict(category="caching_opportunity", severity="medium", stage_name="Build", task_name="Install packages",
                    recommendation="**Diagnosis**: slow\n**Remediation**: add Cache@2\n**Impact**: faster", evidence="e")
        return {**base, **kw}

    def test_drops_caching_advice_the_file_already_applies(self):
        kept, skipped = py.apply_yaml_context([self.finding()], ctx_for(CACHED_PIPELINE))
        assert kept == [] and "already has a Cache@2 step" in skipped[0]

    def test_adds_where_and_keeps_the_rest(self):
        kept, skipped = py.apply_yaml_context([self.finding(stage_name="Build")], ctx_for(NPM_PIPELINE))
        assert skipped == [] and "**Remediation**: In `azure-pipelines.yml`" in kept[0]["recommendation"]
        assert kept[0]["recommendation"].endswith("**Impact**: faster")

    def test_flags_retry_that_is_already_there_and_ignores_unknown_steps_or_missing_yaml(self):
        flaky = self.finding(category="flaky_step", stage_name="Deploy", task_name="Helm Upgrade")
        kept, _ = py.apply_yaml_context([flaky], ctx_for(NPM_PIPELINE))
        assert "retries are not the fix here" in kept[0]["recommendation"]
        unknown = self.finding(task_name="not in the file")
        assert py.apply_yaml_context([unknown], ctx_for(NPM_PIPELINE)) == ([unknown], [])
        assert py.apply_yaml_context([unknown], None) == ([unknown], [])

    def test_invented_snippet_is_removed_when_the_step_may_live_in_an_unread_template(self):
        ctx = ctx_for(MAIN_WITH_TEMPLATE, loader=FakeRepo({}).loader())
        invented = self.finding(category="flaky_step", stage_name="Deploy", task_name="Install MDC chart", recommendation=(
            "**Diagnosis**: fails\n**Remediation**: add a retry:\n\n```yaml\n- task: HelmDeploy@0\n  displayName: 'Install MDC chart'\n  retryCountOnTaskFailure: 2\n```\n**Impact**: x"))
        kept, _ = py.apply_yaml_context([invented], ctx)
        text = kept[0]["recommendation"]
        assert "HelmDeploy@0" not in text and "```" not in text
        assert "was not found in the files that could be read" in text and "`templates/deploy-monitoring.yml`" in text

    def test_a_snippet_stays_when_nothing_is_unread(self):
        unknown = self.finding(task_name="not in the file", recommendation="**Remediation**: x\n```yaml\nkey: v\n```")
        assert py.apply_yaml_context([unknown], ctx_for(NPM_PIPELINE))[0][0]["recommendation"].count("```") == 2


SCREENSHOT_SUMMARY = {"stages": [{"name": "Deploy monitoring", "avg_duration_s": 300, "tasks": [
    {"name": "Install MDC chart", "avg_duration_s": 200, "pct_of_parent_duration": 66, "failure_rate_pct": 31.8, "retry_rate_pct": 0,
     "error_excerpt": GENERIC_ERROR}]}]}


class TestRetryPolicyOnModelFindings:
    def model_finding(self):
        return {"category": "flaky_step", "severity": "high", "stage_name": "Deploy monitoring", "task_name": "Install MDC chart", "evidence": "e",
                "recommendation": ("**Diagnosis**: The task fails frequently with a generic exit code 1.\n**Remediation**: Add `retryCountOnTaskFailure: 2` to the task.\n\n"
                                   "```yaml\n- task: HelmDeploy@0\n  retryCountOnTaskFailure: 2\n```\n**Impact**: This will reduce the failure rate by mitigating transient errors.")}

    def test_the_screenshot_case_a_generic_exit_code_is_not_called_transient(self):
        [fixed] = py.enforce_retry_policy([self.model_finding()], SCREENSHOT_SUMMARY)
        text = fixed["recommendation"]
        assert "retryCountOnTaskFailure: 2" not in text and "HelmDeploy@0" not in text
        assert "**Diagnosis**: The task fails frequently with a generic exit code 1." in text  # the model's diagnosis is kept
        assert "does not say whether" in text and "system.debug: true" in text

    def test_a_transient_error_keeps_the_retry_advice(self):
        summary = {"stages": [{"name": "S", "tasks": [{"name": "Install MDC chart", "error_excerpt": TRANSIENT_ERROR}]}]}
        finding = self.model_finding()
        assert py.enforce_retry_policy([finding], summary) == [finding]

    def test_a_step_that_succeeds_on_retry_keeps_the_retry_advice(self):
        summary = {"stages": [{"name": "S", "tasks": [{"name": "Install MDC chart", "error_excerpt": GENERIC_ERROR, "retry_rate_pct": 12}]}]}
        finding = self.model_finding()
        assert py.enforce_retry_policy([finding], summary) == [finding]

    def test_other_findings_are_untouched(self):
        other = {**self.model_finding(), "category": "caching_opportunity"}
        assert py.enforce_retry_policy([other], SCREENSHOT_SUMMARY) == [other]

    def test_a_recommendation_without_sections_still_gets_the_corrected_advice(self):
        bare = {**self.model_finding(), "recommendation": "Just add retryCountOnTaskFailure: 2."}
        text = py.enforce_retry_policy([bare], SCREENSHOT_SUMMARY)[0]["recommendation"]
        assert "**Remediation**:" in text and "Just add" not in text and "retryCountOnTaskFailure: 2" not in text


SUMMARY = {"stages": [{"name": "Build", "avg_duration_s": 600, "tasks": [
    {"name": "Install packages", "avg_duration_s": 400, "pct_of_parent_duration": 66.7, "failure_rate_pct": 0, "retry_rate_pct": 0}]}]}


class TestFallback:
    def test_fallback_uses_the_real_file_and_never_shows_the_old_helm_example(self):
        findings = _telemetry_fallback(SUMMARY, ctx_for(NPM_PIPELINE))
        assert findings[0]["category"] == "caching_opportunity" and "```diff" in findings[0]["recommendation"]
        assert "helm" not in findings[0]["recommendation"].lower()

    def test_fallback_transient_failure_without_a_file_gets_a_labelled_example(self):
        flaky = {"stages": [{"name": "Deploy", "avg_duration_s": 60, "tasks": [
            {"name": "Helm Upgrade", "avg_duration_s": 50, "failure_rate_pct": 30, "retry_rate_pct": 0, "error_excerpt": TRANSIENT_ERROR}]}]}
        rec = _telemetry_fallback(flaky, None)[0]["recommendation"]
        assert "retryCountOnTaskFailure: 2" in rec and "example, not from your file" in rec and "AzureCLI@2" not in rec and "i/o timeout" in rec

    def test_fallback_generic_failure_says_to_find_the_cause_not_to_retry(self):
        rec = _telemetry_fallback(SCREENSHOT_SUMMARY, None)[0]["recommendation"]
        assert "retryCountOnTaskFailure: 2" not in rec and "system.debug: true" in rec
        assert "does not show the cause" in rec and "fixing the cause removes those failures" not in rec and "would only repeat" not in rec
        assert "**Diagnosis**" in rec and "**Remediation**" in rec and "**Impact**" in rec

    def test_already_cached_job_yields_no_caching_finding(self):
        assert _telemetry_fallback(SUMMARY, ctx_for(CACHED_PIPELINE)) == []

    def test_a_slow_non_cacheable_step_does_not_get_a_cache_snippet(self):
        deploy = {"stages": [{"name": "Deploy", "avg_duration_s": 900, "tasks": [
            {"name": "Wait for rollout", "avg_duration_s": 800, "pct_of_parent_duration": 88, "failure_rate_pct": 0, "retry_rate_pct": 0}]}]}
        finding = _telemetry_fallback(deploy, None)[0]
        assert finding["category"] == "bottleneck" and "Cache@2" not in finding["recommendation"]


def _settings():
    from types import SimpleNamespace
    return SimpleNamespace(sql_connection_string="c", min_history_runs=1, azure_openai_endpoint="https://x", azure_openai_deployment="d",
                           azure_openai_api_version="v", azure_openai_api_key="")


class TestAnalyzeEndToEnd:
    @pytest.fixture
    def wired(self, monkeypatch):
        from types import SimpleNamespace
        sent, saved = {}, {}
        monkeypatch.setattr(ai_module, "get_settings", _settings)
        monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: {**SUMMARY})
        monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(
            count_runs=lambda pid, days: 10, get_pipeline_metrics=lambda pid, days: [], upsert_recommendations=lambda pid, f: saved.update(f=f)))
        monkeypatch.setattr(ai_module, "fetch_one", lambda q, p=(): {"organization_name": "org", "project_name": "proj"})
        monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: _Client())

        class Model:
            findings = [Finding("caching_opportunity", "medium", "Build", "Install packages",
                                "**Diagnosis**: slow\n**Remediation**: cache\n**Impact**: faster", "e")]

            def __init__(self, *a, **k):
                pass

            def recommend(self, summary):
                sent["summary"] = summary
                return RecommendationResponse(findings=self.findings)

        monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Model)
        return sent, saved

    def test_the_model_sees_the_real_file_and_the_answer_is_located(self, wired):
        sent, saved = wired
        result = AIService().analyze(7, 30, resolve_pat=lambda org: "token")
        assert sent["summary"]["pipeline_yaml"]["file"] == "azure-pipelines.yml"
        assert "Based on azure-pipelines.yml (dev)." in result["message"]
        assert "In `azure-pipelines.yml`" in result["findings"][0]["recommendation"] and saved["f"] == result["findings"]

    def test_without_a_token_it_still_works_and_says_the_file_was_not_used(self, wired):
        sent, _ = wired
        result = AIService().analyze(7, 30, resolve_pat=lambda org: None)
        assert "pipeline_yaml" not in sent["summary"]
        assert "Pipeline YAML not used: no Azure DevOps token" in result["message"] and result["findings"]
        assert "not used" in AIService().analyze(7, 30)["message"]

    def test_advice_the_file_already_applies_is_dropped_and_reported(self, wired, monkeypatch):
        monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: _Client(content=CACHED_PIPELINE))
        result = AIService().analyze(7, 30, resolve_pat=lambda org: "token")
        assert result["findings"] == [] and "Skipped, already in place" in result["message"]

    def test_templates_are_read_and_counted_in_the_message(self, wired, monkeypatch):
        repo = FakeRepo({"azure-pipelines.yml": MAIN_WITH_TEMPLATE, "templates/deploy-monitoring.yml": MONITORING_TEMPLATE})
        repo.get_build_definition = lambda project, pid: {"process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
                                                          "repository": {"id": "r1", "type": "TfsGit", "defaultBranch": "refs/heads/main"}}
        monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: repo)
        sent, _ = wired
        result = AIService().analyze(7, 30, resolve_pat=lambda org: "token")
        assert "and 1 template file(s)." in result["message"]
        assert sent["summary"]["pipeline_yaml"]["templates"][0]["file"] == "templates/deploy-monitoring.yml"

    def test_unread_templates_are_reported_in_the_message(self, wired, monkeypatch):
        repo = FakeRepo({"azure-pipelines.yml": MAIN_WITH_TEMPLATE})
        repo.get_build_definition = lambda project, pid: {"process": {"type": 2, "yamlFilename": "azure-pipelines.yml"},
                                                          "repository": {"id": "r1", "type": "TfsGit", "defaultBranch": "refs/heads/main"}}
        monkeypatch.setattr(ai_module, "AzureDevOpsClient", lambda org, token: repo)
        result = AIService().analyze(7, 30, resolve_pat=lambda org: "token")
        assert "Templates that could not be read: templates/deploy-monitoring.yml (" in result["message"] and "was not found in repository" in result["message"]


def _task(name, fail=0.0, retry=0.0, duration=100, error=GENERIC_ERROR):
    return {"name": name, "avg_duration_s": duration, "pct_of_parent_duration": 10, "failure_rate_pct": fail, "retry_rate_pct": retry, "error_excerpt": error if fail else ""}


def _flaky(stage, task, severity="high"):
    return {"category": "flaky_step", "severity": severity, "stage_name": stage, "task_name": task, "recommendation": "**Diagnosis**: d", "evidence": "e"}


# Six steps are above the high-severity threshold; the model only returned four of them (the case seen on a real pipeline).
SIX_FAILING = {"stages": [
    {"name": "Stamp", "avg_duration_s": 900, "failure_rate_pct": 38.6, "tasks": [
        _task("Install MDC chart", fail=31.8), _task("Remove access", fail=20), _task("Deploy role", fail=18), _task("Install CLI", fail=16),
        _task("Validate alert", fail=15), _task("Low failure step", fail=5), _task("Healthy step", duration=500)]},
    {"name": "Records", "avg_duration_s": 100, "failure_rate_pct": 25, "tasks": [_task("Flaky on retry", fail=2, retry=25, error="")]},
]}


class TestCoverageGuarantee:
    def model_four(self):
        return [_flaky("Stamp", "Remove access"), _flaky("Stamp", "Deploy role"), _flaky("Stamp", "Install CLI"), _flaky("Stamp", "Validate alert")]

    def test_every_high_severity_step_is_covered_even_when_the_model_stops_at_four(self):
        findings, added = ai_module.ensure_coverage(self.model_four(), SIX_FAILING, None)
        covered = {(f["stage_name"], f["task_name"]) for f in findings}
        assert ("Stamp", "Install MDC chart") in covered and ("Records", "Flaky on retry") in covered
        assert (added, len(findings)) == (2, 6)
        assert not any(f["task_name"] in ("Low failure step", "Healthy step") for f in findings)  # below the thresholds: not forced in

    def test_worst_failure_rate_comes_first_whatever_order_the_model_used(self):
        findings, _a = ai_module.ensure_coverage(self.model_four(), SIX_FAILING, None)
        ordered, omitted = ai_module.order_and_cap(findings, SIX_FAILING, 15)
        assert [f["task_name"] for f in ordered][:3] == ["Install MDC chart", "Remove access", "Deploy role"] and omitted == 0

    def test_the_added_finding_has_cause_remediation_yaml_and_a_measured_impact(self):
        findings, _a = ai_module.ensure_coverage(self.model_four(), SIX_FAILING, None)
        mdc = next(f for f in findings if f["task_name"] == "Install MDC chart")
        text = mdc["recommendation"]
        assert mdc["category"] == "flaky_step" and mdc["severity"] == "high" and "31.8%" in text
        assert "**Diagnosis**" in text and "**Remediation**" in text and "```yaml" in text and "**Impact**" in text
        assert "retryCountOnTaskFailure: 2" not in text  # generic exit code: find the cause, never a blind retry

    def test_nothing_is_duplicated_when_the_model_already_covered_everything(self):
        every = [_flaky("Stamp", t) for t in ("Install MDC chart", "Remove access", "Deploy role", "Install CLI", "Validate alert")] + [_flaky("Records", "Flaky on retry")]
        findings, added = ai_module.ensure_coverage(every, SIX_FAILING, None)
        assert added == 0 and len(findings) == 6

    def test_a_non_failure_finding_for_a_failing_step_does_not_count_as_covering_its_failures(self):
        bottleneck = {**_flaky("Stamp", "Install MDC chart"), "category": "bottleneck"}
        findings, added = ai_module.ensure_coverage([bottleneck], {"stages": [SIX_FAILING["stages"][0]]}, None)
        assert any(f["task_name"] == "Install MDC chart" and f["category"] == "flaky_step" for f in findings) and added >= 1

    def test_a_differently_spelled_stage_name_does_not_cause_a_duplicate(self):
        findings, added = ai_module.ensure_coverage([_flaky("stamp stage", "Install MDC chart")], {"stages": [
            {"name": "Stamp", "tasks": [_task("Install MDC chart", fail=40)]}]}, None)
        assert added == 0 and len(findings) == 1

    def test_the_same_step_name_in_two_stages_is_judged_per_stage(self):
        summary = {"stages": [{"name": "Dev", "tasks": [_task("Install chart", fail=30)]}, {"name": "Test", "tasks": [_task("Install chart", fail=40)]}]}
        findings, added = ai_module.ensure_coverage([_flaky("Dev", "Install chart")], summary, None)
        assert added == 1 and {f["stage_name"] for f in findings} == {"Dev", "Test"}

    def test_the_total_is_capped_and_the_overflow_is_reported(self):
        many = {"stages": [{"name": "S", "tasks": [_task(f"step {i}", fail=20 + i, error=f"distinct failure number {i} " + "x" * i) for i in range(20)]}]}
        findings, added = ai_module.ensure_coverage([], many, None)
        ordered, omitted = ai_module.order_and_cap(findings, many, ai_module.MAX_FINDINGS)
        assert len(ordered) == ai_module.MAX_FINDINGS and added == 20 and omitted == 5
        assert ordered[0]["task_name"] == "step 19"  # the worst are the ones kept

    def test_no_failures_means_nothing_is_added(self):
        assert ai_module.ensure_coverage([], SUMMARY, None) == ([], 0)


class TestPrioritizedInput:
    def test_stages_and_tasks_reach_the_model_worst_failure_rate_first(self):
        shuffled = {"pipeline": "p", "stages": [SIX_FAILING["stages"][1], {**SIX_FAILING["stages"][0], "tasks": list(reversed(SIX_FAILING["stages"][0]["tasks"]))}]}
        out = ai_module.prioritize_summary(shuffled)
        assert out["pipeline"] == "p"
        assert [s["name"] for s in out["stages"]] == ["Stamp", "Records"]
        assert [t["name"] for t in out["stages"][0]["tasks"]][:3] == ["Install MDC chart", "Remove access", "Deploy role"]
        assert shuffled["stages"][0]["name"] == "Records"  # the caller's data is not modified


class TestAnalyzeCoverage:
    def test_analyze_adds_the_missing_steps_orders_worst_first_and_says_so(self, monkeypatch):
        from types import SimpleNamespace
        saved, sent = {}, {}
        monkeypatch.setattr(ai_module, "get_settings", _settings)
        monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: {"stages": list(reversed(SIX_FAILING["stages"]))})
        monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(
            count_runs=lambda pid, days: 10, get_pipeline_metrics=lambda pid, days: [], upsert_recommendations=lambda pid, f: saved.update(f=f)))
        monkeypatch.setattr(ai_module, "fetch_one", lambda q, p=(): None)

        class Model:
            def __init__(self, *a, **k):
                pass

            def recommend(self, summary):
                sent["first_task"] = summary["stages"][0]["tasks"][0]["name"]
                return RecommendationResponse(findings=[Finding("flaky_step", "high", "Stamp", t, "**Diagnosis**: d", "e") for t in ("Remove access", "Deploy role", "Install CLI", "Validate alert")])

        monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Model)
        result = AIService().analyze(7, 30)
        assert sent["first_task"] == "Install MDC chart"  # the model is shown the worst step first
        assert [f["task_name"] for f in result["findings"]][0] == "Install MDC chart" and len(result["findings"]) == 6
        assert "2 failing step(s)" in result["message"] and saved["f"] == result["findings"]
        assert all("```" in f["recommendation"] for f in result["findings"]), "every finding carries a code block to paste"

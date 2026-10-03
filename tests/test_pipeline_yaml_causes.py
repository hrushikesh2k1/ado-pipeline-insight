"""Round two, from the second set of real results: one cause per card, no unverified code on a failing step, and an honest reason
when a step cannot be placed in the files."""
from types import SimpleNamespace

import app.services.ai_service as ai_module
from app.services import pipeline_yaml as py
from app.services.finding_quality import adopt_causes, normalize_findings
from app.services.root_causes import identify_cause
from core.models import Finding, RecommendationResponse
from test_pipeline_yaml import NPM_PIPELINE, FakeRepo, ctx_for

AUTH_WITH_UNSET_VARIABLES = (
    "ERROR: (AuthorizationFailed) The client '***' with object id 'abc' does not have authorization to perform action "
    "'Microsoft.Storage/storageAccounts/read' over scope '/subscriptions/s/resourceGroups/$(resourceGroupName)/providers/Microsoft.Storage/"
    "storageAccounts/$(storageAccountName)' or the scope is invalid. If access was recently granted, please refresh your credentials.")


class TestUnsetVariablesInsideAnAuthorizationError:
    def test_the_unset_variables_are_the_cause_not_a_missing_role(self):
        cause = identify_cause(AUTH_WITH_UNSET_VARIABLES)
        assert cause.key == "unresolved_variable"
        assert "`$(resourceGroupName)` and `$(storageAccountName)`" in cause.diagnosis and "were never set" in cause.diagnosis
        assert "granting permissions will not fix it" in cause.diagnosis

    def test_every_unset_variable_is_in_the_yaml_example(self):
        yaml_fix = identify_cause(AUTH_WITH_UNSET_VARIABLES).yaml_fix
        assert "- name: resourceGroupName" in yaml_fix and "- name: storageAccountName" in yaml_fix

    def test_a_plain_authorization_error_is_still_a_permission_problem(self):
        text = "The client 'x' does not have authorization to perform action 'Microsoft.Storage/storageAccounts/read' over scope '/subscriptions/s/resourceGroups/rg'"
        assert identify_cause(text).key == "authorization_failed"

    def test_a_single_variable_keeps_its_singular_wording_and_signature(self):
        cause = identify_cause("ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group 'rg' was not found.")
        assert cause.signature == "unresolved_variable:storageaccountname" and "was never set" in cause.diagnosis and "granting" not in cause.diagnosis

    def test_the_same_variables_in_any_order_are_one_cause_for_merging(self):
        assert identify_cause("Error: scope '/x/$(a)/y/$(b)' is invalid").signature == identify_cause("Error: scope '/x/$(b)/y/$(a)' is invalid").signature

    def test_a_long_list_of_variables_is_capped(self):
        diagnosis = identify_cause("Error: " + " ".join(f"$(v{i})" for i in range(9))).diagnosis
        assert "`$(v3)`" in diagnosis and "`$(v4)`" not in diagnosis


def summary_with(excerpt):
    return {"stages": [{"name": "Dispatch", "tasks": [{"name": "Remove access", "failure_rate_pct": 24.3, "retry_rate_pct": 0, "error_excerpt": excerpt}]}]}


RBAC_TEXT = ("**Diagnosis**: Missing RBAC permissions.\n**Remediation**: Grant the Reader role.\n\n```yaml\n"
             "az role assignment create --assignee x --role Reader\n```\n**Impact**: x")


def model_finding(text=RBAC_TEXT, category="flaky_step"):
    return {"category": category, "severity": "high", "stage_name": "Dispatch", "task_name": "Remove access", "recommendation": text, "evidence": "e"}


class TestOneCausePerCard:
    def test_the_cause_the_error_shows_replaces_the_models_diagnosis_and_remediation(self):
        adopted = adopt_causes([model_finding()], summary_with(AUTH_WITH_UNSET_VARIABLES))
        text = adopted[0]["recommendation"]
        assert "RBAC" not in text and "Reader" not in text and "```" not in text
        assert "Task 'Remove access' failed in 24.3% of runs." in text and "never set" in text and "**Impact**: x" in text
        final = normalize_findings(adopted, summary_with(AUTH_WITH_UNSET_VARIABLES))[0][0]["recommendation"]
        assert "- name: resourceGroupName" in final and final.count("```") == 2  # the matching block is added: text and YAML agree

    def test_the_models_wording_is_kept_when_no_cause_is_recognised(self):
        finding = model_finding()
        assert adopt_causes([finding], summary_with("Process completed with exit code 1.")) == [finding]

    def test_a_diff_the_model_wrote_is_left_for_the_check_against_the_real_files(self):
        finding = model_finding("**Diagnosis**: d\n**Remediation**: r\n\n```diff\n--- a/p.yml\n+++ b/p.yml\n+x: 1\n```\n**Impact**: x")
        assert adopt_causes([finding], summary_with(AUTH_WITH_UNSET_VARIABLES)) == [finding]

    def test_other_kinds_of_finding_are_left_alone(self):
        finding = model_finding(category="bottleneck")
        assert adopt_causes([finding], summary_with(AUTH_WITH_UNSET_VARIABLES)) == [finding]

    def test_the_analysis_applies_it_so_the_card_never_shows_the_models_wrong_cause(self, monkeypatch):
        summary = summary_with(AUTH_WITH_UNSET_VARIABLES)
        monkeypatch.setattr(ai_module, "get_settings", lambda: SimpleNamespace(
            sql_connection_string="c", min_history_runs=1, azure_openai_endpoint="https://x", azure_openai_deployment="d", azure_openai_api_version="v", azure_openai_api_key=""))
        monkeypatch.setattr(ai_module, "build_analysis_summary", lambda rows, window_days: summary)
        monkeypatch.setattr(ai_module, "AlertRepository", lambda cs: SimpleNamespace(count_runs=lambda pid, days: 9, get_pipeline_metrics=lambda pid, days: [], upsert_recommendations=lambda pid, f: None))
        monkeypatch.setattr(ai_module, "fetch_one", lambda q, p=(): None)

        class Model:
            def __init__(self, *a, **k):
                pass

            def recommend(self, _summary):
                return RecommendationResponse(findings=[Finding("flaky_step", "high", "Dispatch", "Remove access", RBAC_TEXT.replace("x\n```\n**Impact**: x", "x\n```\n**Impact**: Eliminates 24%."), "e")])

        monkeypatch.setattr(ai_module, "PipelineRecommendationClient", Model)
        text = ai_module.AIService().analyze(1, 30)["findings"][0]["recommendation"]
        assert "RBAC" not in text and "Eliminates" not in text and "never set" in text and "- name: resourceGroupName" in text


class TestFailingStepsShowOnlyVerifiedOrLabelledCode:
    @staticmethod
    def failing(block):
        return {"category": "flaky_step", "recommendation": f"**Diagnosis**: d\n**Remediation**: r\n\n{block}\n**Impact**: x"}

    def test_unlabelled_model_yaml_is_removed(self):
        out = py.validate_model_snippets([self.failing("```yaml\nalertNotification:\n  defaultEmailGroup: true\n```")], ctx_for(NPM_PIPELINE))[0]["recommendation"]
        assert "alertNotification" not in out and "```" not in out and "\n\n\n" not in out

    def test_our_labelled_example_is_kept(self):
        labelled = "```yaml\n# example, not from your file: set it\nvariables:\n  a: b\n```"
        assert labelled in py.validate_model_snippets([self.failing(labelled)], ctx_for(NPM_PIPELINE))[0]["recommendation"]

    def test_other_kinds_of_finding_keep_their_unlabelled_yaml(self):
        finding = {"category": "caching_opportunity", "recommendation": "**Remediation**: r\n\n```yaml\nkey: v\n```"}
        assert py.validate_model_snippets([finding], ctx_for(NPM_PIPELINE)) == [finding]


STEP_IN_TWO_TEMPLATES = {
    "main.yml": "stages:\n  - stage: A\n    jobs:\n      - template: one.yml\n  - stage: B\n    jobs:\n      - template: two.yml\n",
    "one.yml": "jobs:\n  - job: j1\n    steps:\n      - script: a\n        displayName: Deploy Common App ${{ parameters.region }}\n",
    "two.yml": "jobs:\n  - job: j2\n    steps:\n      - script: b\n        displayName: Deploy Common App ${{ parameters.zone }}\n",
}
RG_ERROR = 'Failed to check the resource group status. Error: "resourceGroupName" should satisfy the constraint - Pattern'


def two_template_ctx(files=None):
    files = files or STEP_IN_TWO_TEMPLATES
    return ctx_for(files["main.yml"], "main.yml", FakeRepo(files).loader(files["main.yml"]))


class TestSaysWhyAStepIsNotPlaced:
    def test_a_name_that_fits_two_steps_lists_both_with_their_lines(self):
        ctx = two_template_ctx()
        assert py.locate_step(ctx.facts, "A", "Deploy Common App usgov") is None  # not guessed
        note = py._template_note(ctx, "Deploy Common App usgov")
        assert "fits 2 steps in your files" in note and "does not say which one ran" in note
        assert "`one.yml` (line 5)" in note and "`two.yml` (line 5)" in note

    def test_a_step_in_none_of_the_files_says_so_when_every_template_was_read(self):
        note = py._template_note(two_template_ctx(), "Something else entirely")
        assert note.strip() == "The step was not found in the files that could be read." and "could not be read" not in note

    def test_an_unread_template_is_still_named(self):
        files = {**STEP_IN_TWO_TEMPLATES, "main.yml": STEP_IN_TWO_TEMPLATES["main.yml"] + "  - stage: C\n    jobs:\n      - template: gone.yml\n"}
        note = py._template_note(two_template_ctx(files), "Something else entirely")
        assert "`gone.yml`" in note and "could not be read" in note

    def test_no_note_without_pipeline_yaml(self):
        assert py._template_note(None, "x") == "" and py._template_note(py.YamlContext(False, reason="r"), "x") == ""

    def test_the_cause_advice_for_such_a_step_carries_the_note(self):
        text = py.investigate_remediation("Deploy Common App usgov", RG_ERROR, "persistent", two_template_ctx())
        assert "fits 2 steps in your files" in text and "```yaml" in text

    def test_a_model_finding_for_an_unplaced_step_gets_the_note_inside_its_remediation(self):
        finding = {"category": "flaky_step", "stage_name": "A", "task_name": "Deploy Common App usgov",
                   "recommendation": "**Diagnosis**: d\n**Remediation**: Fix the variable.\n**Impact**: x"}
        text = py.apply_yaml_context([finding], two_template_ctx())[0][0]["recommendation"]
        assert text.index("fits 2 steps") < text.index("**Impact**") and "Fix the variable." in text

    def test_a_placed_step_gets_no_note(self):
        finding = {"category": "flaky_step", "stage_name": "Build", "task_name": "Install packages",
                   "recommendation": "**Diagnosis**: d\n**Remediation**: Fix it.\n**Impact**: x"}
        text = py.apply_yaml_context([finding], ctx_for(NPM_PIPELINE))[0][0]["recommendation"]
        assert "was not found" not in text and "fits" not in text

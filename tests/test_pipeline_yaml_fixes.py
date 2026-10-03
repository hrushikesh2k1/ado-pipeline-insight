"""The four defects found in real AI Analysis output, each pinned by a test:

1. a step named with a template expression ("Deploy ... ${{ parameters.region }}") was never located
2. the model's YAML for a step that could not be located was kept (its structure is a guess)
3. a "YAML" block that is a comment, a bare line or a shell command was shown as the fix
4. a remediation claimed the failure is "deterministic" when the error text does not show it
"""
import pytest

from app.services import pipeline_yaml as py
from app.services.root_causes import identify_cause
from test_pipeline_yaml import NPM_PIPELINE, ctx_for, facts_of

EXPRESSION_PIPELINE = """\
stages:
  - stage: Deploy
    jobs:
      - job: deploy
        steps:
          - task: AzureCLI@2
            displayName: Deploy AKS Alerts ${{ parameters.region }}
            inputs:
              scriptType: bash
          - script: echo hi
            displayName: Verify $(Build.BuildId) rollout
"""


def located(text, task, stage="Deploy"):
    return py.locate_step(facts_of(text), stage, task)


class TestStepNamedWithAnExpression:
    def test_the_expanded_name_in_the_run_data_finds_the_step_written_with_an_expression(self):
        _stage, _job, step = located(EXPRESSION_PIPELINE, "Deploy AKS Alerts usgovvirginia")
        assert step.display == "Deploy AKS Alerts ${{ parameters.region }}"

    def test_a_macro_in_the_name_matches_too(self):
        _stage, _job, step = located(EXPRESSION_PIPELINE, "Verify 4711 rollout")
        assert step.task == "" and "Verify" in step.display

    def test_matching_is_case_insensitive(self):
        assert located(EXPRESSION_PIPELINE, "deploy aks alerts USGOVVIRGINIA") is not None

    def test_a_name_that_does_not_fit_the_pattern_is_not_matched(self):
        assert located(EXPRESSION_PIPELINE, "Deploy AKS Metrics usgovvirginia") is None

    def test_a_name_that_is_mostly_an_expression_is_never_used_as_a_wildcard(self):
        text = "stages:\n  - stage: S\n    jobs:\n      - job: j\n        steps:\n          - script: x\n            displayName: ${{ parameters.name }}\n"
        assert py.MIN_LITERAL_CHARS > len("ab")
        assert located(text, "anything at all", stage="S") is None

    def test_two_different_steps_that_fit_leave_the_answer_unknown_rather_than_a_guess(self):
        text = ("stages:\n  - stage: S\n    jobs:\n      - job: j\n        steps:\n"
                "          - script: a\n            displayName: Deploy ${{ parameters.one }} service\n"
                "          - script: b\n            displayName: Deploy ${{ parameters.two }} service\n")
        assert located(text, "Deploy x service", stage="S") is None

    def test_the_same_step_reached_from_several_stages_is_one_match(self):
        text = ("stages:\n  - stage: A\n    jobs:\n      - job: j\n        steps:\n          - script: a\n            displayName: Deploy ${{ parameters.r }} service\n"
                "  - stage: B\n    jobs:\n      - job: j\n        steps:\n          - script: a\n            displayName: Deploy ${{ parameters.r }} service\n")
        assert located(text, "Deploy west service", stage="B") is not None

    def test_a_literal_name_still_wins_over_an_expression_name(self):
        text = ("stages:\n  - stage: S\n    jobs:\n      - job: j\n        steps:\n"
                "          - script: a\n            displayName: Deploy west service\n"
                "          - script: b\n            displayName: Deploy ${{ parameters.r }} service\n")
        assert located(text, "Deploy west service", stage="S")[2].script == "a"

    def test_the_location_text_never_prints_the_raw_expression(self):
        ctx = ctx_for(EXPRESSION_PIPELINE)
        text = py.where_text(ctx, py.locate_step(ctx.facts, "Deploy", "Deploy AKS Alerts usgovvirginia"))
        assert "${{" not in text and 'step "Deploy AKS Alerts <…>" (line 7)' in text


class TestSnippetForAStepThatWasNotLocated:
    def finding(self, **kw):
        base = dict(category="flaky_step", severity="high", stage_name="Deploy", task_name="Not in any file", evidence="e",
                    recommendation="**Diagnosis**: fails\n**Remediation**: add a retry:\n\n```yaml\n- task: HelmDeploy@0\n  retryCountOnTaskFailure: 2\n```\n**Impact**: x")
        return {**base, **kw}

    def test_the_models_yaml_is_removed_even_when_every_template_was_read(self):
        kept, _ = py.apply_yaml_context([self.finding()], ctx_for(NPM_PIPELINE))
        text = kept[0]["recommendation"]
        assert "HelmDeploy@0" not in text and "```" not in text
        assert "**Diagnosis**: fails" in text and "**Impact**: x" in text  # the rest of the finding is kept
        assert "could not be read" not in text  # nothing was unread, so no note about unread templates

    def test_the_models_yaml_is_removed_when_there_is_no_pipeline_yaml_at_all(self):
        kept, _ = py.apply_yaml_context([self.finding()], None)
        assert "```" not in kept[0]["recommendation"]

    def test_other_categories_keep_their_snippet(self):
        keep = self.finding(category="caching_opportunity")
        assert py.apply_yaml_context([keep], ctx_for(NPM_PIPELINE))[0][0]["recommendation"].count("```") == 2

    def test_a_located_step_keeps_the_models_snippet(self):
        found = self.finding(task_name="Install packages", stage_name="Build")
        kept, _ = py.apply_yaml_context([found], ctx_for(NPM_PIPELINE))
        assert kept[0]["recommendation"].count("```") == 2 and "In `azure-pipelines.yml`" in kept[0]["recommendation"]

    def test_the_replacement_block_is_added_afterwards_so_the_card_still_has_something_to_paste(self):
        from app.services.finding_quality import normalize_finding

        kept, _ = py.apply_yaml_context([self.finding()], ctx_for(NPM_PIPELINE))
        stats = {("deploy", "not in any file"): {"stage": "Deploy", "task": "Not in any file", "fail": 20.0, "retry": 0.0,
                                                 "excerpt": "Process completed with exit code 1.", "avg": 10.0, "raw": {}}}
        text = normalize_finding(kept[0], stats)["recommendation"]
        assert text.count("```") == 2 and "# example, not from your file" in text and "HelmDeploy@0" not in text


class TestOnlyRealPipelineYamlIsShownAsYaml:
    @pytest.mark.parametrize("block", [
        "- task: Cache@2\n  inputs:\n    key: k\n",
        "variables:\n  system.debug: true\n",
        "key: value\n",
        "- script: echo hi\n",
    ])
    def test_a_mapping_or_a_list_with_content_is_pasteable(self, block):
        assert py.is_pasteable_yaml(block)

    @pytest.mark.parametrize("block", [
        "",
        "# only a comment\n# and another\n",
        "az role assignment list --all",
        "kubectl get pods -n monitoring",
        "just a sentence about the fix",
        "key: [unclosed",
        "- \n",
        "- Check the variable group\n- Re-run the pipeline\n",
        "{}",
        "[]",
    ])
    def test_a_comment_a_command_a_sentence_or_broken_yaml_is_not(self, block):
        assert not py.is_pasteable_yaml(block)

    def test_a_comment_only_yaml_block_is_removed_from_the_recommendation(self):
        text = "**Remediation**: do it\n\n```yaml\n# nothing to see\n```\n**Impact**: x"
        cleaned = py.clean_snippets(text)
        assert "```" not in cleaned and "**Remediation**: do it" in cleaned and "**Impact**: x" in cleaned

    def test_a_shell_command_fence_becomes_plain_text_and_cannot_be_mistaken_for_the_fix(self):
        text = "**Remediation**: run this\n\n```bash\naz aks start -g rg -n cluster\n```\n**Impact**: x"
        cleaned = py.clean_snippets(text)
        assert "```" not in cleaned and "    az aks start -g rg -n cluster" in cleaned

    def test_a_block_with_a_yaml_label_that_holds_a_command_is_removed(self):
        assert "```" not in py.clean_snippets("**Remediation**: r\n\n```yaml\naz aks start -g rg -n cluster\n```\n")

    def test_real_yaml_and_diff_blocks_are_untouched(self):
        text = ("**Remediation**: r\n\n```yaml\n- task: Cache@2\n  inputs:\n    key: k\n```\n\n"
                "```diff\n--- a/p.yml\n+++ b/p.yml\n@@ -1 +1,2 @@\n+  retryCountOnTaskFailure: 2\n```\n")
        assert py.clean_snippets(text) == text

    def test_a_recommendation_left_without_a_block_gets_one_from_ensure_fix_block(self):
        cleaned = py.clean_snippets("**Remediation**: r\n\n```yaml\n# nothing\n```\n**Impact**: x")
        out = py.ensure_fix_block(cleaned, py.yaml_fence("variables:\n  system.debug: true"))
        assert out.count("```") == 2 and out.index("system.debug") < out.index("**Impact**")

    def test_a_command_block_does_not_count_as_the_yaml_fix(self):
        cleaned = py.clean_snippets("**Remediation**: r\n\n```bash\nls\n```\n**Impact**: x")
        assert py.ensure_fix_block(cleaned, py.yaml_fence("a: 1")).count("```") == 2


class TestNoUnsupportedCauseClaims:
    @pytest.mark.parametrize("claim", [
        "Since the failure is deterministic, retries will not help.",
        "Because the error is deterministic, a retry is pointless.",
        "This is a deterministic failure.",
        "The issue is transient in nature.",
        "A transient error like this one resolves itself.",
    ])
    def test_a_sentence_that_asserts_the_kind_of_failure_is_removed(self, claim):
        text = f"Check the service connection. {claim} Then re-run the pipeline."
        stripped = py.strip_unsupported_claims(text)
        assert "deterministic" not in stripped.lower() and "transient" not in stripped.lower()
        assert "Check the service connection." in stripped and "Then re-run the pipeline." in stripped

    def test_text_without_such_a_claim_is_unchanged(self):
        text = "Grant the identity the Reader role on the resource group. Then re-run the pipeline."
        assert py.strip_unsupported_claims(text) == text

    def test_finding_quality_applies_it_to_an_unknown_failure_only(self):
        from app.services.finding_quality import normalize_finding

        recommendation = ("**Diagnosis**: It fails.\n**Remediation**: Find the cause in the log. Since the failure is deterministic, do not add retries.\n"
                          "```yaml\nvariables:\n  system.debug: true\n```\n**Impact**: x")
        finding = {"category": "flaky_step", "severity": "high", "stage_name": "S", "task_name": "T", "recommendation": recommendation, "evidence": "e"}

        def stats(excerpt, retry=0.0):
            return {("s", "t"): {"stage": "S", "task": "T", "fail": 20.0, "retry": retry, "excerpt": excerpt, "avg": 1.0, "raw": {}}}

        unknown = normalize_finding(finding, stats("Process completed with exit code 1."))["recommendation"]
        assert "deterministic" not in unknown and "Find the cause in the log." in unknown
        shown = normalize_finding(finding, stats("ERROR: The Resource 'x' under resource group 'rg' was not found."))["recommendation"]
        assert "deterministic" in shown  # a named persistent cause is not rewritten by this rule


class TestAuthorizationAdviceHasTheCommand:
    def cause(self, action, scope="/subscriptions/s/resourceGroups/rg"):
        return identify_cause(f"The client 'abc' does not have authorization to perform action '{action}' over scope '{scope}' or the scope is invalid.")

    def test_a_read_action_names_the_reader_role_and_the_scope(self):
        text = self.cause("Microsoft.Storage/storageAccounts/read").remediation
        assert "az role assignment create --assignee <object id of the identity> --role Reader --scope /subscriptions/s/resourceGroups/rg" in text

    def test_a_write_action_does_not_invent_a_role(self):
        text = self.cause("Microsoft.Storage/storageAccounts/write").remediation
        assert "--role <a role that includes the action>" in text and "--role Reader" not in text

    def test_without_a_scope_the_placeholder_is_shown(self):
        text = identify_cause("does not have authorization to perform action 'Microsoft.Compute/virtualMachines/read'").remediation
        assert "--scope <resource group or resource id>" in text

    def test_it_says_the_yaml_cannot_grant_the_permission(self):
        assert "cannot be fixed in the pipeline file" in self.cause("Microsoft.Storage/storageAccounts/read").remediation

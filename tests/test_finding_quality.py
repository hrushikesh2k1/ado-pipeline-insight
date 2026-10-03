"""Findings are factual, complete and non-repetitive: severity from the numbers, measured impact, a block to paste, duplicates merged."""
import re

import pytest
import yaml

from app.services import finding_quality as fq
from app.services.pipeline_yaml import ensure_fix_block, get_section, replace_sections

GENERIC = "##[error]Script failed with exit code: 1"
VARIABLE = ("ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group "
            "'rg-stamp' was not found.")
PARAM = "template parameter 'defaultEmailGroup' is not valid. Expected a value of type 'Boolean', but received a value of type 'String'."


def task(name, fail=0.0, retry=0.0, error=""):
    return {"name": name, "avg_duration_s": 10, "failure_rate_pct": fail, "retry_rate_pct": retry, "error_excerpt": error}


def finding(stage, name, text="**Diagnosis**: d\n**Remediation**: r\n**Impact**: i", severity="high", category="flaky_step"):
    return {"category": category, "severity": severity, "stage_name": stage, "task_name": name, "recommendation": text, "evidence": "e"}


def summary(*stages):
    return {"stages": [{"name": n, "tasks": t} for n, t in stages]}


def fenced_yaml(text):
    blocks = re.findall(r"```(?:yaml|diff)\n(.*?)\n```", text, re.S)
    assert blocks, "no code block to paste"
    return blocks


class TestSeverityAndImpact:
    @pytest.mark.parametrize("fail,retry,expected", [(45.5, 0, "high"), (15, 0, "high"), (14.9, 0, "medium"), (9.6, 0, "medium"), (5, 0, "medium"), (4.9, 0, "low"), (2, 25, "high"), (0, 5, "low")])
    def test_severity_comes_from_the_measured_thresholds(self, fail, retry, expected):
        assert fq.severity_for(fail, retry) == expected

    def test_impact_states_what_was_measured_and_never_promises_a_reduction(self):
        for fail, retry, kind in ((31.8, 0, "persistent"), (31.8, 0, "transient"), (31.8, 0, "unknown"), (0, 12, "transient")):
            text = fq.measured_impact(fail, retry, kind)
            assert not re.search(r"eliminat|reduc|saves|improv", text, re.I)
        assert "31.8%" in fq.measured_impact(31.8, 0, "persistent") and "12%" in fq.measured_impact(0, 12, "transient")

    def test_impact_claims_nothing_about_retries_when_the_cause_is_not_visible(self):
        text = fq.measured_impact(34.3, 0, fq.impact_kind("Script failed with exit code: 1", 0))
        assert "34.3%" in text and "does not show the cause" in text and "not known whether a retry would help" in text
        assert "would only repeat" not in text and "fixing the cause removes" not in text

    def test_a_named_persistent_cause_still_says_retrying_would_only_repeat_it(self):
        error = "ERROR: The Resource 'x' under resource group 'rg' was not found."
        assert fq.impact_kind(error, 0) == "persistent"
        assert "retrying would only repeat them" in fq.measured_impact(20, 0, fq.impact_kind(error, 0))

    def test_a_transient_error_or_retry_data_is_transient(self):
        assert fq.impact_kind("dial tcp 10.0.0.4:443: i/o timeout", 0) == "transient"
        assert fq.impact_kind("Script failed with exit code: 1", 12) == "transient"


class TestNormalize:
    def test_the_screenshot_finding_gets_the_right_severity_impact_and_no_false_claim(self):
        s = summary(("Stamp", [task("Install MDC chart", fail=9.6, error=GENERIC)]))
        bad = finding("Stamp", "Install MDC chart", severity="high", text=(
            "**Diagnosis**: This is a deterministic failure in the Helm install.\n**Remediation**: Fix the script.\n**Impact**: Eliminates ~9.6% failure rate."))
        out = fq.normalize_findings([bad], s)[0][0]
        text = out["recommendation"]
        assert out["severity"] == "medium"  # 9.6% is below the 15% high threshold
        assert "deterministic" not in text and "Eliminates" not in text
        assert "the cause is not visible in it" in get_section(text, "diagnosis")
        assert "9.6% of runs" in get_section(text, "impact")
        assert "would only repeat" not in get_section(text, "impact")  # the cause is not visible, so nothing is claimed about retries

    def test_a_specific_diagnosis_is_kept_when_the_error_supports_it(self):
        s = summary(("Stamp", [task("Deploy", fail=30, error=PARAM)]))
        mine = finding("Stamp", "Deploy", text="**Diagnosis**: The parameter type is wrong, a deterministic mismatch.\n**Remediation**: Fix it.\n**Impact**: x")
        out = fq.normalize_findings([mine], s)[0][0]
        assert "deterministic mismatch" in get_section(out["recommendation"], "diagnosis")  # a named cause: the claim is supported

    def test_every_finding_ends_up_with_a_block_to_paste(self):
        s = summary(("S", [task("Flaky", fail=40, error="i/o timeout"), task("Bad var", fail=30, error=VARIABLE), task("Mystery", fail=20, error=GENERIC), task("Slow", fail=0)]))
        findings = [finding("S", "Flaky"), finding("S", "Bad var"), finding("S", "Mystery"),
                    finding("S", "Slow", category="bottleneck"), finding("S", None, category="caching_opportunity"), finding("S", None, category="queue_capacity")]
        for out in fq.normalize_findings(findings, s)[0]:
            for block in fenced_yaml(out["recommendation"]):
                yaml.safe_load(block)
        blocks = {f["task_name"] or f["category"]: fenced_yaml(f["recommendation"])[0] for f in fq.normalize_findings(findings, s)[0]}
        assert "retryCountOnTaskFailure: 2" in blocks["Flaky"]  # transient: retry
        assert "- name: storageAccountName" in blocks["Bad var"]  # the variable the error names
        assert "system.debug: true" in blocks["Mystery"]  # unknown cause: get the real error first
        assert "jobs:" in blocks["Slow"] and "Cache@2" in blocks["caching_opportunity"] and "pool:" in blocks["queue_capacity"]

    def test_an_existing_block_is_never_replaced(self):
        s = summary(("S", [task("Flaky", fail=40, error="i/o timeout")]))
        mine = finding("S", "Flaky", text="**Diagnosis**: d\n**Remediation**: r\n\n```diff\n--- a/x.yml\n+++ b/x.yml\n@@\n+k: v\n```\n**Impact**: i")
        assert "+k: v" in fq.normalize_findings([mine], s)[0][0]["recommendation"]

    def test_unmeasured_findings_are_left_alone_apart_from_the_block(self):
        out = fq.normalize_findings([finding("Unknown", "Nothing", severity="low")], summary(("S", [task("A", fail=50)])))[0][0]
        assert out["severity"] == "low" and "```yaml" in out["recommendation"]


class TestMerge:
    def five_stages(self):
        stages = [(f"Stage {i}", [task("Remove access", fail=20 + i, error=VARIABLE)]) for i in range(5)]
        return summary(*stages), [finding(f"Stage {i}", "Remove access") for i in range(5)]

    def test_the_same_step_and_error_across_stages_becomes_one_finding_listing_them_all(self):
        s, findings = self.five_stages()
        merged, folded = fq.normalize_findings(findings, s)
        assert len(merged) == 1 and folded == 4
        one = merged[0]
        assert one["stage_name"] == "Stage 4" and one["severity"] == "high"  # the worst occurrence represents the group
        note = get_section(one["recommendation"], "diagnosis")
        assert all(f"'Stage {i}' ({20 + i}%)" in note for i in range(4)) and "The same step fails the same way" in note
        assert "'Stage 0' (20%)" in one["evidence"]

    def test_different_steps_with_one_root_cause_are_merged_and_named(self):
        s = summary(("Stamp", [task("Deploy AKS alerts", fail=24, error=PARAM), task("Deploy PowerBI alerts", fail=22.9, error=PARAM), task("Deploy NSG alerts", fail=22.9, error=PARAM)]))
        merged, folded = fq.normalize_findings([finding("Stamp", t) for t in ("Deploy AKS alerts", "Deploy PowerBI alerts", "Deploy NSG alerts")], s)
        assert len(merged) == 1 and folded == 2 and merged[0]["task_name"] == "Deploy AKS alerts"
        assert "The same error also fails" in merged[0]["recommendation"] and "'Deploy NSG alerts' in 'Stamp' (22.9%)" in merged[0]["recommendation"]

    def test_the_same_generic_failure_in_two_stages_merges_but_different_steps_with_generic_errors_do_not(self):
        s = summary(("A", [task("Install MDC chart", fail=34.3, error=GENERIC), task("Other step", fail=20, error=GENERIC)]), ("B", [task("Install MDC chart", fail=31.8, error=GENERIC)]))
        merged, folded = fq.normalize_findings([finding("A", "Install MDC chart"), finding("A", "Other step"), finding("B", "Install MDC chart")], s)
        assert folded == 1 and sorted(f["task_name"] for f in merged) == ["Install MDC chart", "Other step"]

    def test_different_errors_for_the_same_step_stay_separate(self):
        s = summary(("A", [task("Deploy", fail=30, error="chart not found")]), ("B", [task("Deploy", fail=20, error="quota exceeded")]))
        assert fq.normalize_findings([finding("A", "Deploy"), finding("B", "Deploy")], s)[1] == 0

    def test_a_long_list_is_shortened(self):
        s = summary(*[(f"S{i}", [task("Step", fail=30 + i, error=VARIABLE)]) for i in range(12)])
        merged, folded = fq.normalize_findings([finding(f"S{i}", "Step") for i in range(12)], s)
        assert folded == 11 and "and 3 more" in merged[0]["recommendation"]

    def test_non_failure_findings_are_never_merged(self):
        s = summary(("A", [task("Slow", fail=0)]))
        both = [finding("A", "Slow", category="bottleneck"), finding("A", "Slow", category="bottleneck")]
        assert len(fq.normalize_findings(both, s)[0]) == 2


class TestOrdering:
    def test_severity_then_failure_rate_then_failing_steps_first(self):
        s = summary(("S", [task("a", fail=20), task("b", fail=40), task("c", fail=8)]))
        items = [{**finding("S", "a")}, {**finding("S", "b")}, {**finding("S", "c", severity="medium")}, {**finding("S", None, severity="high", category="bottleneck")}]
        ordered, omitted = fq.order_and_cap(items, s, 3)
        assert [f["task_name"] for f in ordered] == ["b", "a", None] and omitted == 1


class TestSections:
    def test_replace_and_get_sections(self):
        text = "**Diagnosis**: old\n**Remediation**: fix\n**Impact**: x"
        new = replace_sections(text, diagnosis="new", impact="measured")
        assert get_section(new, "diagnosis") == "new" and get_section(new, "remediation") == "fix" and get_section(new, "impact") == "measured"
        assert get_section("no markers", "diagnosis") == ""

    def test_ensure_fix_block_inserts_before_impact_and_never_duplicates(self):
        block = "```yaml\na: b\n```"
        out = ensure_fix_block("**Diagnosis**: d\n**Remediation**: r\n**Impact**: i", block)
        assert out.index("```yaml") < out.index("**Impact**") and out.count("```yaml") == 1
        assert ensure_fix_block(out, "```yaml\nother\n```") == out
        assert ensure_fix_block("just text", block).endswith(block)

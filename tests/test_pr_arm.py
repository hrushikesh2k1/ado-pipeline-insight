"""Alert templates in a pull request: recognising them, and saying what each alert means before and after the change."""
from __future__ import annotations

import json

import pytest

from app.services.alert_facts import alerts_in, load_arm
from app.services.pr_arm import MAX_CONTEXT_CHARS, MAX_QUERY_CHARS, arm_context, is_arm_template
from irp_support import FIXTURES

VPN = (FIXTURES / "vpn_log_alert.arm.json").read_text(encoding="utf-8")
AKS = (FIXTURES / "aks_cpu_metric_alert.arm.json").read_text(encoding="utf-8")
NAME = "VPN - Tunnel disconnected - Production"


def edited(text: str, *swaps: tuple[str, str]) -> str:
    for old, new in swaps:
        assert old in text, old
        text = text.replace(old, new)
    return text


class TestIsArmTemplate:
    def test_the_arm_schema_is_enough(self):
        assert is_arm_template(VPN) and is_arm_template(AKS)
        assert is_arm_template('{"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#", "parameters": {}}')
        assert is_arm_template('{"$schema": "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#"}')

    def test_so_are_resources_of_microsoft_types_with_an_api_version(self):
        assert is_arm_template('{"resources": [{"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-01-01", "name": "x"}]}')

    def test_ordinary_json_is_not(self):
        for text in ('{"name": "pkg", "version": "1.0.0", "dependencies": {}}', '{"resources": ["a", "b"]}', '[]', '', None, '{"type": "Microsoft.Storage/x"}'):
            assert not is_arm_template(text)


class TestAlertsIn:
    def test_log_and_metric_alerts_are_read_with_their_values(self):
        log, problem = alerts_in(VPN)
        assert problem is None and log[0]["name"] == NAME and log[0]["window_size"] == "PT10M" and log[0]["condition"]["threshold"] == 0
        metric, _ = alerts_in(AKS)
        assert metric[0]["type"] == "metric"

    def test_a_template_that_is_not_json_is_reported_not_raised(self):
        alerts, problem = alerts_in('{"resources": [')
        assert alerts == [] and problem.startswith("not valid JSON")

    def test_a_template_without_alerts_gives_an_empty_list(self):
        assert alerts_in('{"resources": []}') == ([], None)


class TestDescribeAnAlert:
    def test_a_new_template_is_described_in_words(self):
        text = arm_context(None, VPN)
        assert f'1. "{NAME}": log alert (kind LogAlert), severity 1 (Error; 0 is the most severe), enabled' in text
        assert "Fires when the number of rows returned by the alert query is greater than 0" in text
        assert "Evaluated every 5 minutes over a window of 10 minutes." in text
        assert "autoMitigate: true" in text
        assert "This template is new: every alert in it is new." in text

    def test_the_query_is_laid_out_over_several_lines(self):
        text = arm_context(None, VPN)
        assert "   Query:\n      AzureDiagnostics\n      | where ResourceType" in text
        assert "      | where TimeGenerated > ago(10m)\n" in text and "      | project TimeGenerated, Resource, Disconnects" in text

    def test_a_metric_alert(self):
        text = arm_context(None, AKS)
        assert "metric alert" in text and "node_cpu_usage_percentage" in text and "greater than 80" in text and "Query:" not in text

    def test_no_action_group_is_said_in_plain_words(self):
        without = edited(VPN, ('"actions": {\n          "actionGroups": [\n            "[resourceId(\'Microsoft.Insights/actionGroups\', parameters(\'actionGroupName\'))]"\n          ]\n        },', ""))
        assert "none are set in this template, so nobody is notified when it fires" in arm_context(None, without)

    def test_a_disabled_alert(self):
        assert ", disabled" in arm_context(None, edited(VPN, ('"enabled": true', '"enabled": false')))

    def test_a_very_long_query_is_cut(self):
        long_query = "T | where " + " and ".join(f"Col{n} == {n}" for n in range(1000))
        text = arm_context(None, edited(VPN, ("AzureDiagnostics\\n| where ResourceType", long_query.replace('"', "'") + "\\n| where ResourceType")))
        assert "(the rest of the query is cut)" in text and len(text) < MAX_QUERY_CHARS + 1000


class TestWhatChanged:
    def changes(self, new):
        text = arm_context(VPN, new)
        return text.split("WHAT CHANGED IN THE ALERT RULES:\n", 1)[1]

    def test_a_changed_threshold_and_window_are_listed_with_before_and_after(self):
        changes = self.changes(edited(VPN, ('"threshold": 0', '"threshold": 3'), ('"windowSize": "PT10M"', '"windowSize": "PT15M"')))
        assert f'- "{NAME}": window size: PT10M -> PT15M; condition: the number of rows returned by the alert query is greater than 0, split by Resource -> the number of rows returned by the alert query is greater than 3, split by Resource.' in changes
        assert "the query changed" not in changes

    def test_a_changed_query_shows_the_query_before_the_change(self):
        changes = self.changes(edited(VPN, ('where Message has \\"disconnected\\"', 'where Message has \\"disconnected\\" and Resource != \\"gw-test\\"')))
        assert "the query changed (the query before the change is shown below)" in changes
        assert "  Query before the change:\n      AzureDiagnostics\n" in changes and 'Resource != "gw-test"' not in changes

    def test_a_query_that_only_changed_in_spacing_is_not_a_change(self):
        changes = self.changes(edited(VPN, ('| where TimeGenerated > ago(10m)\\n', '|   where TimeGenerated   >   ago(10m)\\n')))
        assert "No alert rule changed" in changes

    def test_other_parts_of_the_template_changing_is_said(self):
        assert "No alert rule changed: only other parts of the template changed." in self.changes(edited(VPN, ('"contentVersion": "1.0.0.0"', '"contentVersion": "1.0.0.1"')))

    def test_a_new_alert(self):
        document = load_arm(VPN)
        second = json.loads(json.dumps(document["resources"][0]))
        second["name"] = "VPN - Second alert"
        second["properties"]["displayName"] = "VPN - Second alert"
        document["resources"].append(second)
        text = arm_context(VPN, json.dumps(document))
        assert 'New alert "VPN - Second alert" (added by this change).' in text and "2. \"VPN - Second alert\"" in text

    def test_a_removed_alert(self):
        document = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", "resources": []}
        text = arm_context(VPN, json.dumps(document))
        assert f'Alert "{NAME}" was removed by this change.' in text

    def test_the_other_way_round_an_alert_that_is_not_in_the_earlier_version_is_new(self):
        old = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", "resources": []}
        assert f'New alert "{NAME}"' in arm_context(json.dumps(old), VPN)

    def test_a_changed_severity_and_removed_action_group(self):
        changes = self.changes(edited(VPN, ('"severity": 1', '"severity": 3')))
        assert "severity: 1 -> 3" in changes


class TestProblemTemplates:
    def test_a_template_that_is_no_longer_valid_json(self):
        text = arm_context(VPN, VPN.replace('"resources": [', '"resources": [,'))
        assert text.startswith("The template is not valid JSON") and "cannot be deployed as it is" in text

    def test_an_earlier_version_that_could_not_be_read(self):
        text = arm_context("{ not json", VPN)
        assert "The earlier version of the template could not be read, so what changed in the alerts is not listed." in text and "WHAT CHANGED" not in text

    def test_a_template_with_no_alerts(self):
        template = '{"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", "resources": [{"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-01-01", "name": "s"}]}'
        assert arm_context(template, template) == "No Azure Monitor alert rule (scheduledQueryRules or metricAlerts) is defined in this template."

    def test_the_whole_context_is_bounded(self):
        document = load_arm(VPN)
        document["resources"] = [{**document["resources"][0], "name": f"Alert {n}", "properties": {**document["resources"][0]["properties"], "displayName": f"Alert {n}"}} for n in range(60)]
        text = arm_context(None, json.dumps(document))
        assert len(text) <= MAX_CONTEXT_CHARS + 40 and text.endswith("(the rest is cut)")

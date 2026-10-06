"""Log alerts in the older 2018-04-16 format (query in source, timing in schedule, severity and action group in action), as Microsoft documents it.

A template often holds both formats side by side. Before this was read, an older-format alert came out with no window, no query, no severity and
"nobody is notified", whatever the template said.
"""
from __future__ import annotations

import json

import pytest

from app.services.alert_facts import alerts_in, read_alert
from app.services.pr_arm import arm_context

SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
WORKSPACE = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-monitoring/providers/Microsoft.OperationalInsights/workspaces/law-main"
GROUP = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-monitoring/providers/microsoft.insights/actionGroups/ag-oncall"


def legacy(name="AKS - Restart", query="KubePodInventory | take 1", window=30, frequency=5, **over):
    action = {"severity": "2", "aznsAction": {"actionGroup": [GROUP], "emailSubject": "Warning"},
              "trigger": {"thresholdOperator": "GreaterThan", "threshold": 0},
              "odata.type": "Microsoft.WindowsAzure.Management.Monitoring.Alerts.Models.Microsoft.AppInsights.Nexus.DataContracts.Resources.ScheduledQueryRules.AlertingAction"}
    properties = {"description": "Restarts", "displayName": name, "enabled": "true", "autoMitigate": False,
                  "source": {"query": query, "dataSourceId": WORKSPACE, "queryType": "ResultCount"},
                  "schedule": {"frequencyInMinutes": frequency, "timeWindowInMinutes": window}, "action": action}
    properties.update(over)
    return {"type": "microsoft.insights/scheduledqueryrules", "apiVersion": "2018-04-16", "name": name, "location": "eastus", "properties": properties}


def current(name="AKS - Crash", window="PT10M"):
    return {"type": "Microsoft.Insights/scheduledQueryRules", "apiVersion": "2023-12-01", "name": name, "location": "eastus", "kind": "LogAlert", "properties": {
        "displayName": name, "severity": 1, "enabled": True, "evaluationFrequency": "PT5M", "windowSize": window, "scopes": [WORKSPACE],
        "criteria": {"allOf": [{"query": "ContainerLogV2 | take 1", "timeAggregation": "Count", "operator": "GreaterThan", "threshold": 0}]},
        "actions": {"actionGroups": [GROUP]}, "autoMitigate": False}}


def template(*resources):
    return json.dumps({"$schema": SCHEMA, "contentVersion": "1.0.0.0", "resources": list(resources)})


class TestReadingTheOlderFormat:
    def alert(self, **over):
        alerts, problem = alerts_in(template(legacy(**over)))
        assert problem is None and len(alerts) == 1
        return alerts[0]

    def test_everything_the_template_says_is_read(self):
        a = self.alert()
        assert (a["name"], a["severity"], a["enabled"], a["auto_mitigate"], a["legacy"], a["api_version"]) == ("AKS - Restart", 2, True, False, True, "2018-04-16")
        assert (a["evaluation_frequency"], a["window_size"]) == ("PT5M", "PT30M")
        assert a["query"] == "KubePodInventory | take 1" and a["scopes"] == [WORKSPACE] and a["action_groups"] == ["ag-oncall"]
        assert a["condition_sentence"] == "the number of rows returned by the alert query is greater than 0"
        assert a["condition"]["threshold"] == 0 and a["condition"]["operator"] == "GreaterThan" and a["product"] == "Microsoft.OperationalInsights/workspaces"

    def test_text_flags_become_flags(self):
        assert self.alert(enabled="false")["enabled"] is False
        assert self.alert(enabled="TRUE")["enabled"] is True
        assert self.alert(autoMitigate="true")["auto_mitigate"] is True

    def test_throttling_is_kept_under_its_own_name(self):
        a = self.alert(action={**legacy()["properties"]["action"], "throttlingInMin": 60})
        assert a["throttle_minutes"] == 60 and a["mute_actions_duration"] is None

    def test_a_metric_trigger_is_described_without_guessing(self):
        action = {**legacy()["properties"]["action"], "trigger": {"thresholdOperator": "GreaterThan", "threshold": 0,
                                                                  "metricTrigger": {"metricColumn": "Computer", "metricTriggerType": "Consecutive", "thresholdOperator": "GreaterThan", "threshold": 2}}}
        assert self.alert(action=action)["condition_sentence"] == "the number of rows returned by the alert query is greater than 0, with a metric trigger on column Computer (consecutive: greater than 2)"

    def test_missing_parts_are_not_invented(self):
        a = self.alert(source={"dataSourceId": WORKSPACE}, schedule={}, action={})
        assert a["query"] is None and a["window_size"] is None and a["evaluation_frequency"] is None and a["severity"] is None and a["action_groups"] == []

    def test_a_template_with_both_formats_reads_both(self):
        alerts, _ = alerts_in(template(legacy(), current()))
        assert [(a["name"], a["legacy"] if "legacy" in a else False) for a in alerts] == [("AKS - Restart", True), ("AKS - Crash", False)]
        assert alerts[1]["window_size"] == "PT10M" and alerts[1]["severity"] == 1

    def test_a_flag_written_as_text_in_the_newer_format_is_read_too(self):
        resource = current()
        resource["properties"]["enabled"] = "false"
        assert alerts_in(template(resource))[0][0]["enabled"] is False

    def test_the_newer_format_is_not_mistaken_for_the_older_one(self):
        assert "legacy" not in alerts_in(template(current()))[0][0]


class TestThePlainWordsTheReviewerGets:
    def test_an_older_format_alert_is_described_from_what_the_template_says(self):
        text = arm_context(None, template(legacy()))
        assert '1. "AKS - Restart": log alert (older 2018-04-16 format), severity 2 (Warning), enabled' in text
        assert "0 is the most severe" not in text  # Microsoft documents that scale for the newer format only
        assert "Evaluated every 5 minutes over a window of 30 minutes." in text
        assert "Action groups: ag-oncall" in text and "nobody is notified" not in text
        assert "   Query:\n      KubePodInventory | take 1" in text and "Scope: " + WORKSPACE in text

    def test_the_newer_format_still_says_what_the_scale_is(self):
        assert "severity 1 (Error; 0 is the most severe)" in arm_context(None, template(current()))

    def test_a_changed_query_in_an_older_format_alert_is_seen(self):
        text = arm_context(template(legacy(query="KubePodInventory | take 1")), template(legacy(query="KubePodInventory | take 2")))
        assert "the query changed" in text and "No alert rule changed" not in text and "Query before the change:\n      KubePodInventory | take 1" in text

    def test_a_changed_window_and_throttling_are_seen(self):
        old = template(legacy(window=10))
        new = template(legacy(window=30, action={**legacy()["properties"]["action"], "throttlingInMin": 15}))
        text = arm_context(old, new)
        assert "window size: PT10M -> PT30M" in text and "throttlingInMin: not set -> 15" in text

    def test_in_a_template_with_both_formats_each_change_belongs_to_its_alert(self):
        old = template(legacy(window=30), current(window="PT10M"))
        new = template(legacy(window=30), current(window="PT30M"))
        changes = arm_context(old, new).split("WHAT CHANGED IN THE ALERT RULES:\n", 1)[1]
        assert changes.startswith('- "AKS - Crash": window size: PT10M -> PT30M.') and "AKS - Restart" not in changes

    def test_a_disabled_older_alert_is_said_to_be_disabled(self):
        assert ", disabled" in arm_context(None, template(legacy(enabled="false")))


class TestInIrpStudioToo:
    def test_the_alert_reader_the_irp_writer_uses_understands_the_older_format(self):
        facts = read_alert(template(legacy(name="AKS - Restart")), None, "AKS - Restart")
        assert facts["alert"]["window_size"] == "PT30M" and facts["alert"]["severity"] == 2 and facts["severity_name"] == "Warning"
        assert facts["kql"]["query"] == "KubePodInventory | take 1" and facts["kql"]["tables"] == ["KubePodInventory"]
        assert "greater than 0" in facts["description_sentence"]

    def test_a_disabled_older_alert_gets_the_disabled_warning(self):
        facts = read_alert(template(legacy(enabled="false")), None, None)
        assert any("disabled" in w for w in facts["warnings"])

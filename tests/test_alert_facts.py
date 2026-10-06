import json
from pathlib import Path

import pytest

from app.services.alert_facts import (
    _Context,
    _resolve,
    analyze_kql,
    facts_for_prompt,
    find_alerts,
    human_duration,
    load_arm,
    read_alert,
    strip_json_comments,
    strip_kql_comments,
)

FIXTURES = Path(__file__).parent / "fixtures" / "irp"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def resolve(value, template=None, params=None):
    ctx = _Context(template or {}, params)
    return _resolve(value, ctx), ctx


class TestJsonComments:
    def test_line_and_block_comments_are_removed(self):
        assert json.loads(strip_json_comments('{"a": 1, // note\n "b": /* two */ 2}')) == {"a": 1, "b": 2}

    def test_slashes_inside_strings_stay(self):
        text = '{"url": "https://example.com/a//b", "q": "x /* y */"}'
        assert json.loads(strip_json_comments(text)) == {"url": "https://example.com/a//b", "q": "x /* y */"}

    def test_an_escaped_quote_does_not_end_the_string(self):
        assert json.loads(strip_json_comments(r'{"a": "he said \"// not a comment\""}'))["a"] == 'he said "// not a comment"'


class TestExpressions:
    def test_a_parameter_default_is_used(self):
        value, _ = resolve("[parameters('env')]", {"parameters": {"env": {"defaultValue": "Production"}}})
        assert value == "Production"

    def test_a_parameter_without_a_value_becomes_a_named_placeholder_and_is_reported(self):
        value, ctx = resolve("[parameters('actionGroup')]", {"parameters": {"actionGroup": {"type": "string"}}})
        assert value == "<actionGroup>" and "parameter 'actionGroup' has no value" in ctx.unresolved[0]

    def test_a_passed_in_value_beats_the_default(self):
        value, _ = resolve("[parameters('n')]", {"parameters": {"n": {"defaultValue": "default"}}}, {"n": "passed"})
        assert value == "passed"

    def test_variables_concat_and_nested_variables(self):
        template = {"parameters": {"env": {"defaultValue": "Prod"}}, "variables": {"base": "VPN", "name": "[concat(variables('base'), ' - ', parameters('env'))]"}}
        assert resolve("[variables('name')]", template)[0] == "VPN - Prod"

    def test_format_and_case_functions(self):
        assert resolve("[format('{0}-{1}', 'a', 'B')]")[0] == "a-B"
        assert resolve("[toLower('AbC')]")[0] == "abc" and resolve("[toUpper('abc')]")[0] == "ABC"
        assert resolve("[replace('a-b-c', '-', '_')]")[0] == "a_b_c"

    def test_resource_id_builds_an_id_with_the_names_the_template_gives(self):
        value, _ = resolve("[resourceId('Microsoft.Network/virtualNetworkGateways', 'gw1')]")
        assert value == "/subscriptions/<subscriptionId>/resourceGroups/<resourceGroup>/providers/Microsoft.Network/virtualNetworkGateways/gw1"

    def test_the_resource_group_and_subscription_are_placeholders(self):
        assert resolve("[resourceGroup().name]")[0] == "<resourceGroup>"
        assert resolve("[subscription().subscriptionId]")[0] == "<subscriptionId>"

    def test_an_expression_it_cannot_evaluate_is_marked_not_invented(self):
        value, ctx = resolve("[uniqueString(resourceGroup().id)]")
        assert value.startswith("<unresolved:") and ctx.unresolved

    def test_an_escaped_bracket_is_a_literal(self):
        assert resolve("[[not an expression]")[0] == "[not an expression]"

    def test_plain_text_numbers_lists_and_objects_are_resolved_inside(self):
        value, _ = resolve({"a": ["[concat('x', 'y')]", 3, True], "b": "plain"})
        assert value == {"a": ["xy", 3, True], "b": "plain"}

    def test_property_access_and_indexing(self):
        template = {"variables": {"o": {"name": "n1", "list": ["a", "b"]}}}
        assert resolve("[variables('o').name]", template)[0] == "n1"
        assert resolve("[variables('o').list[1]]", template)[0] == "b"

    def test_a_variable_that_refers_to_itself_does_not_loop_forever(self):
        value, _ = resolve("[variables('a')]", {"variables": {"a": "[variables('a')]"}})
        assert isinstance(value, str)

    def test_a_quote_inside_a_string_literal(self):
        assert resolve("[concat('it''s', ' ok')]")[0] == "it's ok"


class TestFindingAlerts:
    def test_a_full_template(self):
        found = find_alerts(load_arm(fixture("vpn_log_alert.arm.json")))
        assert len(found) == 1 and found[0][0]["type"] == "Microsoft.Insights/scheduledQueryRules"

    def test_a_bare_resource_and_a_list_of_resources(self):
        resource = {"type": "Microsoft.Insights/metricAlerts", "name": "a", "properties": {}}
        assert len(find_alerts(resource)) == 1
        assert len(find_alerts([resource, {"type": "Microsoft.Storage/storageAccounts", "name": "s"}])) == 1

    def test_the_type_is_matched_without_regard_to_case(self):
        assert len(find_alerts({"type": "microsoft.insights/SCHEDULEDQUERYRULES", "name": "a", "properties": {}})) == 1

    def test_resources_named_with_symbolic_names(self):
        document = {"resources": {"alertA": {"type": "Microsoft.Insights/metricAlerts", "name": "a", "properties": {}}}}
        assert len(find_alerts(document)) == 1

    def test_an_alert_inside_a_nested_deployment_gets_the_values_passed_to_it(self):
        found = find_alerts(load_arm(fixture("nested_deployment.arm.json")))
        assert len(found) == 1
        _resource, ctx = found[0]
        assert ctx.params == {"gatewayName": "vnet-gw-prod-east"}

    def test_a_template_without_alerts(self):
        assert find_alerts({"resources": [{"type": "Microsoft.Storage/storageAccounts", "name": "s"}]}) == []
        assert find_alerts("text") == [] and find_alerts({}) == []


class TestDurations:
    @pytest.mark.parametrize("iso,text", [("PT5M", "5 minutes"), ("PT1M", "1 minute"), ("PT1H", "1 hour"), ("P1D", "1 day"), ("PT1H30M", "1 hour 30 minutes"), ("PT30S", "30 seconds")])
    def test_iso_durations_in_words(self, iso, text):
        assert human_duration(iso) == text

    def test_anything_else_is_returned_as_it_is(self):
        assert human_duration("5 minutes") == "5 minutes" and human_duration(None) == "" and human_duration("PT") == "PT"


class TestLogAlert:
    facts = read_alert(fixture("vpn_log_alert.arm.json"))

    def test_the_names_and_values_come_from_the_template(self):
        alert = self.facts["alert"]
        assert alert["name"] == "VPN - Tunnel disconnected - Production"
        assert alert["type"] == "log" and alert["source"] == "Log" and alert["kind"] == "LogAlert" and alert["api_version"] == "2021-08-01"
        assert (alert["severity"], self.facts["severity_name"]) == (1, "Error")
        assert (alert["evaluation_frequency"], alert["window_size"]) == ("PT5M", "PT10M")

    def test_the_target_resource_type_wins_over_the_scope(self):
        assert self.facts["alert"]["product"] == "Microsoft.Network/virtualNetworkGateways"
        assert self.facts["alert"]["scopes"] == ["/subscriptions/<subscriptionId>/resourceGroups/<resourceGroup>/providers/Microsoft.OperationalInsights/workspaces/law-network-prod"]

    def test_the_condition_is_put_into_words(self):
        assert self.facts["alert"]["condition_sentence"] == "the number of rows returned by the alert query is greater than 0, split by Resource"
        assert self.facts["description_sentence"] == "the number of rows returned by the alert query is greater than 0, split by Resource, measured over 10 minutes and evaluated every 5 minutes"

    def test_the_query_comes_from_the_template_with_its_comment_kept_in_the_text(self):
        assert self.facts["kql"]["source"] == "arm" and self.facts["kql"]["query"].startswith("AzureDiagnostics\n| where ResourceType")

    def test_the_action_group_is_named_and_a_missing_value_is_reported(self):
        assert self.facts["alert"]["action_groups"] == ["<actionGroupName>"]
        assert any("parameter 'actionGroupName' has no value" in item for item in self.facts["arm"]["unresolved"])
        assert any("could not be resolved" in w for w in self.facts["warnings"])

    def test_the_query_is_analysed(self):
        kql = self.facts["kql"]
        assert kql["tables"] == ["AzureDiagnostics"]
        assert {"column": "Category", "operator": "==", "values": ["TunnelDiagnosticLog"]} in kql["filters"]
        assert kql["time_windows"] == ["10m"] and kql["group_by"] == ["Resource", "bin(TimeGenerated, 5m)"]
        assert kql["output_columns"] == ["TimeGenerated", "Resource", "Disconnects"]

    def test_the_resolved_resource_is_kept_for_the_writer(self):
        assert '"displayName": "VPN - Tunnel disconnected - Production"' in self.facts["resolved_resource_json"]

    def test_a_measure_column_and_failing_periods_are_in_the_sentence(self):
        resource = {"type": "Microsoft.Insights/scheduledQueryRules", "name": "a", "properties": {"severity": 3, "criteria": {"allOf": [{
            "query": "Perf | summarize avg(CounterValue)", "timeAggregation": "Average", "metricMeasureColumn": "AggregatedValue", "operator": "GreaterThanOrEqual",
            "threshold": 90, "failingPeriods": {"numberOfEvaluationPeriods": 5, "minFailingPeriodsToAlert": 3}}]}}}
        sentence = read_alert(json.dumps(resource))["alert"]["condition_sentence"]
        assert sentence == "the average of column AggregatedValue returned by the alert query is at least 90 in at least 3 of 5 evaluation periods"

    def test_a_scope_that_is_a_resource_gives_the_product_when_no_target_type_is_set(self):
        resource = {"type": "Microsoft.Insights/scheduledQueryRules", "name": "a", "properties": {"scopes": ["/subscriptions/s/resourceGroups/r/providers/Microsoft.Network/virtualNetworkGateways/gw"], "criteria": {"allOf": [{"query": "X"}]}}}
        assert read_alert(json.dumps(resource))["alert"]["product"] == "Microsoft.Network/virtualNetworkGateways"

    def test_a_disabled_alert_and_extra_conditions_are_flagged(self):
        resource = {"type": "Microsoft.Insights/scheduledQueryRules", "name": "a", "properties": {"enabled": False, "criteria": {"allOf": [{"query": "A"}, {"query": "B"}]}}}
        warnings = read_alert(json.dumps(resource))["warnings"]
        assert any("disabled" in w for w in warnings) and any("more than one condition" in w for w in warnings)


class TestMetricAlert:
    def test_a_static_threshold(self):
        facts = read_alert(fixture("aks_cpu_metric_alert.arm.json"))
        alert = facts["alert"]
        assert alert["type"] == "metric" and alert["source"] == "Metric" and facts["severity_name"] == "Warning"
        assert alert["condition_sentence"] == "the average of metric node_cpu_usage_percentage (Insights.Container/nodes) is greater than 80, split by host"
        assert facts["description_sentence"].endswith("measured over 5 minutes and evaluated every 1 minute")
        assert alert["product"] == "Microsoft.ContainerService/managedClusters"
        assert alert["action_groups"] == ["ag-oncall"] and alert["condition"]["criteria"][0]["threshold"] == 80
        assert facts["kql"]["query"] == "" and facts["kql"]["source"] is None

    def test_a_dynamic_threshold(self):
        resource = {"type": "Microsoft.Insights/metricAlerts", "name": "d", "properties": {"severity": 2, "criteria": {"odata.type": "Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria", "allOf": [
            {"criterionType": "DynamicThresholdCriterion", "name": "m", "metricName": "Percentage CPU", "operator": "GreaterThan", "timeAggregation": "Average", "alertSensitivity": "High"}]}}}
        sentence = read_alert(json.dumps(resource))["alert"]["condition_sentence"]
        assert sentence == "the average of metric Percentage CPU is greater than (dynamic threshold, sensitivity High)"

    def test_several_criteria_are_joined(self):
        resource = {"type": "Microsoft.Insights/metricAlerts", "name": "m", "properties": {"criteria": {"allOf": [
            {"criterionType": "StaticThresholdCriterion", "metricName": "A", "operator": "GreaterThan", "threshold": 1, "timeAggregation": "Total"},
            {"criterionType": "StaticThresholdCriterion", "metricName": "B", "operator": "LessThan", "threshold": 2, "timeAggregation": "Minimum"}]}}}
        assert " and " in read_alert(json.dumps(resource))["alert"]["condition_sentence"]

    def test_a_web_test(self):
        resource = {"type": "Microsoft.Insights/metricAlerts", "name": "w", "properties": {"criteria": {"odata.type": "Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria", "failedLocationCount": 3}}}
        assert read_alert(json.dumps(resource))["alert"]["condition_sentence"] == "the web test fails from at least 3 locations"

    def test_a_nested_deployment_resolves_the_name_and_scope(self):
        alert = read_alert(fixture("nested_deployment.arm.json"))["alert"]
        assert alert["name"] == "Tunnel bandwidth low - vnet-gw-prod-east"
        assert alert["scopes"][0].endswith("/providers/Microsoft.Network/virtualNetworkGateways/vnet-gw-prod-east")


class TestReadAlert:
    def test_nothing_given(self):
        facts = read_alert("", "")
        assert facts["has_definition"] is False and facts["alert"] is None and facts["warnings"] == []

    def test_text_that_is_not_json_is_reported_and_given_to_the_writer_as_it_is(self):
        facts = read_alert("{ not json")
        assert facts["alert"] is None and facts["arm"]["parsed"] is False
        assert "not valid JSON" in facts["warnings"][0] and facts["has_definition"] is False

    def test_json_without_an_alert_says_so(self):
        facts = read_alert(json.dumps({"resources": [{"type": "Microsoft.Network/virtualNetworkGateways", "name": "gw"}]}))
        assert facts["arm"]["parsed"] is True and facts["alert"] is None and "No log alert" in facts["warnings"][0]

    def test_a_query_alone_is_enough_to_ground_the_writer(self):
        facts = read_alert("", "AzureDiagnostics | where Category == 'GatewayDiagnosticLog'")
        assert facts["has_definition"] is True and facts["alert"] is None and facts["kql"]["source"] == "input"

    def test_the_query_you_give_wins_over_the_template_and_you_are_told(self):
        facts = read_alert(fixture("vpn_log_alert.arm.json"), "AzureDiagnostics | take 1")
        assert facts["kql"]["query"] == "AzureDiagnostics | take 1" and facts["kql"]["source"] == "input"
        assert any("differs from the query in the ARM template" in w for w in facts["warnings"])

    def test_the_same_query_with_other_spacing_is_not_a_difference(self):
        arm = json.loads(strip_json_comments(fixture("vpn_log_alert.arm.json")))
        query = arm["resources"][0]["properties"]["criteria"]["allOf"][0]["query"]
        assert not any("differs" in w for w in read_alert(fixture("vpn_log_alert.arm.json"), query.replace("\n", " \n  "))["warnings"])

    def test_with_several_alerts_the_one_named_is_chosen_and_the_rest_are_listed(self):
        document = {"resources": [
            {"type": "Microsoft.Insights/metricAlerts", "name": "First alert", "properties": {}},
            {"type": "Microsoft.Insights/metricAlerts", "name": "Second alert", "properties": {}}]}
        facts = read_alert(json.dumps(document), alert_name="second  ALERT")
        assert facts["alert"]["name"] == "Second alert" and facts["arm"]["alerts_found"] == ["First alert", "Second alert"]
        assert any("defines 2 alerts" in w and "First alert" in w for w in facts["warnings"])

    def test_a_log_alert_without_a_query_is_flagged(self):
        resource = {"type": "Microsoft.Insights/scheduledQueryRules", "name": "a", "properties": {"criteria": {"allOf": [{"threshold": 1}]}}}
        assert any("has no query" in w for w in read_alert(json.dumps(resource))["warnings"])

    def test_nothing_raises_on_odd_shapes(self):
        for text in ('"just a string"', "[]", "[1, 2]", '{"resources": "x"}', '{"resources": [null, 5]}', '{"type": "Microsoft.Insights/metricAlerts", "properties": null}'):
            read_alert(text)

    def test_the_writer_reads_the_facts_and_the_query(self):
        text = facts_for_prompt(read_alert(fixture("vpn_log_alert.arm.json")))
        assert "Alert type: log alert (scheduledQueryRules); the IRP's Source is Log" in text
        assert "the number of rows returned by the alert query is greater than 0" in text and "Severity (from the ARM template): Error" in text
        assert "<alert_query>\nAzureDiagnostics" in text and "tables: AzureDiagnostics" in text and "filter Category == TunnelDiagnosticLog" in text
        assert "<arm_alert>" in text and "Action group(s): <actionGroupName>" in text

    def test_with_nothing_there_the_writer_reads_nothing(self):
        assert facts_for_prompt(read_alert("", "")) == ""


class TestKql:
    def test_the_first_table_of_a_query(self):
        assert analyze_kql("Perf\n| where CounterName == 'x'")["tables"] == ["Perf"]

    def test_let_names_are_not_tables_but_what_they_read_is(self):
        kql = analyze_kql("let recent = AzureDiagnostics | where TimeGenerated > ago(1h);\nrecent\n| summarize count()")
        assert kql["tables"] == ["AzureDiagnostics"]

    def test_joins_and_unions(self):
        assert analyze_kql("A\n| join kind=inner (B | where x == 1) on k")["tables"] == ["A", "B"]
        assert analyze_kql("union kind=outer T1, T2\n| count")["tables"] == ["T1", "T2"]

    def test_a_column_list_is_not_mistaken_for_a_table(self):
        assert analyze_kql("Heartbeat\n| project\n    Computer,\n    TimeGenerated\n| where Computer != ''")["tables"] == ["Heartbeat"]

    def test_filters_with_one_or_many_values(self):
        kql = analyze_kql('AzureDiagnostics | where Category in ("A", "B") and ResourceType =~ "VIRTUALNETWORKGATEWAYS" and ResultType == 500')
        assert {"column": "Category", "operator": "in", "values": ["A", "B"]} in kql["filters"]
        assert {"column": "ResourceType", "operator": "=~", "values": ["VIRTUALNETWORKGATEWAYS"]} in kql["filters"]
        assert {"column": "ResultType", "operator": "==", "values": ["500"]} in kql["filters"]

    def test_summarize_and_output_columns(self):
        kql = analyze_kql("Perf | summarize avg(CounterValue), Max = max(CounterValue) by Computer, bin(TimeGenerated, 5m)")
        assert kql["aggregations"] == ["avg(CounterValue)", "Max = max(CounterValue)"]
        assert kql["group_by"] == ["Computer", "bin(TimeGenerated, 5m)"] and kql["output_columns"][-1] == "Max"

    def test_an_explicit_project_names_the_output(self):
        assert analyze_kql("T | extend a = 1 | project Time = TimeGenerated, Node")["output_columns"] == ["Time", "Node"]

    def test_comments_are_ignored_but_slashes_in_strings_are_not_comments(self):
        assert strip_kql_comments('T // c\n| where u == "http://x"') == 'T \n| where u == "http://x"'
        assert analyze_kql('T // AzureDiagnostics in a comment\n| where u == "http://x"')["tables"] == ["T"]

    def test_unbalanced_text_and_unresolved_expressions_are_warned_about(self):
        assert any("unbalanced" in w for w in analyze_kql('T | where a == "x')["warnings"])
        assert any("ARM expression" in w for w in analyze_kql("T | where a == '<unresolved: parameters(x)>'")["warnings"])

    def test_empty_and_odd_input_never_raises(self):
        assert analyze_kql(None)["tables"] == [] and analyze_kql("   ")["tables"] == []
        analyze_kql(";;;|||(((")

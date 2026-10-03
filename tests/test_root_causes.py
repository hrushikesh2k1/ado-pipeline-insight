"""Known failure causes: recognised from the error text alone, each with a pasteable (and valid) YAML example."""
import pytest
import yaml

from app.services.failure_kind import best_error_line, classify_failure, is_generic
from app.services.root_causes import identify_cause

# The error texts below are the ones seen on a real monitoring pipeline.
UNRESOLVED_VARIABLE = ("ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/$(storageAccountName)' under resource group "
                       "'cldops-stamp-usgovvirginia-rg' was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix")
AUTHORIZATION = ("ERROR: (AuthorizationFailed) The client '***' with object id '...' does not have authorization to perform action "
                 "'Microsoft.Storage/storageAccounts/read' over scope '/subscriptions/1234/resourceGroups/rg' or the scope is invalid.")
PARAM_TYPE = ("Deployment template validation failed: 'The provided value for the template parameter 'defaultEmailGroup' is not valid. "
              "Expected a value of type 'Boolean', but received a value of type 'String'.'")
POWER_STATE = "##[error]OperationNotAllowed: Operations are not allowed when the managed cluster is not in the Running power state."
RG_CONSTRAINT = "Failed to check the resource group status. Error: \"\\\"resourceGroupName\\\" should satisfy the constraint - \\\"Pattern\\\": /^[-\\w\\._\\(\\)]+$/\""
PLAIN_NOT_FOUND = "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/stprod01' under resource group 'rg-prod' was not found."


def test_an_unresolved_variable_is_named_and_beats_the_generic_not_found():
    cause = identify_cause(UNRESOLVED_VARIABLE)
    assert cause.key == "unresolved_variable" and cause.signature == "unresolved_variable:storageaccountname"
    assert "`$(storageAccountName)`" in cause.diagnosis and "never set" in cause.diagnosis
    assert "- name: storageAccountName" in cause.yaml_fix and "variables:" in cause.yaml_fix


def test_a_missing_permission_names_the_action_and_the_scope():
    cause = identify_cause(AUTHORIZATION)
    assert cause.key == "authorization_failed" and cause.signature == "authorization:microsoft.storage/storageaccounts/read"
    assert "`Microsoft.Storage/storageAccounts/read`" in cause.diagnosis and "/subscriptions/1234/resourceGroups/rg" in cause.diagnosis
    assert "cannot be fixed in the pipeline file" in cause.remediation  # honest: the YAML is only a guard


def test_a_plain_missing_resource_is_not_mistaken_for_a_variable_problem():
    cause = identify_cause(PLAIN_NOT_FOUND)
    assert cause.key == "resource_not_found" and "stprod01" in cause.diagnosis and "rg-prod" in cause.diagnosis
    assert "dependsOn" in cause.yaml_fix


def test_template_parameter_type_mismatch_suggests_the_right_literal():
    cause = identify_cause(PARAM_TYPE)
    assert cause.signature == "template_param:defaultemailgroup"
    assert "`defaultEmailGroup` expects a value of type Boolean, but the pipeline passes a String" in cause.diagnosis
    assert "-defaultEmailGroup true" in cause.yaml_fix
    assert "-count 1" in identify_cause("template parameter 'count' is not valid. Expected a value of type 'Int', but received a value of type 'String'").yaml_fix


@pytest.mark.parametrize("text,key", [(POWER_STATE, "cluster_not_running"), (RG_CONSTRAINT, "resource_group_name")])
def test_other_known_causes(text, key):
    assert identify_cause(text).key == key


@pytest.mark.parametrize("text", [None, "", "Process completed with exit code 1.", "echo $(Build.BuildId)", "Error - Resource - Unavailable", "dial tcp: i/o timeout"])
def test_no_cause_is_claimed_without_evidence(text):
    assert identify_cause(text) is None


@pytest.mark.parametrize("text", [UNRESOLVED_VARIABLE, AUTHORIZATION, PLAIN_NOT_FOUND, PARAM_TYPE, POWER_STATE, RG_CONSTRAINT])
def test_every_pasteable_block_is_valid_yaml_and_labelled_an_example(text):
    cause = identify_cause(text)
    parsed = yaml.safe_load(cause.yaml_fix)  # a snippet the customer cannot paste would be worse than none
    assert parsed is not None and cause.yaml_fix.startswith("# example, not from your file")
    assert cause.kind == "persistent" and classify_failure(text) == "persistent"


class TestErrorLines:
    def test_boilerplate_is_skipped_for_the_informative_line(self):
        text = ("##[error]Check out the troubleshooting guide to see if your issue is addressed: https://docs.example "
                "##[error]Failed to check the resource group status. Error: bad name")
        assert best_error_line(text) == "Failed to check the resource group status. Error: bad name"

    def test_falls_back_to_the_boilerplate_when_it_is_all_there_is(self):
        assert best_error_line("##[error]Script failed with exit code: 1") == "Script failed with exit code: 1"
        assert best_error_line(None) == "" and best_error_line("  \n ") == ""

    def test_long_lines_are_trimmed_and_generic_detection(self):
        assert len(best_error_line("x" * 500)) == 200
        assert is_generic("##[error]Script failed with exit code: 1") and is_generic(None) and not is_generic("chart not found")


@pytest.mark.parametrize("text,expected", [
    (AUTHORIZATION, "persistent"), (PARAM_TYPE, "persistent"), (POWER_STATE, "persistent"), (RG_CONSTRAINT, "persistent"),
    ("Process completed with exit code 1.", "unknown"), ("dial tcp 10.0.0.1:443: i/o timeout", "transient"),
])
def test_classification_uses_the_known_causes(text, expected):
    assert classify_failure(text) == expected

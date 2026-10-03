"""Known failure causes: recognise them in a step's error text and say precisely what is wrong and how to fix it.

Each cause is recognised from the error text alone, states only what that text shows, and carries a YAML block the
customer can paste. The YAML is always an example to adapt (the values it needs are not in the error), which the
advice labels as such; a real diff against the customer's file is only produced elsewhere, when the step is found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Cause:
    key: str
    signature: str  # identical for the same underlying problem, so duplicates across steps and stages can be merged
    kind: str  # "persistent": retrying only repeats it
    diagnosis: str
    remediation: str
    yaml_fix: str


_MACRO = re.compile(r"\$\(([A-Za-z_][\w.\-]*)\)")
_PROBLEM = re.compile(r"not found|does not exist|invalid|not valid|constraint|cannot|unable|failed|error", re.IGNORECASE)
_AUTH = re.compile(r"does not have authorization to perform action '([^']+)'(?: over scope '([^']*)')?", re.IGNORECASE)
_NOT_FOUND = re.compile(r"Resource '([^']+)' under resource group '([^']+)' was not found", re.IGNORECASE)
_RG_CONSTRAINT = re.compile(r"resourceGroupName.{0,20}should satisfy the constraint", re.IGNORECASE)
_POWER_STATE = re.compile(r"not in the Running power state", re.IGNORECASE)
_PARAM_TYPE = re.compile(
    r"template parameter '([^']+)' is not valid\.\s*Expected a value of type '([^']+)', but received a value of type '([^']+)'", re.IGNORECASE)

_SAMPLE_VALUE = {"boolean": "true", "bool": "true", "int": "1", "integer": "1", "array": "'[]'", "object": "'{}'"}


MAX_VARIABLES = 4  # how many unset variables one cause names (a scope with three of them is still one problem)


def _listed(items: list[str], quote: str = "`") -> str:
    shown = [f"{quote}{item}{quote}" for item in items]
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def _unresolved_variable(text: str) -> Cause | None:
    names = list(dict.fromkeys(_MACRO.findall(text)))  # distinct, in the order the error shows them
    if not names or not _PROBLEM.search(text):
        return None
    shown = names[:MAX_VARIABLES]
    many = len(shown) > 1
    auth = _AUTH.search(text)
    why_auth = (" Azure reports it as an authorization error, but the scope in that message contains the literal variable (\"or the scope is invalid\"), "
                "so the scope is invalid: granting permissions will not fix it." if auth else "")
    entries = "".join(f"  - name: {name}\n    value: '<value>'\n" for name in shown)
    return Cause(
        "unresolved_variable", f"unresolved_variable:{','.join(sorted(n.lower() for n in names))}", "persistent",
        f"The error contains the literal text {_listed([f'$({n})' for n in shown])}. Azure DevOps leaves a macro untouched when the variable has no value at the time "
        f"the step runs, so the pipeline {'variables' if many else 'variable'} {_listed(shown)} {'were' if many else 'was'} never set for this step.{why_auth}",
        f"Give {_listed(shown)} {'a value' if not many else 'values'} before this step runs: define {'them' if many else 'it'} under `variables:`, link the variable group "
        f"that holds {'them' if many else 'it'}, or, if an earlier step sets {'them' if many else 'it'}, make sure that step runs first in the same job (or pass the value "
        "between jobs with `isOutput`).",
        f"# example, not from your file: give the variable{'s' if many else ''} a value before this step runs\nvariables:\n{entries}"
        "# or link the variable group that defines it:\n# variables:\n#   - group: <variable group name>",
    )


def _role_for(action: str) -> str:
    """The built-in role to suggest: Reader for a read action; otherwise the customer has to choose a role that includes the action."""
    return "Reader" if action.lower().endswith("/read") else "<a role that includes the action>"


def _authorization(text: str) -> Cause | None:
    match = _AUTH.search(text)
    if not match:
        return None
    action, scope = match.group(1), match.group(2) or ""
    where = f" over scope `{scope}`" if scope else ""
    return Cause(
        "authorization_failed", f"authorization:{action.lower()}", "persistent",
        f"The identity that runs this step does not have permission to perform `{action}`{where}.",
        f"Grant that identity a role that includes `{action}` (for example Reader, or a custom role) on the resource group or resource, or point the "
        f"step at a service connection that already has it. Someone who can assign roles can run: `az role assignment create --assignee <object id of "
        f"the identity> --role {_role_for(action)} --scope {scope or '<resource group or resource id>'}`. A missing permission cannot be fixed in the "
        "pipeline file; the YAML below only makes the step fail early with a clear message instead of in the middle of the deployment.",
        "# example, not from your file: fail early, and show what the identity can do\n- task: AzureCLI@2\n  displayName: Check access before deploying\n"
        "  inputs:\n    azureSubscription: '<your service connection>'\n    scriptType: bash\n    scriptLocation: inlineScript\n    inlineScript: |\n"
        "      az role assignment list --assignee \"$(az account show --query user.name -o tsv)\" --all --query \"[].{role:roleDefinitionName, scope:scope}\" -o table",
    )


def _not_found(text: str) -> Cause | None:
    match = _NOT_FOUND.search(text)
    if not match:
        return None
    resource, group = match.group(1), match.group(2)
    return Cause(
        "resource_not_found", f"not_found:{resource.lower()}", "persistent",
        f"`{resource}` does not exist in resource group `{group}` at the moment this step runs.",
        "Create the resource earlier in the pipeline or correct its name. If another stage or job creates it, make this one wait for that with `dependsOn`.",
        "# example, not from your file: wait for the stage or job that creates the resource\ndependsOn: <stage or job that creates it>",
    )


def _resource_group_name(text: str) -> Cause | None:
    if not _RG_CONSTRAINT.search(text):
        return None
    return Cause(
        "resource_group_name", "resource_group_name", "persistent",
        "The resource group name given to the step is empty or has characters Azure does not allow (only letters, digits, `-`, `_`, `.` and "
        "parentheses are valid). This is usually a variable that is empty or was not expanded.",
        "Find the variable that supplies the resource group name, make sure it has a value when this step runs, and print it in an earlier step to confirm.",
        "# example, not from your file: set the resource group name before the step that uses it\nvariables:\n  - name: resourceGroupName\n    value: '<resource group name>'",
    )


def _power_state(text: str) -> Cause | None:
    if not _POWER_STATE.search(text):
        return None
    return Cause(
        "cluster_not_running", "aks_not_running", "persistent",
        "The AKS cluster is stopped (not in the Running power state), so Azure rejects operations on it.",
        "Start the cluster before this step, or keep it running while deployments happen.",
        "# example, not from your file: start the cluster first if it is stopped\n- task: AzureCLI@2\n  displayName: Make sure the cluster is running\n  inputs:\n"
        "    azureSubscription: '<your service connection>'\n    scriptType: bash\n    scriptLocation: inlineScript\n    inlineScript: |\n"
        "      state=$(az aks show -g <resource group> -n <cluster> --query powerState.code -o tsv)\n"
        "      if [ \"$state\" != \"Running\" ]; then az aks start -g <resource group> -n <cluster>; fi",
    )


def _parameter_type(text: str) -> Cause | None:
    match = _PARAM_TYPE.search(text)
    if not match:
        return None
    param, expected, received = match.groups()
    sample = _SAMPLE_VALUE.get(expected.lower(), "'<value>'")
    return Cause(
        "template_parameter_type", f"template_param:{param.lower()}", "persistent",
        f"The ARM template parameter `{param}` expects a value of type {expected}, but the pipeline passes a {received}.",
        f"Pass `{param}` as a real {expected} value (not a quoted string) where the template is deployed: in the `overrideParameters` input or in the parameters file.",
        f"# example, not from your file: pass {param} as a {expected}\noverrideParameters: '-{param} {sample}'",
    )


_RECOGNISERS = (_unresolved_variable, _authorization, _not_found, _resource_group_name, _power_state, _parameter_type)


def identify_cause(excerpt: str | None) -> Cause | None:
    """The known cause an error text shows, or None. The first matching recogniser wins, most specific first."""
    text = (excerpt or "").strip()
    if not text:
        return None
    for recogniser in _RECOGNISERS:
        cause = recogniser(text)
        if cause:
            return cause
    return None

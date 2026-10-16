"""Focused review guidance, selected from file paths and actual source structure."""
from __future__ import annotations

import re
from typing import Any

import yaml

AZURE_PIPELINES_GUIDE = (
    "Azure DevOps pipelines: trace the actual outcome through triggers, parameters, "
    "template expressions, stage/job conditions, dependencies and continueOnError. "
    "Check referenced branches, files, templates and resources using available evidence; "
    "repository tools cannot prove an external resource exists. For each supported "
    "environment and region, trace the selected subscription, resource group, identity "
    "and target resource. A warning or skipped task must not produce a clean success "
    "report when required validation did not run. Check cleanup and status reporting "
    "on the intended success and failure paths. Give a concrete parameter/branch/failure case and its result."
)
CLOUD_OPERATIONS_GUIDE = (
    "Cloud operations: distinguish a successful empty result from missing data and from "
    "a failed or unauthorized request. Do not treat API errors, missing telemetry or "
    "partial input as zero issues or successful validation. Check bounded retries for "
    "throttling and transient errors, request and overall timeouts, preserved error "
    "details, and cleanup after failure. Check secrets and temporary access tokens for "
    "least privilege, adequate but bounded lifetime, and exposure in logs. For destructive "
    "actions, verify required lookups and identity checks fail closed. Use the correct "
    "composite resource identity, such as subscription, resource group and resource name. "
    "Report a concrete failure in the changed code, not a generic demand to add retries."
)
TYPESCRIPT_GUIDE = (
    "TypeScript and UI: trace received data through normalization, state, rendering and "
    "user actions. Missing identity fields must not silently become duplicate IDs. Check "
    "null and invalid values, boundary conditions, overlapping polls and stale responses, "
    "and whether controls are enabled in the states shown. Preserve useful error details. "
    "For displayed counts or summaries, verify the counted unit matches the label."
)

_PIPELINE_PATH = re.compile(r"(^|/)(\.?azure-pipelines/|azure-pipelines(?:[._-][^/]*)?\.ya?ml$)", re.I)
_CLOUD_PATH = re.compile(r"(^|/)(azure|cloud|deploy(?:ment)?|infra(?:structure)?|ops|runbooks?|automation)([/_.-]|$)", re.I)
_CLOUD_CODE = re.compile(r"\b(?:az\s+(?:account|group|resource|deployment|webapp|storage|monitor|keyvault|aks)|(?:Get|Set|Remove|New|Connect|Invoke)-Az\w+|(?:import|from)\s+(?:azure|boto3)\b|AzureCLI@|AzurePowerShell@|management\.azure\.com|DefaultAzureCredential)", re.I)


def is_azure_pipeline(path: str, text: str) -> bool:
    path = path.replace('\\', '/').lower().lstrip('/')
    if not path.endswith(('.yml', '.yaml')) or path.startswith('.github/workflows/'):
        return False
    # Do not parse arbitrarily large YAML or every file of the repository.
    if len(text) > 150000:
        return bool(_PIPELINE_PATH.search(path))
    try:
        data: Any = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError, ValueError):
        return bool(_PIPELINE_PATH.search(path))
    if isinstance(data, dict) and ('apiVersion' in data or 'kind' in data):
        return False
    if _PIPELINE_PATH.search(path):
        return True
    if not isinstance(data, dict):
        return False
    for key, node_keys in (('stages', ('stage', 'template')), ('jobs', ('job', 'deployment', 'template'))):
        nodes = data.get(key)
        if isinstance(nodes, list) and any(isinstance(node, dict) and (
            any(k in node for k in node_keys) or any(str(k).startswith('${{') for k in node)
        ) for node in nodes):
            return True
    steps = data.get('steps')
    return isinstance(steps, list) and any(isinstance(s, dict) and any(k in s for k in ('task', 'script', 'bash', 'pwsh', 'powershell', 'template', 'checkout')) for s in steps)


def focused_guides(language: str, path: str, text: str) -> list[str]:
    guides = []
    if language in ('TypeScript', 'TypeScript (React)', 'JavaScript', 'JavaScript (React)'):
        guides.append(TYPESCRIPT_GUIDE)
    if language == 'YAML' and is_azure_pipeline(path, text):
        guides.append(AZURE_PIPELINES_GUIDE)
    if language in ('Python', 'PowerShell', 'Shell') and (_CLOUD_PATH.search(path) or _CLOUD_CODE.search(text)):
        guides.append(CLOUD_OPERATIONS_GUIDE)
    return guides

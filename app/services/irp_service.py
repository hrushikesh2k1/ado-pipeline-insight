from __future__ import annotations

import logging
import re
from typing import Any

from core.ado_client import AzureDevOpsClient
from core.openai_client import PipelineRecommendationClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

IRP_SYSTEM_PROMPT = """You are a Principal Cloud Site Reliability Engineer (SRE) and Incident Commander specializing in Azure, ARM templates, and enterprise incident response plans.
Your task is to generate an Incident Response Plan (IRP) in GitHub-flavored Markdown following the EXACT organization standard below.

MANDATORY STRUCTURE & SECTIONS TO INCLUDE:

# [Alert Name]

# Alert Details

| **Alert** | [Alert Name] |
| --- | --- |
| **Description** | *This alert is designed to trigger when/if [Condition / Symptoms], deployed in [Environment]. It is a critical issue when this occurs and the system cannot be accessible.* |
| **Severity** | [Critical / Error / Warning / Info] |
| **Source** | [Log / Metric] |
| **Root Cause** | - **Case 1 : ** [Primary Failure Mode 1] - **Case 2 : ** [Primary Failure Mode 2] - **Case 3 : ** [Primary Failure Mode 3] - **Case 4 : ** [Primary Failure Mode 4] |
| **Product** | [Product / Component Name, e.g. Common / Infrastructure] |

# Prerequisites

- Access Packages:
  - Commercial: https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages
  - Gov Cloud: https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages
- Required Azure IAM Roles: Network Contributor / Reader on Target Resource Group.

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Check **the connection / resource status | 1. Review the **Query Result** and check the **Error Details**.<br>2. Check if the root cause indicates transient glitches, configuration drift, or host events.<br>3. Run Azure CLI / PowerShell command to verify live status: `az ...` or `Get-Az...` | Ref : |
| **Check **the resource health | 1. Navigate to Azure portal -> Resource Health blade.<br>2. Verify status is **Available**.<br>3. If Unavailable, inspect platform maintenance logs. | |
| **Case 1**: [Primary Failure Mode 1] | [Detailed actionable remediation steps, CLI/PowerShell commands] | |
| **Case 2**: [Primary Failure Mode 2] | [Detailed actionable remediation steps, CLI/PowerShell commands] | |
| **Case 3**: [Primary Failure Mode 3] | [Detailed actionable remediation steps, CLI/PowerShell commands] | |
| **Case 4**: [Primary Failure Mode 4] | [Detailed actionable remediation steps, CLI/PowerShell commands] | |
| Please find the KUSTO queries for the respective Causes | [Kusto Analysis - KQL queries for investigating alert logs] | |
| Health Check | Repeat Step 1 & 2 to ensure resource status is Healthy / Available. | |
| **Confirm **that the alert has stopped firing in CNC / Monitoring | Confirm alert resolution in Azure Monitor / CNC. | |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| **[Test Scenario 1 (e.g. Deletion / Reset)]** | 1. Via Azure Portal: Navigate to resource -> Settings -> Action -> Confirm.<br>2. Via PowerShell: `Remove-Az...` or `Restart-Az...`<br>3. Via Azure CLI: `az ...` |
| **[Test Scenario 2 (e.g. Config Mismatch)]** | 1. Navigate to resource -> Configuration.<br>2. Edit setting to simulate mismatch.<br>3. Verify alert triggers within latency window. |

## Overview

*This alert is designed to trigger when/if [Detailed trigger statement]. It is a critical operational issue when this occurs.*

## Alert Properties

|  |  |
| --- | --- |
| **Severity:** | * [x] Critical * [ ] Error * [ ] Warning * [ ] Info |
| **Signal Type:** | * [x] Log * [ ] Metric |

## Remediation Overview

## Investigation Steps

- Access Packages:
  - Commercial: https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages
  - Gov Cloud: https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages
- Step-by-step diagnostic workflow:
  1. Navigate to the Azure Portal.
  2. Locate the resource group (Naming convention: `<location>-<resourceType>-<customerProjectName>`).
  3. Run diagnostic commands:
     ```powershell
     # Diagnostic verification command
     Get-AzResource -Name "<ResourceName>" -ResourceGroupName "<ResourceGroupName>"
     ```
  4. Inspect live metrics & diagnostic logs in Log Analytics.

## RCA & Mitigation

| **Scenario** | **Application Impact** | **Alert Latency (min)** | **Related alerts** | **Response Plan** |
| --- | --- | --- | --- | --- |
| **[Scenario 1]** | Users unable to connect; risk of SLA breach. | [X] mins | - Critical: [Alert Name] | - [Response Guide Link / Steps] |
| **[Scenario 2]** | Partial service degradation / latency spike. | [X] mins | - Warning: [Alert Name] | - [Troubleshooting Guide Link / Steps] |

## Example Story Submissions

- [User Story 123456](https://dev.azure.com/org/proj/_workitems/edit/123456): Critical - [Alert Name]

## References

- [Official Azure Documentation](https://learn.microsoft.com/en-us/azure/)

## Alert Enhancement

- Enhanced result set mapping:

| **Field Name** | **Description** |
| --- | --- |
| [Field 1 from Output Columns] | [Detailed description of Field 1] |
| [Field 2 from Output Columns] | [Detailed description of Field 2] |
| [Field 3 from Output Columns] | [Detailed description of Field 3] |

## Lessons learned

- [Key post-incident insight 1]
- [Key post-incident insight 2]

CRITICAL RULES:
1. Ground all commands in official Azure documentation CLI (`az ...`), PowerShell (`Get-Az...`), and KQL queries.
2. Fill every field from the provided Alert Name, CVRD, Alert Output Columns, ARM Template Context, and Alert Details.
3. REMEDIATION STEPS TABLE FORMAT: The Remediation Steps table MUST have EXACTLY 3 columns with the exact header:
   | **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
   DO NOT create a 4th column (such as "EXPECTED OUTCOME"). All diagnostic actions, commands, and expected outcomes belong in the ACTION or ADDITIONAL COMMENTS column. Escape any pipe character in queries as `\\|` or enclose in backticks.
4. ABSOLUTELY NO AUTHORING CHECKLIST:
   DO NOT generate or include any "IRP Authoring Checklist", "Authoring Checklist", "Checklist (with Examples)", or template writing guidelines anywhere in the output. The output must contain ONLY the actual runbook content.
5. Return pure Markdown only.
"""


def _split_markdown_table_row(row: str) -> list[str]:
    trimmed = row.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]

    cells = []
    current = []
    in_code = False
    for idx, ch in enumerate(trimmed):
        prev = trimmed[idx - 1] if idx > 0 else ""
        if ch == "`" and prev != "\\":
            in_code = not in_code
            current.append(ch)
        elif ch == "|" and not in_code and prev != "\\":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def _clean_irp_markdown(text: str) -> str:
    """Post-process generated IRP markdown to strip authoring checklists and normalize tables."""
    if not text:
        return ""
    # Strip any authoring checklist section (e.g., ## IRP Authoring Checklist, # IRP Authoring Checklist, etc.)
    cleaned = re.sub(
        r"(?i)\n*#+\s*(?:IRP\s+)?Authoring\s+Checklist[\s\S]*$",
        "",
        text,
    ).strip()

    # Process tables to ensure Remediation Steps has strictly 3 columns: STEPS | ACTION | ADDITIONAL COMMENTS
    lines = cleaned.split("\n")
    new_lines = []
    in_remediation_table = False

    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()

        # Check if line is a table header for Remediation Steps
        if trimmed.startswith("|") and ("STEPS" in trimmed.upper() or "STEP" in trimmed.upper()) and "ACTION" in trimmed.upper():
            in_remediation_table = True
            new_lines.append("| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |")
            # Check next line for divider
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                new_lines.append("| --- | --- | --- |")
                i += 2
                continue
            i += 1
            continue

        if in_remediation_table:
            if not trimmed.startswith("|") or trimmed.startswith("#") or not trimmed:
                in_remediation_table = False
                new_lines.append(line)
                i += 1
                continue

            # It's a row in the remediation table
            raw_cells = _split_markdown_table_row(trimmed)
            # Skip divider rows if any
            if all(c.replace("-", "").strip() == "" for c in raw_cells):
                i += 1
                continue

            if len(raw_cells) == 3:
                step = raw_cells[0]
                action = raw_cells[1]
                comments = raw_cells[2]
                new_lines.append(f"| {step} | {action} | {comments} |")
            elif len(raw_cells) == 2:
                new_lines.append(f"| {raw_cells[0]} | {raw_cells[1]} | |")
            elif len(raw_cells) > 3:
                # More than 3 cells (e.g. from EXPECTED OUTCOME column or unescaped KQL pipes)
                step = raw_cells[0]
                comments = raw_cells[-1] if len(raw_cells[-1]) < 60 and not any(k in raw_cells[-1].lower() for k in ["where", "project", "summarize", "az ", "kubectl"]) else ""
                middle_cells = raw_cells[1:-1] if comments else raw_cells[1:]
                action = "<br>".join([c for c in middle_cells if c])
                new_lines.append(f"| {step} | {action} | {comments} |")
            else:
                new_lines.append(line)
            i += 1
            continue

        new_lines.append(line)
        i += 1

    return "\n".join(new_lines).strip()


class IrpService:
    def __init__(self, settings=None, openai_client: PipelineRecommendationClient | None = None):
        self.settings = settings or get_settings()
        self.openai_client = openai_client

    def _get_client(self) -> PipelineRecommendationClient | None:
        if self.openai_client:
            return self.openai_client
        endpoint = getattr(self.settings, "azure_openai_endpoint", None)
        deployment = getattr(self.settings, "azure_openai_deployment", None)
        api_version = getattr(self.settings, "azure_openai_api_version", "2024-02-01")
        api_key = getattr(self.settings, "azure_openai_api_key", None)
        if not endpoint or not deployment:
            return None
        try:
            return PipelineRecommendationClient(
                endpoint,
                deployment,
                api_version,
                api_key or None,
            )
        except Exception as e:
            logger.warning("Could not initialize Azure OpenAI client for IRP: %s", e)
            return None

    def generate_irp(
        self,
        alert_name: str,
        target_resource: str | None = None,
        severity: str = "Sev-1",
        trigger_condition: str | None = None,
        owning_team: str | None = None,
        environment: str | None = "Production",
        cvrd: str | None = None,
        alert_output_columns: str | None = None,
        arm_template_context: str | None = None,
        alert_details: str | None = None,
        irp_template: str | None = None,
        irp_example: str | None = None,
        additional_notes: str | None = None,
    ) -> dict[str, Any]:
        """Generate an Incident Response Plan (IRP) adhering to uploaded templates, examples, and official Azure documentation."""
        client = self._get_client()
        sanitized_alert = alert_name.strip()
        effective_resource = (target_resource or "").strip() or "Azure Resource / Alert Target"
        slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", sanitized_alert.replace(" ", "-")).strip("-")
        suggested_path = f"/Incident-Response-Plans/{slug}"

        user_prompt_data = {
            "alert_name": sanitized_alert,
            "cvrd": (cvrd or "").strip(),
            "alert_output_columns": (alert_output_columns or "").strip(),
            "arm_template_context": (arm_template_context or "").strip(),
            "alert_details": (alert_details or "").strip(),
            "target_resource": effective_resource,
            "severity": severity or "Sev-1",
            "trigger_condition": trigger_condition or "Metric threshold breached for > 5 minutes",
            "owning_team": owning_team or "Cloud Operations & SRE",
            "environment": environment or "Production",
            "irp_template": (irp_template or "").strip(),
            "irp_example": (irp_example or "").strip(),
            "additional_notes": (additional_notes or "").strip(),
        }

        if client:
            try:
                system_prompt = (
                    "You are a Principal Cloud Site Reliability Engineer (SRE) and Incident Commander specializing in Azure, ARM templates, and incident response runbooks.\n"
                    "Your task is to generate a comprehensive, highly technical, and production-ready Incident Response Plan (IRP) in GitHub-flavored Markdown.\n\n"
                    "CRITICAL INSTRUCTIONS:\n"
                    "1. STRICT TEMPLATE & SCHEMA CONFORMANCE:\n"
                    "   - If an IRP Template or IRP Example is provided below, you MUST follow its EXACT structure, section headings, ordering, markdown tables, and callouts.\n"
                    "   - Mirror the schema and formatting conventions of the IRP Example perfectly.\n"
                    "2. REMEDIATION STEPS TABLE FORMAT (MANDATORY 3 COLUMNS ONLY):\n"
                    "   - The Remediation Steps table MUST contain EXACTLY 3 columns with the exact header:\n"
                    "     | **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |\n"
                    "   - NEVER create 4 columns or extra columns like 'EXPECTED OUTCOME'. Put all diagnostics, KQL queries, CLI commands, and expected outcomes in ACTION or ADDITIONAL COMMENTS.\n"
                    "   - If table cells contain pipe characters `|` (e.g. in KQL queries), you MUST escape them as `\\|` or wrap in backticks so they do not break table column delimiters.\n"
                    "3. DO NOT INCLUDE ANY AUTHORING CHECKLIST:\n"
                    "   - DO NOT output any 'IRP Authoring Checklist', 'Authoring Checklist', or template guidance at the bottom. Only output the actual runbook content.\n"
                    "4. OFFICIAL DOCUMENTATION & REGULATION ACCURACY:\n"
                    "   - Diagnostic and remediation commands MUST follow official Microsoft Azure documentation, Azure CLI (`az ...`), Azure PowerShell (`Get-Az...`, `Restart-Az...`), and KQL Log Analytics best practices.\n"
                    "   - Incorporate the specific ARM template context, resource types, CVRD, and Alert Output Columns in queries and diagnostic tables.\n"
                    "5. RETURN PURE MARKDOWN ONLY (no conversational chit-chat before or after)."
                )

                prompt_lines = [
                    f"### ALERT METADATA:",
                    f"- Alert Name: {user_prompt_data['alert_name']}",
                    f"- Severity: {user_prompt_data['severity']}",
                    f"- CVRD / Alert ID: {user_prompt_data['cvrd'] or 'N/A'}",
                    f"- Target Resource / Service: {user_prompt_data['target_resource']}",
                    f"- Trigger Condition: {user_prompt_data['trigger_condition']}",
                    f"- Owning Team: {user_prompt_data['owning_team']}",
                    f"- Environment: {user_prompt_data['environment']}",
                ]

                if user_prompt_data["alert_output_columns"]:
                    prompt_lines.append(f"\n### ALERT OUTPUT COLUMNS:\n{user_prompt_data['alert_output_columns']}")

                if user_prompt_data["alert_details"]:
                    prompt_lines.append(f"\n### ALERT DETAILS / REPORT INFO:\n{user_prompt_data['alert_details']}")

                if user_prompt_data["arm_template_context"]:
                    prompt_lines.append(f"\n### ARM TEMPLATE / INFRASTRUCTURE CONTEXT:\n```json\n{user_prompt_data['arm_template_context'][:4000]}\n```")

                if user_prompt_data["irp_template"]:
                    prompt_lines.append(f"\n### MANDATORY IRP TEMPLATE (Follow this exact structure):\n```markdown\n{user_prompt_data['irp_template'][:5000]}\n```")

                if user_prompt_data["irp_example"]:
                    prompt_lines.append(f"\n### REFERENCE IRP EXAMPLE (Mirror this schema and style):\n```markdown\n{user_prompt_data['irp_example'][:5000]}\n```")

                if user_prompt_data["additional_notes"]:
                    prompt_lines.append(f"\n### ADDITIONAL NOTES:\n{user_prompt_data['additional_notes']}")

                user_content = "\n".join(prompt_lines)

                response = client.client.chat.completions.create(
                    model=client.deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.2,
                )
                markdown_text = response.choices[0].message.content or ""
                cleaned_text = _clean_irp_markdown(markdown_text)
                if cleaned_text:
                    return {
                        "alert_name": sanitized_alert,
                        "severity": severity,
                        "target_resource": effective_resource,
                        "markdown_content": cleaned_text,
                        "suggested_wiki_path": suggested_path,
                    }
            except Exception as e:
                logger.warning("Azure OpenAI IRP generation error, using deterministic fallback: %s", e)

        # Fallback generation adhering to template/example if supplied
        fallback_content = _clean_irp_markdown(self._build_deterministic_irp(user_prompt_data))
        return {
            "alert_name": sanitized_alert,
            "severity": severity,
            "target_resource": effective_resource,
            "markdown_content": fallback_content,
            "suggested_wiki_path": suggested_path,
        }

    def _build_deterministic_irp(self, data: dict[str, Any]) -> str:
        name = data["alert_name"]
        resource = data["target_resource"]
        sev = data["severity"]
        team = data["owning_team"]
        env = data["environment"]
        trigger = data["trigger_condition"]
        cvrd = data.get("cvrd") or "CVRD-OPS-001"
        cols = data.get("alert_output_columns") or "TimeGenerated, ResourceGroup, ContainerName, PodName, CpuUsageNanoCores, NodeName"
        details = data.get("alert_details") or f"This alert triggers when/if {name} occurs on {resource}, deployed in {env}."

        # Parse column list for Alert Enhancement table
        col_rows = []
        for col in [c.strip() for c in cols.split(",") if c.strip()]:
            col_rows.append(f"| {col} | Telemetry metric / log property captured during failure event. |")
        col_table = "\n".join(col_rows) if col_rows else "| FieldName | Description of the field |"

        lower_name = name.lower()
        lower_res = resource.lower()

        # =========================================================================
        # 1. AKS / CONTAINER / KUBERNETES / CPU EXCEEDED
        # =========================================================================
        if any(k in lower_name or k in lower_res for k in ["aks", "container", "cpu", "kubernetes", "k8s", "pod", "node"]):
            return f"""# {name}

# Alert Details

| **Alert** | {name} |
| --- | --- |
| **Description** | *{details}* |
| **Severity** | {sev} |
| **Source** | Metrics / Log Analytics |
| **Root Cause** | - **Case 1 : ** Container CPU spike due to application workload increase or infinite loop<br>- **Case 2 : ** Insufficient CPU resource requests/limits configured in pod specs<br>- **Case 3 : ** Node resource exhaustion or node under-provisioned<br>- **Case 4 : ** Misbehaving or runaway container process<br>- **Case 5 : ** Cluster autoscaler not scaling out nodes as expected |
| **Product** | Azure Kubernetes Service (AKS) |

# Prerequisites

- **AKS Cluster Name:** `<aksClusterName>`
- **Resource Group:** `<resourceGroup>`
- **Namespace:** `<namespace>` (if applicable)
- **Access to Azure CLI** with sufficient permissions to query and manage AKS resources
- **Access to Azure Portal** and Azure Monitor Logs (Log Analytics workspace linked to AKS)
- **kubectl configured** to connect to the AKS cluster
- **Azure subscription ID** where the AKS cluster is deployed

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Verify **high CPU container(s) and identify affected pods | 1. Run in Azure Cloud Shell or local CLI with kubectl:<br>`kubectl top pods -n <namespace> --sort-by=cpu`<br>2. Run KQL Log Analytics query:<br>`Perf \| where ObjectName == "K8SContainer" and CounterName == "cpuUsageNanoCores" \| summarize AvgCPU = avg(CounterValue) / 1e9 by InstanceName, bin(TimeGenerated, 5m)` | Identify top offending pods |
| **Check **node resource utilization and health | 1. Run `kubectl top nodes` to check if the underlying node is under CPU pressure.<br>2. Run `kubectl describe node <nodeName>` to check for `MemoryPressure`, `DiskPressure`, or scheduling constraints. | Verify node capacity |
| **Case 1**: Application Workload Spike / Heavy Traffic | 1. Scale out the deployment replicas to distribute the load:<br>`kubectl scale deployment <deploymentName> --replicas=<newCount> -n <namespace>`<br>2. Verify Horizontal Pod Autoscaler (HPA) triggers scaling:<br>`kubectl get hpa -n <namespace>` | Scale replicas |
| **Case 2**: Insufficient CPU Limits in Pod Specification | 1. Inspect pod resource configuration in deployment manifest:<br>`kubectl get deployment <deploymentName> -n <namespace> -o yaml \| grep -A 5 resources:`<br>2. Update `resources.limits.cpu` and `resources.requests.cpu` to accommodate burst traffic and reapply manifest. | Adjust resource limits |
| **Case 3**: Runaway Container Process / Thread Lock | 1. Inspect container logs for stack traces, infinite loops, or unhandled exceptions:<br>`kubectl logs <podName> -n <namespace> --tail=200`<br>2. Perform a graceful rolling restart of the deployment:<br>`kubectl rollout restart deployment/<deploymentName> -n <namespace>` | Restart runaway pods |
| **Case 4**: Node Pool Exhaustion / Cluster Scaling | 1. Check cluster autoscaler events: `kubectl get events -n kube-system \| grep -i autoscaler`<br>2. Manually scale node pool if autoscaler is constrained:<br>`az aks nodepool scale -g <resourceGroup> --cluster-name <clusterName> -n <nodePoolName> --node-count <count>` | Scale node pool |
| **KQL Diagnostic Query** | `ContainerLog \| where TimeGenerated > ago(30m) \| where LogEntry contains "error" or LogEntry contains "exception" \| project TimeGenerated, PodName, LogEntry` | KQL analysis |
| **Health Check & Validation** | 1. Monitor container CPU utilization until it stabilizes below 70%.<br>2. Verify all pods are in `Running` state: `kubectl get pods -n <namespace>` | Confirm health |
| **Confirm **Alert Resolution | Confirm that the alert has stopped firing in Azure Monitor and CNC portal. | Resolution check |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| **Simulating High CPU Workload** | 1. Deploy a test CPU stress pod: `kubectl run cpu-stress --image=progrium/stress --restart=Never -- --cpu 2`<br>2. Verify container CPU exceeds 80% and alert fires within latency window.<br>3. Delete stress pod: `kubectl delete pod cpu-stress` |
| **Simulating Pod Auto-Recovery** | 1. Apply updated HPA threshold to scale out pods when CPU hits 75%.<br>2. Verify automated replica creation mitigates CPU breach. |

## Overview

*{details}*

## Alert Properties

|  |  |
| --- | --- |
| **Severity:** | * [x] Critical * [ ] Error * [ ] Warning * [ ] Info |
| **Signal Type:** | * [x] Log * [ ] Metric |

## Remediation Overview

## Investigation Steps

- Access Packages:
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- Diagnostic Execution:
  1. Connect to AKS cluster context:
     ```bash
     az aks get-credentials --resource-group "<resourceGroup>" --name "<aksClusterName>"
     ```
  2. Inspect high CPU pods:
     ```bash
     kubectl top pods -n "<namespace>" --sort-by=cpu
     ```
  3. Inspect pod lifecycle and events:
     ```bash
     kubectl describe pod "<podName>" -n "<namespace>"
     ```

## RCA & Mitigation

| **Scenario** | **Application Impact** | **Alert Latency (min)** | **Related alerts** | **Response Plan** |
| --- | --- | --- | --- | --- |
| **Application Traffic Spike** | Degraded API response times; elevated p99 latency. | 3 mins | - Warning: High HTTP 5xx errors | - [Scale pod replicas or tune HPA thresholds] |
| **Runaway Process / Deadlock** | Single pod 100% CPU lock; restart loops. | 5 mins | - Critical: Pod CrashLoopBackOff | - [Rollout restart deployment and patch process] |
| **Node Pool CPU Exhaustion** | New pods stuck in Pending state. | 8 mins | - Critical: Pods Unschedulable | - [Scale AKS node pool count] |

## Example Story Submissions

- [User Story 123456](https://dev.azure.com/org/proj/_workitems/edit/123456): Critical - {name} ({cvrd})

## References

- [Azure Monitor Container Insights Documentation](https://learn.microsoft.com/en-us/azure/azure-monitor/containers/container-insights-overview)
- [Manage AKS Node Pools](https://learn.microsoft.com/en-us/azure/aks/use-multiple-node-pools)

## Alert Enhancement

- Enhanced result set mapping:

| **Field Name** | **Description** |
| --- | --- |
{col_table}

## Lessons learned

- Set proportional CPU requests and limits in pod specifications to prevent "noisy neighbor" container throttling.
- Implement Horizontal Pod Autoscalers (HPA) configured at 70% CPU threshold for smooth traffic bursting.
"""

        # =========================================================================
        # 2. APP SERVICE / WEB APP / SERVER FARM HIGH CPU
        # =========================================================================
        if any(k in lower_name or k in lower_res for k in ["app service", "webapp", "serverfarm", "asp"]):
            return f"""# {name}

# Alert Details

| **Alert** | {name} |
| --- | --- |
| **Description** | *{details}* |
| **Severity** | {sev} |
| **Source** | Metrics / App Service Logs |
| **Root Cause** | - **Case 1 : ** Traffic surge exceeding App Service Plan worker capacity<br>- **Case 2 : ** Thread pool starvation / synchronous blocking I/O<br>- **Case 3 : ** High Garbage Collection CPU overhead due to memory pressure<br>- **Case 4 : ** Misconfigured or disabled autoscale rules |
| **Product** | Azure App Service |

# Prerequisites

- **App Service Plan Name:** `<appServicePlanName>`
- **Resource Group:** `<resourceGroup>`
- **Azure CLI & Azure Portal Access** (Website Contributor role)

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Verify **App Service CPU utilization and queue length | 1. Navigate to Azure Portal -> App Service Plan -> Metrics (CPU Percentage, HttpQueueLength).<br>2. Check active instances in Azure CLI:<br>`az appservice plan show -g <resourceGroup> -n <planName> --query "{{sku:sku.name, capacity:sku.capacity}}"` | Identify capacity |
| **Scale Out / Scale Up App Service Plan** | Scale out workers immediately to absorb load:<br>`az appservice plan update -g <resourceGroup> -n <planName> --number-of-workers <newCount>` | Scale workers |
| **Case 1**: Unresponsive worker process | Restart the specific Web App instances:<br>`az webapp restart -g <resourceGroup> -n <appName>` | Restart app |
| **Case 2**: Inspect Profiler / Diagnostic Logs | Navigate to App Service -> Diagnose and solve problems -> Availability and Performance -> CPU Analysis. | Diagnostic analysis |
| **Health Check** | Verify CPU Percentage drops below 70% and HTTP 5xx errors cease. | Health check |
| **Confirm **Alert Resolution | Confirm alert stops firing in Azure Monitor. | Resolution check |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| **Simulating App Service Load** | Run synthetic HTTP load test to verify autoscale rule fires at 80% CPU. |

## Overview

*{details}*

## Alert Properties

|  |  |
| --- | --- |
| **Severity:** | * [x] Critical * [ ] Error * [ ] Warning * [ ] Info |
| **Signal Type:** | * [x] Log * [ ] Metric |

## Remediation Overview

## Investigation Steps

- Access Packages:
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- Diagnostic commands:
  ```powershell
  Get-AzAppServicePlan -ResourceGroupName "<resourceGroup>" -Name "<planName>"
  ```

## RCA & Mitigation

| **Scenario** | **Application Impact** | **Alert Latency (min)** | **Related alerts** | **Response Plan** |
| --- | --- | --- | --- | --- |
| **Traffic Surge** | Elevated HTTP 503 / 504 errors | 3 mins | - Warning: High HTTP Queue Length | - [Scale out App Service instances] |

## Example Story Submissions

- [User Story 123456](https://dev.azure.com/org/proj/_workitems/edit/123456): Critical - {name} ({cvrd})

## References

- [Azure App Service CPU Troubleshooting](https://learn.microsoft.com/en-us/azure/app-service/overview-diagnostics)

## Alert Enhancement

| **Field Name** | **Description** |
| --- | --- |
{col_table}

## Lessons learned

- Enable automatic scaling with minimum and maximum instance count thresholds.
"""

        # =========================================================================
        # 3. VPN / VIRTUAL NETWORK GATEWAY DISCONNECTED (DEFAULT/VPN)
        # =========================================================================
        return f"""# {name}

# Alert Details

| **Alert** | {name} |
| --- | --- |
| **Description** | *{details}* |
| **Severity** | {sev} |
| **Source** | Log |
| **Root Cause** | - **Case 1 : ** Deleted / Unprovisioned Connection - **Case 2 : ** Shared Key (PSK) or Policy Mismatch - **Case 3 : ** Azure Platform / Host Maintenance - **Case 4 : ** Customer On-Premises Device Unreachable |
| **Product** | Common |

# Prerequisites

- Access Packages:
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- Required Azure IAM Roles: Network Contributor / Reader on Target Resource Group.

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Check **the connection status | 1. Review the **Query Result** and check the **Error Details**.<br>2. Check if the root cause indicates transient glitches, configuration drift, or host events.<br>3. Verify connection state in Azure CLI:<br>`az network vpn-connection show --name "<ConnectionName>" --resource-group "<ResourceGroupName>" --query "{{connectionStatus:connectionStatus, provisioningState:provisioningState}}" -o tsv` | Ref : |
| **Check **the resource health | 1. Locate the resource group associated with `{resource}`.<br>2. Under **Help**, click on **Resource health**.<br>3. Ensure that the resource health is **Available**.<br>4. If Unavailable, inspect platform maintenance logs. | |
| **Case 1**: Deleted / Unprovisioned Connection | Recreate or restore the connection resource in Azure Portal -> Settings -> Connections -> Add, or via Azure CLI / Terraform. | |
| **Case 2**: Shared Key (PSK) / Policy Mismatch | Verify that the pre-shared key (PSK) and IPsec/IKE policies configured in Azure match the customer on-premises device settings. | |
| **Case 3**: Azure Host / Platform Maintenance | This is an Azure-initiated event. Monitor the health status every 5 minutes until maintenance completes and connection transitions back to Connected. | |
| **Case 4**: Customer On-Premises Device Unreachable | 1. Confirm Azure-side config is correct (public IP on Local Network Gateway matches on-prem).<br>2. Confirm UDP 500 (IKE) and UDP 4500 (NAT-T) are open inbound.<br>3. Pull `IKEDiagnosticLog` in Log Analytics.<br>4. Escalate to Customer On-Call Network POC. | |
| Please find the KUSTO queries for the respective Causes | [Kusto Analysis - KQL queries for investigating alert logs] | |
| Health Check | Repeat Step 1 & 2 to ensure connection status is **Connected** and provisioning state is **Succeeded**. | |
| **Confirm **that the alert has stopped firing in CNC / Monitoring | Confirm alert resolution in Azure Monitor / CNC. | |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| **Simulating Connection Disconnect / Delete** | 1. Via Azure Portal: Navigate to target gateway -> Settings -> Connections -> Delete.<br>2. Via PowerShell:<br>`Remove-AzVirtualNetworkGatewayConnection -ResourceGroupName "<ResourceGroup>" -VirtualNetworkGatewayName "<GatewayName>" -Name "<ConnectionName>"`<br>3. Via Azure CLI:<br>`az network vnet-gateway connection delete -g "<ResourceGroup>" -n "<GatewayName>" --connection-name "<ConnectionName>"` |
| **Simulating Shared Key (PSK) Mismatch** | 1. Navigate to target connection -> Settings -> Authentication Type.<br>2. Edit Shared Key (PSK) to simulate mismatch.<br>3. Verify alert triggers within expected latency window. |

## Overview

*{details}*

## Alert Properties

|  |  |
| --- | --- |
| **Severity:** | * [x] Critical * [ ] Error * [ ] Warning * [ ] Info |
| **Signal Type:** | * [x] Log * [ ] Metric |

## Remediation Overview

## Investigation Steps

- Access Packages:
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- Check the resource status:
  1. Navigate to the Azure portal.
  2. Locate the resource group associated with `{resource}`.
  3. Under resources, navigate to `{resource}`.
  4. Under Settings, verify connection state is **Connected** or **Available**.
  5. Run PowerShell command:
     ```powershell
     Get-AzResource -Name "{resource}" -ResourceGroupName "<ResourceGroupName>"
     ```
  6. If status is Unknown or Disconnected, execute response plans in **RCA & Mitigation**.

## RCA & Mitigation

| **Scenario** | **Application Impact** | **Alert Latency (min)** | **Related alerts** | **Response Plan** |
| --- | --- | --- | --- | --- |
| **Deleted / Missing Connection** | Users unable to access applications; risk of SLA breach. | 4 mins | - Critical: {name} | - [Adding a connection via Virtual network gateway] |
| **Shared Key (PSK) Mismatch** | Connection status drops to Unknown; tunnel blocked. | 6 mins | - Critical: {name} due to config change | - [Troubleshooting Virtual network gateway connections] |

## Example Story Submissions

- [User Story 123456](https://dev.azure.com/org/proj/_workitems/edit/123456): Critical - {name} ({cvrd})

## References

- [Troubleshoot Azure Resources](https://learn.microsoft.com/en-us/azure/)

## Alert Enhancement

- Enhanced result set mapping:

| **Field Name** | **Description** |
| --- | --- |
{col_table}

## Lessons learned

- In cases where a tunnel is disconnected due to configuration testing, Azure will make continuous attempts to re-establish connection once settings match.
- The Shared key (PSK) and traffic selectors must match symmetrically on both sides to establish connection.
"""

    def publish_irp(
        self,
        organization: str,
        project: str,
        pat: str | None,
        wiki_id: str,
        path: str,
        content: str,
        comment: str = "Add Incident Response Plan",
        update_inventory: bool = True,
        inventory_page_path: str = "/Alert-Inventory",
        alert_name: str | None = None,
        severity: str | None = "Sev-1",
        owning_team: str | None = "Cloud Operations",
    ) -> dict[str, Any]:
        """Publish an IRP page to the ADO Wiki and optionally append to the Alert Inventory page."""
        effective_pat = pat or self.settings.ado_pat
        if not effective_pat:
            raise ValueError("Azure DevOps Personal Access Token (PAT) with Wiki (Write) permission is required.")

        client = AzureDevOpsClient(organization, effective_pat)

        # 1. Create or update the IRP page
        clean_path = path.strip()
        if not clean_path.startswith("/"):
            clean_path = f"/{clean_path}"

        page_result = client.create_or_update_wiki_page(
            project=project,
            wiki_id=wiki_id,
            path=clean_path,
            content=content,
            comment=comment,
        )

        inventory_updated = False
        # 2. Optionally update Alert Inventory table
        if update_inventory and alert_name:
            try:
                inventory_updated = self._append_alert_inventory(
                    client=client,
                    project=project,
                    wiki_id=wiki_id,
                    inventory_path=inventory_page_path,
                    alert_name=alert_name,
                    irp_path=clean_path,
                    severity=severity or "Sev-1",
                    owning_team=owning_team or "Operations",
                )
            except Exception as e:
                logger.warning("Could not auto-update Alert Inventory table: %s", e)

        return {
            "success": True,
            "page_path": clean_path,
            "wiki_id": wiki_id,
            "inventory_updated": inventory_updated,
            "page_details": page_result,
        }

    def _append_alert_inventory(
        self,
        client: AzureDevOpsClient,
        project: str,
        wiki_id: str,
        inventory_path: str,
        alert_name: str,
        irp_path: str,
        severity: str,
        owning_team: str,
    ) -> bool:
        """Read Alert Inventory page, append row if not already present, and update."""
        existing_content = ""
        try:
            inv_page = client.get_wiki_page(project, wiki_id, inventory_path)
            existing_content = inv_page.get("content", "")
        except Exception:
            existing_content = ""

        row = f"| [{alert_name}]({irp_path}) | {severity} | Active | {owning_team} | [View IRP]({irp_path}) |"

        if not existing_content.strip():
            new_content = f"""# Production Alert Inventory

This page tracks all alerts deployed in Production and links to their active Incident Response Plans (IRP).

| Alert Name | Severity | Status | Owning Team | Runbook (IRP) |
| :--- | :--- | :--- | :--- | :--- |
{row}
"""
        else:
            if alert_name in existing_content:
                # Already present
                return True
            if "| Alert Name |" not in existing_content:
                new_content = existing_content.rstrip() + f"\n\n| Alert Name | Severity | Status | Owning Team | Runbook (IRP) |\n| :--- | :--- | :--- | :--- | :--- |\n{row}\n"
            else:
                new_content = existing_content.rstrip() + f"\n{row}\n"

        client.create_or_update_wiki_page(
            project=project,
            wiki_id=wiki_id,
            path=inventory_path,
            content=new_content,
            comment=f"Register alert '{alert_name}' in Alert Inventory",
        )
        return True

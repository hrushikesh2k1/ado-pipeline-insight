from __future__ import annotations

import logging
import re
from typing import Any

from core.ado_client import AzureDevOpsClient
from core.openai_client import PipelineRecommendationClient
from app.core.config import get_settings
from app.services.irp_format import (
    IRP_SYSTEM_PROMPT,
    MAX_EXAMPLE_CHARS,
    build_user_prompt,
    extract_skeleton,
    normalize_irp_markdown,
)

logger = logging.getLogger(__name__)


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

        uploaded = bool(user_prompt_data["irp_example"] or user_prompt_data["irp_template"])
        not_read = " Your uploaded example and template were not read." if uploaded else ""
        built_in = " Built-in plans exist for AKS/container, App Service and VPN alerts; any other alert gets the VPN plan."
        notes: list[str] = []

        if client:
            try:
                example_skeleton, example_cut = extract_skeleton(user_prompt_data["irp_example"], MAX_EXAMPLE_CHARS)
                response = client.client.chat.completions.create(
                    model=client.deployment,
                    messages=[
                        {"role": "system", "content": IRP_SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(user_prompt_data, example_skeleton, user_prompt_data["irp_template"])},
                    ],
                    temperature=0.2,
                )
                markdown, problems = normalize_irp_markdown(response.choices[0].message.content, sanitized_alert)
                if markdown:
                    if example_cut:
                        notes.append(f"Your IRP example is longer than {MAX_EXAMPLE_CHARS:,} characters, so only the first {MAX_EXAMPLE_CHARS:,} were used.")
                    return self._result(sanitized_alert, severity, effective_resource, markdown, suggested_path, "ai", notes + problems)
                reason = "The AI returned no text"
            except Exception as e:
                logger.warning("Azure OpenAI IRP generation error, using the built-in IRP: %s", e)
                reason = f"The AI request failed ({type(e).__name__}; the server log has the details)"
            notes.append(f"{reason}, so the built-in IRP for this alert type was used.{not_read}{built_in}")
        else:
            notes.append("Azure OpenAI is not configured on this server (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT, plus az login or AZURE_OPENAI_API_KEY), "
                         f"so the built-in IRP for this alert type was used.{not_read}{built_in}")

        fallback, _problems = normalize_irp_markdown(self._build_deterministic_irp(user_prompt_data), sanitized_alert)
        return self._result(sanitized_alert, severity, effective_resource, fallback, suggested_path, "built-in", notes)

    @staticmethod
    def _result(alert_name: str, severity: str, resource: str, markdown: str, path: str, generated_by: str, notes: list[str]) -> dict[str, Any]:
        return {
            "alert_name": alert_name,
            "severity": severity,
            "target_resource": resource,
            "markdown_content": markdown,
            "suggested_wiki_path": path,
            "generated_by": generated_by,
            "notice": " ".join(notes) or None,
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
- **Access Packages:**
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- **Required Azure IAM Roles:** Azure Kubernetes Service Cluster User Role / Contributor.

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Verify **high CPU container(s) and identify affected pods | 1. In Azure Cloud Shell or local CLI with kubectl, run:<br><pre><code>kubectl top pods -n <namespace> --sort-by=cpu</code></pre><br>2. In **Log Analytics**, run:<br><pre><code>Perf<br>\\| where ObjectName == "K8SContainer" and CounterName == "cpuUsageNanoCores"<br>\\| summarize AvgCPU = avg(CounterValue) / 1e9 by InstanceName, bin(TimeGenerated, 5m)<br>\\| order by AvgCPU desc</code></pre> | Identify top offending pods |
| **Check **node resource utilization and health | 1. In CLI, run:<br><pre><code>kubectl top nodes<br>kubectl describe node <nodeName></code></pre><br>2. Check for `MemoryPressure`, `DiskPressure`, or scheduling constraints. | Verify node capacity |
| **Case 1**: Application Workload Spike / Heavy Traffic | 1. **Inform to the management for approval**.<br>2. Scale out deployment replicas to distribute load:<br><pre><code>kubectl scale deployment <deploymentName> --replicas=<newCount> -n <namespace></code></pre><br>3. Verify Horizontal Pod Autoscaler (HPA) triggers scaling:<br><pre><code>kubectl get hpa -n <namespace></code></pre> | If traffic spike persists, proceed with Step-4 |
| **Case 2**: Insufficient CPU Limits in Pod Specification | 1. **Inform to the management for approval**.<br>2. Inspect pod resource configuration:<br><pre><code>kubectl get deployment <deploymentName> -n <namespace> -o yaml</code></pre><br>3. Update `resources.limits.cpu` and `resources.requests.cpu` in manifest and reapply. | Adjust resource limits upon approval |
| **Case 3**: Runaway Container Process / Thread Lock | 1. Inspect container logs for stack traces or infinite loops:<br><pre><code>kubectl logs <podName> -n <namespace> --tail=200</code></pre><br>2. **Inform to the management for approval**.<br>3. Perform a rollout restart of the deployment:<br><pre><code>kubectl rollout restart deployment/<deploymentName> -n <namespace></code></pre> | Requires management approval for rollout restart |
| **Case 4**: Node Pool Exhaustion / Cluster Scaling | 1. **Inform to the management for approval**.<br>2. Scale node pool if autoscaler is constrained:<br><pre><code>az aks nodepool scale -g <resourceGroup> --cluster-name <clusterName> -n <nodePoolName> --node-count <count></code></pre> | Requires management approval |
| Step 7: Check Logs in Log Analytics | In **Log Analytics**, run:<br><pre><code>ContainerLog<br>\\| where TimeGenerated > ago(30m)<br>\\| where LogEntry contains "error" or LogEntry contains "exception"<br>\\| project TimeGenerated, PodName, LogEntry<br>\\| order by TimeGenerated desc</code></pre><br>Cases:<br>1. High OOMKilled / CPU throttled errors > Check container resource limits<br>2. Application deadlock stack traces > Trigger thread dump and rollout restart | If Case-1, proceed with Step-4<br>If Case-2, Proceed with Step-5 |
| Health Check | 1. Monitor container CPU utilization until it stabilizes below 70%.<br>2. Verify all pods are in `Running` state:<br><pre><code>kubectl get pods -n <namespace></code></pre> | Confirm health |
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
| **Verify **App Service CPU utilization and queue length | 1. Navigate to Azure Portal -> App Service Plan -> Metrics (CPU Percentage, HttpQueueLength).<br>2. Check active instances in Azure CLI:<br><pre><code>az appservice plan show -g <resourceGroup> -n <planName> --query "{{sku:sku.name, capacity:sku.capacity}}"</code></pre> | Identify capacity |
| **Scale Out / Scale Up App Service Plan** | 1. **Inform to the management for approval**.<br>2. Scale out workers immediately to absorb load:<br><pre><code>az appservice plan update -g <resourceGroup> -n <planName> --number-of-workers <newCount></code></pre> | Requires management approval |
| **Case 1**: Unresponsive worker process | 1. **Inform to the management for approval**.<br>2. Restart the specific Web App instances:<br><pre><code>az webapp restart -g <resourceGroup> -n <appName></code></pre> | Requires management approval |
| **Case 2**: Inspect Profiler / Diagnostic Logs | In **Log Analytics**, run:<br><pre><code>AppServiceHTTPLogs<br>\\| where TimeGenerated > ago(30m)<br>\\| where ScStatus >= 500<br>\\| project TimeGenerated, CsMethod, CsUriStem, ScStatus, TimeTaken<br>\\| order by TimeTaken desc</code></pre> | Diagnostic analysis |
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
| **Root Cause** | - **Case 1 : ** Deleted / Unprovisioned Connection<br>- **Case 2 : ** Shared Key (PSK) or Policy Mismatch<br>- **Case 3 : ** Azure Platform / Host Maintenance<br>- **Case 4 : ** Customer On-Premises Device Unreachable |
| **Product** | Common |

# Prerequisites

- Access Packages:
  - Commercial: [Commercial Access Package](https://myaccess.microsoft.com/@hexsig.onmicrosoft.com#/access-packages)
  - Gov Cloud: [Gov Cloud Access Package](https://myaccess.microsoft.us/@HexSI.onmicrosoft.com#/access-packages)
- Required Azure IAM Roles: Network Contributor / Reader on Target Resource Group.

# Remediation Steps

| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| --- | --- | --- |
| **Check **the connection status | 1. Review the **Query Result** and check the **Error Details**.<br>2. Check if the root cause indicates transient glitches, configuration drift, or host events.<br>3. Verify connection state in Azure CLI:<br><pre><code>az network vpn-connection show --name "<ConnectionName>" --resource-group "<ResourceGroupName>" --query "{{connectionStatus:connectionStatus, provisioningState:provisioningState}}" -o tsv</code></pre> | Ref : |
| **Check **the resource health | 1. Locate the resource group associated with `{resource}`.<br>2. Under **Help**, click on **Resource health**.<br>3. Ensure that the resource health is **Available**.<br>4. If Unavailable, inspect platform maintenance logs. | |
| **Case 1**: Deleted / Unprovisioned Connection | 1. **Inform to the management for approval**.<br>2. Recreate or restore the connection resource in Azure Portal -> Settings -> Connections -> Add, or via Azure CLI / Terraform. | Requires management approval |
| **Case 2**: Shared Key (PSK) / Policy Mismatch | 1. **Inform to the management for approval**.<br>2. Verify that the pre-shared key (PSK) and IPsec/IKE policies configured in Azure match the customer on-premises device settings:<br><pre><code>az network vpn-connection shared-key show -g "<ResourceGroupName>" -n "<ConnectionName>"</code></pre> | Requires management approval |
| **Case 3**: Azure Host / Platform Maintenance | This is an Azure-initiated event. Monitor the health status every 5 minutes until maintenance completes and connection transitions back to Connected. | |
| **Case 4**: Customer On-Premises Device Unreachable | 1. Confirm Azure-side config is correct (public IP on Local Network Gateway matches on-prem).<br>2. Confirm UDP 500 (IKE) and UDP 4500 (NAT-T) are open inbound.<br>3. Pull `IKEDiagnosticLog` in Log Analytics.<br>4. Escalate to Customer On-Call Network POC. | |
| Step 7: Check Logs | In **Log Analytics**, run:<br><pre><code>AzureDiagnostics<br>\\| where ResourceType == "VIRTUALNETWORKGATEWAYS" and Resource =~ "<vpnGatewayName>" and Category == "RouteDiagnosticLog"<br>\\| where OperationName in ("BgpConnectedEvent", "BgpDisconnectedEvent")<br>\\| where Message contains "<bgpPeerIp>"<br>\\| project TimeGenerated, OperationName, Message<br>\\| order by TimeGenerated desc</code></pre><br>Cases:<br>1. Only BgpDisconnectEvent, No BgpConnectedEvent at all > The peer shows connecting if underlying IPsec/IKE negotiation is failing. Check IKEDiagnosticLog<br>2. Alternating BgpDisconnectEvent and BgpConnectedEvent repeating > This is timer/Prefix/config-change issue | If Case-1, proceed with Step-8<br>If Case-2, Proceed with Step-9 |
| Step 8: Reset VPN Gateway Connection | 1. **Inform to the management for approval**.<br>2. Reset gateway connection in CLI:<br><pre><code>az network vpn-connection reset -g "<ResourceGroupName>" -n "<ConnectionName>"</code></pre> | Requires management approval |
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

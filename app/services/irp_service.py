from __future__ import annotations

import logging
import re
from typing import Any

from core.ado_client import AzureDevOpsClient
from core.openai_client import PipelineRecommendationClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

IRP_SYSTEM_PROMPT = """You are a Principal Cloud Site Reliability Engineer (SRE) and Incident Commander specializing in Azure, Kubernetes, networking, and enterprise systems.
Your task is to generate a comprehensive, highly technical, actionable, and production-ready Incident Response Plan (IRP) for a production alert.

Formatting Guidelines:
- Return pure GitHub-flavored Markdown.
- Use explicit, actionable Azure CLI (`az ...`), PowerShell (`Get-Az...`, `Test-NetConnection`), and KQL (Azure Monitor / Log Analytics) queries.
- Do NOT invent fake URLs or placeholders like `<fill_this_in>` wherever standard Azure syntax applies.
- Include concrete diagnostic commands, precise recovery steps, safe rollback guidelines, and clear post-incident verification tests.

Standard IRP Structure:
# Incident Response Plan: [Alert Name]

> **Alert Summary**: [1-2 sentences on what this alert detects and immediate severity]
> **Severity**: [Sev-1 / Sev-2 / Sev-3] | **Target Resource**: [Resource Name / Type] | **Owning Team**: [Team Name] | **Environment**: [Environment]

---

## 1. Incident Overview & Impact
- **Trigger Logic**: [Exact metric threshold and duration]
- **User / Business Impact**: [User-facing symptoms, affected dependencies, SLA risk]
- **Likely Root Causes**: [Bulleted list of 3-5 standard failure modes]

## 2. Immediate Triage & Diagnostics (First 5 Minutes)
Checklist of immediate verification actions:
- [ ] **Step 1: Authenticity & Health Check**
```powershell
# PowerShell verification command
```
- [ ] **Step 2: Metrics & Active Error Logs Inspection**
```bash
# Azure CLI / KQL query
```

## 3. Detailed Troubleshooting Workflow
### Phase A: Connectivity, Gateway & Network Layer
[Specific diagnostic steps, CLI commands, and expected outputs]

### Phase B: Service, Compute & Dependencies Layer
[Specific logs inspection, state checks, and configuration validation]

## 4. Mitigation & Remediation Procedures
### Option 1: Fast Recovery / Reset (Preferred)
```powershell
# Precise reset / restart / reconnect commands
```
### Option 2: Failover & Secondary Route Activation
[Steps to redirect traffic or activate secondary backup paths]
### Option 3: Hard Recovery / Resource Recreation
[Emergency procedure if standard reset fails]

## 5. Post-Incident Validation & Health Checks
- [ ] Validation Check 1 (e.g., End-to-end ping, throughput, connection status)
- [ ] Validation Check 2 (e.g., Downstream application health check probes)
- [ ] Validation Check 3 (e.g., Azure Monitor Alert auto-resolves to Healthy)

## 6. Escalation Matrix & Contacts
| Tier | Role / Team | Contact Method | SLA / Response Time |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Primary On-Call Engineer | PagerDuty / On-Call Channel | 5 mins |
| **Tier 2** | Infrastructure / Network SME | Escalation Hotline / Teams | 15 mins |
| **Tier 3** | Cloud Provider Support (Azure) | Azure Portal Severity-A Ticket | 30 mins |

## 7. Preventive Measures & Follow-Up
- Post-incident review action items (monitoring threshold tuning, Bicep/Terraform updates, redundancy improvements).
"""


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
        target_resource: str,
        severity: str = "Sev-1",
        trigger_condition: str | None = None,
        owning_team: str | None = None,
        environment: str | None = "Production",
        existing_irp_context: str | None = None,
        additional_notes: str | None = None,
    ) -> dict[str, Any]:
        """Generate an Incident Response Plan using Azure OpenAI with fallback to structured SRE templates."""
        client = self._get_client()
        sanitized_alert = alert_name.strip()
        slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", sanitized_alert.replace(" ", "-")).strip("-")
        suggested_path = f"/Incident-Response-Plans/{slug}"

        user_prompt_data = {
            "alert_name": sanitized_alert,
            "target_resource": target_resource.strip(),
            "severity": severity,
            "trigger_condition": trigger_condition or "Metric threshold breached for > 5 minutes",
            "owning_team": owning_team or "Cloud Operations & SRE",
            "environment": environment or "Production",
            "additional_notes": additional_notes or "",
        }
        if existing_irp_context:
            user_prompt_data["reference_wiki_irp_template"] = existing_irp_context[:3000]

        if client:
            try:
                response = client.client.chat.completions.create(
                    model=client.deployment,
                    messages=[
                        {"role": "system", "content": IRP_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Generate a complete Incident Response Plan for the following alert:\n"
                                f"Alert Name: {user_prompt_data['alert_name']}\n"
                                f"Target Resource: {user_prompt_data['target_resource']}\n"
                                f"Severity: {user_prompt_data['severity']}\n"
                                f"Trigger Condition: {user_prompt_data['trigger_condition']}\n"
                                f"Owning Team: {user_prompt_data['owning_team']}\n"
                                f"Environment: {user_prompt_data['environment']}\n"
                                f"Notes: {user_prompt_data['additional_notes']}\n"
                            ),
                        },
                    ],
                    temperature=0.2,
                )
                markdown_text = response.choices[0].message.content or ""
                if markdown_text.strip():
                    return {
                        "alert_name": sanitized_alert,
                        "severity": severity,
                        "target_resource": target_resource,
                        "markdown_content": markdown_text.strip(),
                        "suggested_wiki_path": suggested_path,
                    }
            except Exception as e:
                logger.warning("Azure OpenAI IRP generation error, using deterministic fallback: %s", e)

        # High-quality deterministic fallback tailored to common patterns
        fallback_content = self._build_deterministic_irp(user_prompt_data)
        return {
            "alert_name": sanitized_alert,
            "severity": severity,
            "target_resource": target_resource,
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

        return f"""# Incident Response Plan: {name}

> **Alert Summary**: {name} has triggered for `{resource}` in {env}. Immediate triage is required to avoid service downtime.
> **Severity**: {sev} | **Target Resource**: {resource} | **Owning Team**: {team} | **Environment**: {env}

---

## 1. Incident Overview & Impact
- **Trigger Logic**: `{trigger}`
- **User / Business Impact**: Disruptions or latency in user workflows relying on `{resource}`. Risk of SLA breaches.
- **Likely Root Causes**:
  - Transient network latency or network route peering outage.
  - Resource saturation (CPU/Memory/IOPS exhaustion or connection limits).
  - Upstream certificate expiration, IPsec re-key failure, or firewall policy changes.
  - Infrastructure maintenance or hardware node failover in Azure datacenter.

## 2. Immediate Triage & Diagnostics (First 5 Minutes)
Checklist of immediate verification actions:
- [ ] **Step 1: Check Resource & Alert Status**
```powershell
# Verify current status in Azure
az resource show --name "{resource}" --resource-type "Microsoft.Network/virtualNetworkGateways" --output table
```
- [ ] **Step 2: Inspect Live Diagnostic Logs**
```kql
// Query Log Analytics for recent disconnect / error events
AzureDiagnostics
| where Resource == "{resource}"
| where TimeGenerated >= ago(30m)
| where Level in ("Error", "Critical", "Warning")
| project TimeGenerated, OperationName, Message, Level
| order by TimeGenerated desc
```

## 3. Detailed Troubleshooting Workflow
### Phase A: Connectivity & Health Validation
1. Verify network path reachability and DNS resolution.
2. Confirm that dependent services and security group rules allow traffic on required ports.
```bash
# Network reachability test
nc -zv -w 5 <target-endpoint> 443
```

### Phase B: Service Logs & Gateway Health
1. Check resource health blade in Azure Portal (`Resource Health` -> `Health History`).
2. Verify CPU, Memory, and Active Connection metrics in Azure Monitor.

## 4. Mitigation & Remediation Procedures
### Option 1: Fast Recovery / Connection Reset (Preferred)
```powershell
# Reset Azure connection / gateway instance
az network vnet-gateway reset --name "{resource}" --resource-group "rg-{env.lower()}"
```
### Option 2: Traffic Rerouting & Secondary Path Activation
1. If secondary redundant link is provisioned, increase BGP route weight or update route table to direct traffic to standby gateway.
2. Verify failover route propagation across all Virtual Networks.

### Option 3: Hard Service Restart / Failover
1. Escalate to Cloud Infrastructure SME if connection does not recover after reset.
2. Initiate failover to paired Azure region if disaster recovery criteria are met.

## 5. Post-Incident Validation & Health Checks
- [ ] Continuous ping / synthetic probe passes with 0% packet loss for 10 minutes.
- [ ] Downstream dependent applications confirm successful connectivity.
- [ ] Azure Monitor Alert status transitions back to **Resolved / Healthy**.

## 6. Escalation Matrix & Contacts
| Tier | Role / Team | Contact Method | SLA / Response Time |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Primary On-Call Engineer | PagerDuty / Teams (`#ops-incidents`) | 5 mins |
| **Tier 2** | {team} SME | Phone / Escalation Rota | 15 mins |
| **Tier 3** | Microsoft Premier Azure Support | Azure Portal Severity-A Case | 30 mins |

## 7. Preventive Measures & Follow-Up
- Audit alarm thresholds to eliminate transient false positives.
- Ensure automated health probes and dual-redundant paths are active.
- Schedule Post-Mortem review within 48 hours.
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

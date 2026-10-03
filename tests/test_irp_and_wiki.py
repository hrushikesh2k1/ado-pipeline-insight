from unittest.mock import MagicMock, patch
import pytest
from app.services.irp_service import IrpService
from core.ado_client import AzureDevOpsClient


def test_irp_service_heuristic_generation():
    service = IrpService(openai_client=None)
    
    res = service.generate_irp(
        alert_name="VPN Tunnel Disconnected",
        cvrd="CVRD-NET-8821",
        alert_output_columns="TimeGenerated, ResourceGroup, GatewayName, ConnectionState",
        arm_template_context='{"type": "Microsoft.Network/virtualNetworkGateways"}',
        alert_details="Site-to-site IPsec tunnel dropped.",
        target_resource="vnet-gateway-prod-east",
        severity="Sev-1",
        trigger_condition="Tunnel status != 1 for 2 minutes",
        owning_team="Network Engineering",
        environment="Production",
        irp_template="# IRP Template\n## 1. Overview\n## 2. Triage",
        irp_example="# Example IRP\n## 1. Overview\n- Checklist",
    )
    
    assert res["suggested_wiki_path"] == "/Incident-Response-Plans/VPN-Tunnel-Disconnected"
    assert "VPN Tunnel Disconnected" in res["markdown_content"]
    assert "Sev-1" in res["markdown_content"]
    assert "vnet-gateway-prod-east" in res["markdown_content"]
    assert "az network vnet-gateway reset" in res["markdown_content"]
    assert res["alert_name"] == "VPN Tunnel Disconnected"


def test_irp_service_publish_flow():
    mock_client = MagicMock(spec=AzureDevOpsClient)
    mock_client.create_or_update_wiki_page.return_value = {
        "id": 101,
        "path": "/Incident-Response-Plans/VPN-Tunnel-Disconnected",
        "remoteUrl": "https://dev.azure.com/org/proj/_wiki/wikis/proj.wiki?pagePath=/Incident-Response-Plans/VPN-Tunnel-Disconnected"
    }
    mock_client.get_wiki_page.return_value = {"content": "# Production Alert Inventory\n\n| Alert Name | Severity | Status | Owning Team | Runbook (IRP) |\n| :--- | :--- | :--- | :--- | :--- |\n"}
    
    service = IrpService(openai_client=None)
    
    with patch("app.services.irp_service.AzureDevOpsClient", return_value=mock_client):
        res = service.publish_irp(
            organization="my-org",
            project="my-proj",
            pat="dummy-pat",
            wiki_id="my-proj.wiki",
            path="/Incident-Response-Plans/VPN-Tunnel-Disconnected",
            content="# VPN Tunnel Disconnected IRP\nContent...",
            comment="Add IRP",
            update_inventory=True,
            alert_name="VPN Tunnel Disconnected",
            severity="Sev-1",
            owning_team="Network Engineering",
        )
        
        assert res["success"] is True
        assert res["page_path"] == "/Incident-Response-Plans/VPN-Tunnel-Disconnected"
        assert res["inventory_updated"] is True
        assert mock_client.create_or_update_wiki_page.call_count == 2

import json

import pytest
from fastapi.testclient import TestClient

import app.services.llm_util as llm_util
from app.api import routes  # noqa: F401  (imported so the app module is loaded before it is patched)
from app.main import create_app
from app.services.irp_service import IrpService
from irp_support import CASES, EXAMPLE, FIXTURES, FakeIrpModel, good_case_row

ARM = (FIXTURES / "vpn_log_alert.arm.json").read_text(encoding="utf-8")
KQL = 'AzureDiagnostics | where Category == "IKEDiagnosticLog" | summarize count() by Resource'


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(llm_util.time, "sleep", lambda _s: None)


def generate(model, **kw):
    kw.setdefault("alert_name", "VPN - Tunnel disconnected")
    return IrpService(openai_client=model).generate_irp(**kw)


class TestGroundedGeneration:
    def test_an_arm_template_gives_the_case_by_case_irp_with_its_scorecard_and_commands(self):
        model = FakeIrpModel()
        result = generate(model, arm_template_context=ARM, irp_example=EXAMPLE)
        assert result["method"] == "case-by-case" and result["generated_by"] == "ai" and result["notice"] is None
        assert [c["name"] for c in result["cases"]] == [c["name"] for c in CASES]
        assert result["scorecard"]["status"] == "warn" and result["commands"] and result["facts"]["alert"]["type"] == "log"
        assert "| Case 1: IPsec Phase 2 tunnel dropped |" in result["markdown_content"]
        assert len(model.calls_of("cases")) == 1 and len(model.calls_of("frame")) == 1 and len(model.calls_of("case")) == 3

    def test_the_severity_comes_from_the_template_not_the_form(self):
        result = generate(FakeIrpModel(), arm_template_context=ARM, severity="Sev4 (Verbose)")
        assert result["severity"] == "Sev1 (Error)" and "| **Severity** | Error |" in result["markdown_content"]

    def test_a_query_alone_is_enough_and_the_form_s_severity_is_kept(self):
        model = FakeIrpModel()
        result = generate(model, alert_kql=KQL, severity="Sev2 (Warning)")
        assert result["method"] == "case-by-case" and result["severity"] == "Sev2 (Warning)" and result["facts"]["alert"] is None
        assert "| **Severity** | Warning |" in result["markdown_content"]
        assert "<alert_query>\nAzureDiagnostics | where Category == \"IKEDiagnosticLog\"" in model.calls_of("cases")[0][1]

    def test_the_query_the_user_gave_wins_over_the_template_and_they_are_told(self):
        result = generate(FakeIrpModel(), arm_template_context=ARM, alert_kql=KQL)
        assert any("differs from the query in the ARM template" in w for w in result["facts"]["warnings"])

    def test_cases_the_owner_edited_are_the_ones_written(self):
        model = FakeIrpModel()
        result = generate(model, arm_template_context=ARM, cases=[{"name": "Gateway rebooted", "signal": "restart in the log"}])
        assert not model.calls_of("cases") and [c["name"] for c in result["cases"]] == ["Gateway rebooted"]
        assert "| Case 1: Gateway rebooted |" in result["markdown_content"]

    def test_a_too_long_example_is_cut_and_the_page_is_told(self):
        long_example = EXAMPLE.replace("| Check the connection status |", "| " + "x" * 70_000 + " |")
        result = generate(FakeIrpModel(), arm_template_context=ARM, irp_example=long_example)
        assert result["method"] == "case-by-case" and "Your IRP example is longer than 60,000 characters" in result["notice"]

    def test_the_single_pass_writer_does_not_get_the_arm_text_twice(self):
        result = generate(FakeIrpModel(), arm_template_context="{ not json", alert_kql=None)
        assert result["method"] == "single-pass" and result["facts"]["warnings"][0].startswith("The ARM template is not valid JSON")


class TestFallbacks:
    def test_with_nothing_to_ground_on_the_single_pass_writer_is_used_as_before(self):
        model = FakeIrpModel()
        result = generate(model)
        assert result["method"] == "single-pass" and result["facts"] is None and result["scorecard"] is None and result["commands"] is None
        assert not model.calls_of("cases") and "| **Severity** | Critical |" in result["markdown_content"]

    def test_a_template_with_no_alert_in_it_falls_back_and_says_why(self):
        resource = json.dumps({"type": "Microsoft.Network/virtualNetworkGateways", "name": "gw"})
        result = generate(FakeIrpModel(), arm_template_context=resource)
        assert result["method"] == "single-pass" and "No log alert" in result["facts"]["warnings"][0]

    def test_if_the_case_by_case_writer_fails_the_single_pass_writer_takes_over_and_the_page_is_told(self):
        model = FakeIrpModel(case_row=lambda name, attempt: RuntimeError("model down"))
        result = generate(model, arm_template_context=ARM)
        assert result["method"] == "single-pass" and "The case-by-case writer failed" in result["notice"] and "so the single-pass writer was used" in result["notice"]
        assert "| Check status |" in result["markdown_content"]

    def test_if_everything_fails_the_built_in_plan_is_used(self):
        class Dead(FakeIrpModel):
            def _create(self, *a, **k):
                raise RuntimeError("down")

        result = generate(Dead(), arm_template_context=ARM)
        assert result["method"] == "built-in" and result["generated_by"] == "built-in" and "The AI request failed" in result["notice"]
        assert result["facts"]["alert"]["name"] == "VPN - Tunnel disconnected - Production"  # what was read is still shown

    def test_without_a_model_the_built_in_plan_is_used_and_the_template_is_still_read(self):
        result = IrpService(openai_client=None, settings=type("S", (), {"azure_openai_endpoint": "", "azure_openai_deployment": ""})()).generate_irp(
            alert_name="VPN - Tunnel disconnected", arm_template_context=ARM)
        assert result["method"] == "built-in" and "Azure OpenAI is not configured" in result["notice"] and result["severity"] == "Sev1 (Error)"


class TestAnalyze:
    def service(self, model):
        return IrpService(openai_client=model)

    def test_the_facts_and_the_proposed_cases(self):
        model = FakeIrpModel()
        result = self.service(model).analyze_alert(alert_name="VPN - Tunnel disconnected", arm_template_context=ARM)
        assert [c["name"] for c in result["cases"]] == [c["name"] for c in CASES] and result["notice"] is None
        assert result["severity"] == "Sev1 (Error)" and result["facts"]["alert"]["type"] == "log"
        assert "resolved_resource_json" not in result["facts"]  # the resolved ARM text is for the writer only
        assert len(model.calls) == 1

    def test_nothing_to_analyse(self):
        result = self.service(FakeIrpModel()).analyze_alert(alert_name="x")
        assert result["cases"] == [] and "Add the alert's ARM template" in result["notice"] and result["facts"]["has_definition"] is False

    def test_without_a_model_the_facts_are_still_read(self):
        service = IrpService(openai_client=None, settings=type("S", (), {"azure_openai_endpoint": "", "azure_openai_deployment": ""})())
        result = service.analyze_alert(alert_name="x", alert_kql=KQL)
        assert result["cases"] == [] and "not configured" in result["notice"] and result["facts"]["kql"]["tables"] == ["AzureDiagnostics"]

    def test_when_the_model_cannot_propose_cases_the_facts_are_still_returned(self):
        result = self.service(FakeIrpModel(cases=[{"name": ""}])).analyze_alert(alert_name="x", arm_template_context=ARM)
        assert result["cases"] == [] and "could not propose root causes" in result["notice"] and result["facts"]["alert"]


class TestRoutes:
    @pytest.fixture
    def client(self, monkeypatch):
        self.model = FakeIrpModel()
        monkeypatch.setattr(IrpService, "_get_client", lambda self_: self.model)
        return TestClient(create_app(), raise_server_exceptions=False)

    def test_generate_returns_the_new_fields(self, client):
        response = client.post("/api/v1/irp/generate", json={"alert_name": "VPN - Tunnel disconnected", "arm_template_context": ARM, "alert_kql": KQL, "irp_example": EXAMPLE})
        data = response.json()
        assert response.status_code == 200 and data["method"] == "case-by-case"
        assert data["scorecard"]["checks"] and data["commands"][0]["status"] == "unverified" and data["cases"][0]["name"] == CASES[0]["name"]
        assert data["facts"]["kql"]["source"] == "input"

    def test_the_owner_s_cases_go_through_the_request(self, client):
        body = {"alert_name": "a", "arm_template_context": ARM, "cases": [{"name": "Only cause", "signal": "s"}]}
        data = client.post("/api/v1/irp/generate", json=body).json()
        assert [c["name"] for c in data["cases"]] == ["Only cause"]

    def test_analyze(self, client):
        data = client.post("/api/v1/irp/analyze", json={"alert_name": "VPN - Tunnel disconnected", "arm_template_context": ARM}).json()
        assert data["severity"] == "Sev1 (Error)" and len(data["cases"]) == 3 and data["facts"]["alert"]["scopes"]

    @pytest.mark.parametrize("body", [
        {"alert_name": ""}, {"alert_name": "a", "cases": [{"name": ""}]}, {"alert_name": "a", "cases": [{"name": "c"}] * 9},
        {"alert_name": "a", "alert_kql": "x" * 100_001},
    ])
    def test_bad_requests_are_refused(self, client, body):
        assert client.post("/api/v1/irp/generate", json=body).status_code == 422

    def test_a_large_request_gets_through_on_the_irp_routes_only(self, client):
        big = {"alert_name": "a", "irp_example": "# Alert Details\n" + "x" * 100_000, "irp_template": "y" * 60_000}
        assert len(json.dumps(big)) > 160_000
        assert client.post("/api/v1/irp/generate", json=big).status_code == 200
        assert client.post("/api/v1/irp/analyze", json={"alert_name": "a", "irp_template": "y" * 100_000}).status_code == 200
        assert client.post("/api/v1/irp/publish", json={"organization": "o", "project": "p", "wiki_id": "w", "path": "/p", "content": "c" * 100_000}).status_code == 413

    def test_a_huge_request_is_still_refused(self, client):
        assert client.post("/api/v1/irp/generate", json={"alert_name": "a", "irp_example": "x" * 700_000}).status_code == 413

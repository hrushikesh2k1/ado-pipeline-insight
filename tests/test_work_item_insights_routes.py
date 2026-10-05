import base64
import time

import pytest
from fastapi.testclient import TestClient

import app.services.work_item_classifier as classifier
from app.api import routes
from app.main import create_app
from app.services.work_item_insights import WorkItemInsightsService
from wi_support import FakeAdo, FakeAI, raw_item

_REAL_SLEEP = time.sleep
SCOPE = "organization=org&project=Proj&tag=monitoring"
BASE = "/api/v1/insights/work-items"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(classifier.time, "sleep", lambda _s: None)
    ado = FakeAdo([
        raw_item(1, title="VPN tunnel drops", state="Active"),
        raw_item(2, title="Login fails", state="Closed", closed="2026-09-20T09:00:00Z"),
        raw_item(3, type="Task", title="Create new alert for pods", state="Done", closed="2026-09-21T09:00:00Z"),
    ])
    monkeypatch.setattr(routes, "wi_insights", WorkItemInsightsService(ado_factory=lambda org, pat: ado, ai_factory=lambda: FakeAI()))
    return TestClient(create_app(), raise_server_exceptions=False)


def b64(text: str | bytes) -> str:
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


def wait_until_done(client, tries=100):
    for _ in range(tries):
        status = client.get(f"{BASE}/status?{SCOPE}").json()
        if status["status"] != "running":
            return status
        _REAL_SLEEP(0.05)
    raise AssertionError("the refresh did not finish")


class TestReading:
    def test_a_scope_that_was_never_refreshed(self, client):
        data = client.get(f"{BASE}?{SCOPE}").json()
        assert data["has_data"] is False and data["items"] == [] and data["scope"]["tag"] == "monitoring"
        assert client.get(f"{BASE}/status?{SCOPE}").json()["status"] == "idle"

    @pytest.mark.parametrize("query", ["organization=bad%20org!&project=Proj", "organization=org&project=a..b"])
    def test_an_invalid_organization_or_project_is_refused(self, client, query):
        assert client.get(f"{BASE}?{query}").status_code == 422
        assert client.get(f"{BASE}/status?{query}").status_code == 422


class TestRefresh:
    def test_refresh_runs_in_the_background_and_the_page_can_then_read_the_result(self, client):
        started = client.post(f"{BASE}/refresh", json={"organization": "org", "project": "Proj", "tag": "monitoring", "pat": "token-123"})
        assert started.status_code == 200 and started.json()["status"] in ("running", "done")
        assert wait_until_done(client)["status"] == "done"
        data = client.get(f"{BASE}?{SCOPE}").json()
        assert data["has_data"] and {i["id"]: i["area"] for i in data["items"]}[1] == "VPN issues"
        assert data["bug_types"] == ["Bug"]

    def test_the_token_can_come_in_the_header_like_the_other_pages(self, client):
        started = client.post(f"{BASE}/refresh", json={"organization": "org", "project": "Proj"}, headers={"X-ADO-PAT": "token-123"})
        assert started.status_code == 200

    def test_without_any_token_the_refresh_is_refused(self, client):
        response = client.post(f"{BASE}/refresh", json={"organization": "org", "project": "Proj"})
        assert response.status_code in (401, 403)

    @pytest.mark.parametrize("body", [{"months": 0}, {"months": 99}, {"organization": "bad org!"}])
    def test_a_bad_request_is_refused(self, client, body):
        payload = {"organization": "org", "project": "Proj", "pat": "token-123", **body}
        assert client.post(f"{BASE}/refresh", json=payload).status_code == 422

    def test_the_token_is_never_returned(self, client):
        client.post(f"{BASE}/refresh", json={"organization": "org", "project": "Proj", "tag": "monitoring", "pat": "token-123"})
        wait_until_done(client)
        assert "token-123" not in client.get(f"{BASE}?{SCOPE}").text
        assert "token-123" not in client.get(f"{BASE}/status?{SCOPE}").text


class TestInventory:
    def upload(self, client, name="alerts.csv", content=b"Alert,Service\nVPN down,VPN\nPods restart,AKS\n", **extra):
        return client.post(f"{BASE}/inventory", json={"organization": "org", "project": "Proj", "tag": "monitoring",
                                                      "filename": name, "content_base64": b64(content), **extra})

    def test_upload_read_and_remove(self, client):
        response = self.upload(client)
        assert response.status_code == 200
        summary = response.json()
        assert summary["count"] == 2 and summary["name_column"] == "Alert" and summary["category_column"] == "Service"
        assert client.get(f"{BASE}?{SCOPE}").json()["inventory"]["count"] == 2
        assert client.delete(f"{BASE}/inventory?{SCOPE}").json() == {"status": "removed"}
        assert client.get(f"{BASE}?{SCOPE}").json()["inventory"] is None

    def test_the_columns_can_be_chosen_on_a_second_upload(self, client):
        data = b"Alert,Title,Team\nA,Real name,SRE\n"
        assert self.upload(client, content=data).json()["name_column"] == "Alert"
        again = self.upload(client, content=data, name_column="Title", category_column="Team").json()
        assert again["name_column"] == "Title" and again["sample"] == ["Real name"]

    def test_what_is_wrong_with_the_file_is_said_plainly(self, client):
        bad_type = self.upload(client, name="alerts.pdf")
        assert bad_type.status_code == 422 and "Upload a .xlsx" in bad_type.json()["detail"]
        corrupt = self.upload(client, name="alerts.xlsx", content=b"not a spreadsheet")
        assert corrupt.status_code == 422 and "could not be read" in corrupt.json()["detail"]
        empty = self.upload(client, content=b"Alert\n")
        assert empty.status_code == 422 and "at least one alert" in empty.json()["detail"]

    def test_text_that_is_not_base64_is_refused(self, client):
        response = client.post(f"{BASE}/inventory", json={"organization": "org", "project": "Proj", "filename": "a.csv", "content_base64": "***not base64***"})
        assert response.status_code == 422

    def test_a_real_sized_file_gets_through_the_request_size_guard(self, client):
        rows = b"".join(f"alert-{n:06d}-{'x' * 80},Service\n".encode() for n in range(40_000))
        content = b"Alert,Category\n" + rows
        assert 3_500_000 < len(content) < 5_000_000
        response = self.upload(client, content=content)
        assert response.status_code == 200 and response.json()["count"] == 40_000

    def test_a_file_over_5_mb_is_refused_with_a_clear_message(self, client):
        response = self.upload(client, content=b"Alert\n" + b"a" * 5_100_000)
        assert response.status_code == 422 and "larger than 5 MB" in response.json()["detail"]

    def test_a_body_larger_than_the_upload_limit_is_refused_before_it_is_read(self, client):
        response = client.post(f"{BASE}/inventory", json={"organization": "org", "project": "Proj", "filename": "a.csv", "content_base64": "A" * 7_300_000})
        assert response.status_code == 413

    def test_only_the_upload_route_gets_the_larger_limit(self, client):
        big = {"organization": "org", "project": "Proj", "pat": "token-123", "tag": "x" * 70_000}
        assert client.post(f"{BASE}/refresh", json=big).status_code == 413  # still the default 64 KB


class TestSignInGate:
    """With sign-in on (the default in production) none of the insight endpoints answer anonymously."""

    @pytest.fixture
    def locked(self, monkeypatch):
        import app.core.config as cfg
        from app.core import session_auth
        from app.core.session_auth import CredentialStore, Credentials

        class Fixed(CredentialStore):
            def __init__(self):
                super().__init__(settings=cfg.Settings(require_login=True))

            def get(self):
                return Credentials("Admin", "pw-for-this-test", "unit-test-session-secret")

        monkeypatch.setenv("REQUIRE_LOGIN", "true")
        cfg.get_settings.cache_clear()
        monkeypatch.setattr(session_auth, "credential_store", Fixed())
        session_auth.login_throttle.reset()
        monkeypatch.setattr(routes, "wi_insights", WorkItemInsightsService(ado_factory=lambda o, p: FakeAdo([]), ai_factory=lambda: FakeAI()))
        yield TestClient(create_app(), raise_server_exceptions=False, base_url="https://testserver")
        cfg.get_settings.cache_clear()
        session_auth.login_throttle.reset()

    def test_every_endpoint_needs_a_session(self, locked):
        assert locked.get(f"{BASE}?{SCOPE}").status_code == 401
        assert locked.get(f"{BASE}/status?{SCOPE}").status_code == 401
        assert locked.post(f"{BASE}/refresh", json={"organization": "org", "project": "Proj", "pat": "token-123"}).status_code == 401
        assert locked.post(f"{BASE}/inventory", json={"organization": "org", "project": "Proj", "filename": "a.csv", "content_base64": b64("Alert,Service")}).status_code == 401
        assert locked.delete(f"{BASE}/inventory?{SCOPE}").status_code == 401

    def test_after_signing_in_they_answer(self, locked):
        assert locked.post("/api/v1/auth/login", json={"username": "Admin", "password": "pw-for-this-test"}).status_code == 200
        assert locked.get(f"{BASE}?{SCOPE}").status_code == 200

"""The pull request review over HTTP: what a caller gets, and what each failure looks like."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import create_app
from app.services import pr_review
from pr_support import FakeAdo, FakePrModel, finding

PAYLOAD = {"organization": "myorg", "project": "myproj", "repository_id": "repo-1", "pull_request_id": 101, "pat": "fake-pat"}
URL = "/api/v1/ado/pullrequests/review"


@pytest.fixture
def api(monkeypatch):
    state = {"ado": FakeAdo(), "model": FakePrModel(), "ado_args": []}

    def make_ado(organization, pat):
        state["ado_args"].append((organization, pat))
        return state["ado"]

    monkeypatch.setattr(routes, "AzureDevOpsClient", make_ado)
    monkeypatch.setattr(pr_review, "get_model_client", lambda: state["model"])
    monkeypatch.setattr("app.services.llm_util.time.sleep", lambda seconds: None)
    return TestClient(create_app(), raise_server_exceptions=False), state


def http_error(code):
    return requests.HTTPError(response=SimpleNamespace(status_code=code))


def test_a_review_comes_back_with_everything_the_page_shows(api):
    client, state = api
    state["model"] = FakePrModel({"scripts/report.py": [finding(17, "Division by zero")]})
    response = client.post(URL, json=PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["pull_request_id"] == 101 and data["posted_to_ado"] is False and data["method"] == "diff-per-file"
    assert data["verdict"] == "APPROVED_WITH_SUGGESTIONS" and data["source_commit"] == "a" * 40
    comment = data["comments"][0]
    assert (comment["file_path"], comment["line_number"], comment["verified"], comment["language"]) == ("scripts/report.py", 17, True, "Python")
    assert {f["status"] for f in data["files"]} == {"reviewed", "skipped"}
    assert any(c["item"] == "Changelog updated" and c["status"] == "ok" for c in data["checklist"])
    assert "cannot judge how the result looks" in data["scope_note"] and set(data["scorecard"]) == {"correctness", "security", "performance", "maintainability", "test_coverage"}


def test_the_callers_pat_is_used_for_azure_devops(api):
    client, state = api
    client.post(URL, json=PAYLOAD)
    assert state["ado_args"] == [("myorg", "fake-pat")]


def test_without_the_ai_the_request_fails_and_nothing_is_made_up(api, monkeypatch):
    client, _ = api

    def unavailable():
        raise pr_review.AiUnavailable("Azure OpenAI is not configured, so the AI review is unavailable. Nothing was reviewed.")

    monkeypatch.setattr(pr_review, "get_model_client", unavailable)
    response = client.post(URL, json=PAYLOAD)
    assert response.status_code == 503
    assert "Nothing was reviewed" in response.json()["detail"] and "comments" not in response.json()


def test_when_the_ai_fails_for_every_file_the_request_fails(api):
    client, state = api
    state["model"] = FakePrModel({p: RuntimeError("x") for p in ("scripts/report.py", "scripts/totals.ps1", "tests/test_report.py")})
    response = client.post(URL, json=PAYLOAD)
    assert response.status_code == 502 and "Nothing was reviewed" in response.json()["detail"]


def test_a_pull_request_with_nothing_to_review_is_a_422(api):
    client, state = api
    state["ado"] = FakeAdo(changes=[])
    assert client.post(URL, json=PAYLOAD).status_code == 422


@pytest.mark.parametrize("code,expected,text", [(401, 401, "PAT"), (403, 401, "PAT"), (203, 401, "PAT"), (404, 404, "not found"), (500, 502, "HTTP 500")])
def test_azure_devops_errors_are_explained(api, code, expected, text):
    client, state = api
    state["ado"] = FakeAdo()
    state["ado"].get_pull_request = lambda *args: (_ for _ in ()).throw(http_error(code))
    response = client.post(URL, json=PAYLOAD)
    assert response.status_code == expected and text in response.json()["detail"]


def test_an_unexpected_error_does_not_leak_its_details(api):
    client, state = api
    state["ado"] = FakeAdo(fail={"get_pull_request"})
    response = client.post(URL, json=PAYLOAD)
    assert response.status_code == 502 and "get_pull_request failed" not in response.text and "Nothing was reviewed" in response.json()["detail"]


def test_without_a_pat_the_server_one_is_used_only_for_allowed_organizations(api, monkeypatch):
    client, state = api
    looked_up = []
    monkeypatch.setattr(routes, "get_ado_pat", lambda org: looked_up.append(org) or "server-pat")
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(allowed_ado_org_list=["myorg"]))
    without_pat = {k: v for k, v in PAYLOAD.items() if k != "pat"}

    assert client.post(URL, json=without_pat).status_code == 200
    assert state["ado_args"][-1] == ("myorg", "server-pat")

    other = client.post(URL, json={**without_pat, "organization": "someone-else"})
    assert other.status_code == 403 and looked_up == ["myorg"]  # the server's token was never looked up for the other organization


def test_without_any_pat_the_caller_is_asked_for_one(api, monkeypatch):
    client, _ = api

    def no_pat(org):
        raise RuntimeError("no key vault")

    monkeypatch.setattr(routes, "get_ado_pat", no_pat)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(allowed_ado_org_list=[]))
    response = client.post(URL, json={k: v for k, v in PAYLOAD.items() if k != "pat"})
    assert response.status_code == 401 and "personal access token" in response.json()["detail"].lower()


def test_the_request_is_validated(api):
    client, _ = api
    assert client.post(URL, json={**PAYLOAD, "pull_request_id": 0}).status_code == 422
    assert client.post(URL, json={**PAYLOAD, "organization": ""}).status_code == 422


def test_the_pull_request_list_carries_the_commit_a_review_was_made_at(api, monkeypatch):
    client, _ = api

    class Lister:
        def __init__(self, organization, pat):
            pass

        def list_pull_requests(self, project, repository_id, status="active"):
            return [{"pullRequestId": 5, "title": "T", "status": "active", "createdBy": {"displayName": "A"}, "creationDate": "2026-10-01T00:00:00Z",
                     "sourceRefName": "refs/heads/f", "targetRefName": "refs/heads/main", "repository": {"id": "r", "name": "repo"},
                     "lastMergeSourceCommit": {"commitId": "abc123"}},
                    {"pullRequestId": 6, "title": "U", "status": "active", "createdBy": {}, "creationDate": "", "sourceRefName": "refs/heads/g", "targetRefName": "refs/heads/main", "repository": {}}]

    monkeypatch.setattr(routes, "AzureDevOpsClient", Lister)
    response = client.get("/api/v1/ado/pullrequests?organization=myorg&project=myproj&repository_id=r&pat=x")
    assert response.status_code == 200
    assert [p["last_source_commit"] for p in response.json()] == ["abc123", None]

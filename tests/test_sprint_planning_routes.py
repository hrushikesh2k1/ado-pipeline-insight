"""Sprint planning over HTTP: what the page gets, and what each failure looks like."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
import app.api.sprint_planning_routes as planning_routes
from app.main import create_app
from sprint_support import FakeBoard, http_error, comment, story
from test_sprint_planning import AVA, BEN, CARA, scenario_items

SETUP = "/api/v1/ado/sprint-planning/setup"
PLAN = "/api/v1/ado/sprint-planning/plan"
BODY = {"organization": "myorg", "project": "Demo", "team": "Alpha", "pat": "fake-pat", "from_iteration_id": "s2", "to_iteration_id": "s3",
        "people": [AVA, BEN, CARA], "per_person": 3, "active_days": 10}
QUERY = {"organization": "myorg", "project": "Demo", "team": "Alpha", "pat": "fake-pat"}


@pytest.fixture
def api(monkeypatch):
    state = {"board": FakeBoard(scenario_items(), comments={10: [comment("newest")], 12: [comment("blocked on the vendor")]}), "made": []}

    def make(organization, pat):
        state["made"].append((organization, pat))
        return state["board"]

    monkeypatch.setattr(planning_routes, "AzureDevOpsClient", make)
    return TestClient(create_app(), raise_server_exceptions=False), state


class TestSetup:
    def test_the_page_gets_everything_it_needs_to_start(self, api):
        client, _ = api
        response = client.get(SETUP, params=QUERY)
        assert response.status_code == 200
        data = response.json()
        assert [s["id"] for s in data["sprints"]] == ["s1", "s2", "s3", "s4"] and (data["default_from_id"], data["default_to_id"]) == ("s2", "s3")
        assert [m["name"] for m in data["members"]][:2] == ["Ava Stone", "Ben Ortiz"] and "Demo\\Alpha\\Backend" in data["areas"]
        assert (data["per_person"], data["active_days"], data["default_types"]) == (6, 10, ["User Story"])

    def test_the_callers_token_is_used(self, api):
        client, state = api
        client.get(SETUP, params=QUERY)
        assert state["made"] == [("myorg", "fake-pat")]

    def test_the_token_may_come_in_the_header(self, api):
        client, state = api
        client.get(SETUP, params={k: v for k, v in QUERY.items() if k != "pat"}, headers={"X-ADO-PAT": "header-pat"})
        assert state["made"] == [("myorg", "header-pat")]

    def test_without_a_token_the_request_is_refused(self, api, monkeypatch):
        client, state = api

        def none(organization):
            raise RuntimeError("no server token")

        monkeypatch.setattr(routes, "get_ado_pat", none)
        response = client.get(SETUP, params={k: v for k, v in QUERY.items() if k != "pat"})
        assert response.status_code == 401 and "personal access token" in response.json()["detail"] and state["made"] == []

    @pytest.mark.parametrize("missing", ["organization", "project", "team"])
    def test_a_missing_name_is_a_422(self, api, missing):
        client, _ = api
        assert client.get(SETUP, params={k: v for k, v in QUERY.items() if k != missing}).status_code == 422

    @pytest.mark.parametrize("field,value,word", [("organization", "bad org!", "organization"), ("project", "a/b", "project"), ("project", "x..y", "project")])
    def test_a_name_that_cannot_be_one_is_a_422_that_says_which(self, api, field, value, word):
        client, state = api
        response = client.get(SETUP, params={**QUERY, field: value})
        assert response.status_code == 422 and word in response.json()["detail"] and state["made"] == []
        assert client.post(PLAN, json={**BODY, field: value}).status_code == 422


class TestPlan:
    @pytest.mark.parametrize("capacity_mode", ["points", "stories"])
    @pytest.mark.parametrize("capacity", [
        {"capacity_points": 0},
        {"working_days": 0},
        {"working_days": 10, "pto_days": 10},
        {"working_days": 10, "pto_days": 12},
        {"working_days": 0, "capacity_points": 20},
        {},
        {"capacity_points": None, "working_days": None},
    ])
    def test_capacity_survives_request_validation_and_zero_availability_is_enforced(self, api, capacity_mode, capacity):
        client, state = api
        state["board"] = FakeBoard([
            story(101, who="ava", iteration="Demo\\Sprint 2", points=3),
            story(102, who="ava", iteration="Demo\\Sprint 3", points=2),
            story(103, points=1),
        ])
        response = client.post(PLAN, json={**BODY, "people": [{**AVA, **capacity}], "capacity_mode": capacity_mode})
        assert response.status_code == 200
        member = response.json()["people"][0]
        assert [item["id"] for item in member["carried"]] == [101]
        assert [item["id"] for item in member["already_planned"]] == [102]
        no_days = capacity.get("working_days") == 0 or capacity.get("pto_days", 0) >= 10
        no_budget = no_days or (capacity_mode == "points" and capacity.get("capacity_points") == 0)
        assert [item["id"] for item in member["new"]] == ([] if no_budget else [103])
        if no_budget:
            assert member["points_capacity"] == 0
            assert member["points_over_by"] == 5
            assert member["points_open"] == 0
            assert any("Capacity exceeded" in warning for warning in member["warnings"])

    def test_the_plan_comes_back_with_what_the_page_shows(self, api):
        client, _ = api
        response = client.post(PLAN, json=BODY)
        assert response.status_code == 200
        plan = response.json()
        assert plan["posted_to_ado"] is False and plan["per_person"] == 3 and plan["active_days"] == 10 and plan["generated_at"].endswith("Z")
        assert (plan["from_sprint"]["name"], plan["to_sprint"]["name"]) == ("Sprint 2", "Sprint 3")
        assert [p["name"] for p in plan["people"]] == ["Ava Stone", "Ben Ortiz", "Cara Lin"] and [p["total"] for p in plan["people"]] == [3, 3, 3]
        ben = plan["people"][1]
        assert [s["id"] for s in ben["carried"]] == [12] and [s["id"] for s in ben["new"]] == [30, 31] and ben["new"][0]["matched_area"] == "Demo\\Alpha\\Backend"
        assert plan["summary"]["flagged"] == 2 and plan["summary"]["blocked"] == 1 and plan["summary"]["long_active"] == 1

    def test_a_flagged_story_comes_with_its_flags_and_comments(self, api):
        client, _ = api
        slow, blocked = client.post(PLAN, json=BODY).json()["flagged"]
        assert slow["flags"][0]["code"] == "active_too_long" and slow["comments"] == [{"author": "Ava Stone", "date": "2026-10-01T09:00:00Z", "text": "newest"}]
        assert blocked["flags"][0]["reason"] == 'Blocked: tag "Blocked"' and blocked["url"] == "https://dev.azure.com/myorg/Demo/_workitems/edit/12"

    def test_the_team_name_is_trimmed_and_the_token_used(self, api):
        client, state = api
        assert client.post(PLAN, json={**BODY, "team": " Alpha "}).status_code == 200 and state["made"] == [("myorg", "fake-pat")]

    @pytest.mark.parametrize("over", [
        {"people": []}, {"per_person": 0}, {"per_person": 31}, {"active_days": 0}, {"active_days": 91}, {"from_iteration_id": ""}, {"team": ""}, {"organization": ""},
        {"people": [{"name": "", "areas": []}]}, {"people": [{"name": "Ava", "areas": ["x"] * 61}]}, {"people": [{"name": f"P{n}", "areas": []} for n in range(41)]},
        {"work_item_types": ["a"] * 9},
    ])
    def test_a_request_that_makes_no_sense_is_a_422_before_azure_devops_is_asked(self, api, over):
        client, state = api
        assert client.post(PLAN, json={**BODY, **over}).status_code == 422 and state["made"] == []

    def test_a_plan_that_cannot_be_made_says_why(self, api):
        client, _ = api
        response = client.post(PLAN, json={**BODY, "to_iteration_id": "s2"})
        assert response.status_code == 422 and "different sprint" in response.json()["detail"]
        assert client.post(PLAN, json={**BODY, "to_iteration_id": "nope"}).json()["detail"].startswith("Choose the sprint")

    @pytest.mark.parametrize("failure,status,words", [(401, 401, "authentication failed"), (403, 401, "authentication failed"), (203, 401, "authentication failed"),
                                                      (404, 404, "was not found"), (500, 502, "Azure DevOps returned HTTP 500")])
    def test_azure_devops_errors_are_explained(self, api, failure, status, words):
        client, state = api
        state["board"].list_team_iterations = lambda *args, **kwargs: (_ for _ in ()).throw(http_error(failure))
        response = client.post(PLAN, json=BODY)
        assert response.status_code == status and words in response.json()["detail"]
        assert client.get(SETUP, params=QUERY).status_code in (status, 200)  # the setup reads the sprints too; its failure is explained the same way

    def test_anything_else_is_a_502_that_does_not_leak_the_message(self, api):
        client, state = api
        state["board"].list_team_iterations = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret internal detail"))
        response = client.post(PLAN, json=BODY)
        assert response.status_code == 502 and "secret internal detail" not in response.text and "Nothing was changed in Azure DevOps" in response.json()["detail"]

    def test_the_routes_only_read(self, api):
        client, state = api
        client.post(PLAN, json=BODY)
        client.get(SETUP, params=QUERY)
        board = state["board"]
        assert not [name for name in dir(board) if name.startswith(("update_", "create_", "delete_", "patch_", "post_", "set_"))]

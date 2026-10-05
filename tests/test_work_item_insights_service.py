import json
import time
from types import SimpleNamespace

import pytest
import requests

import app.services.work_item_classifier as classifier
import app.services.work_item_insights as insights
from app.repositories import work_item_insights_repository as store
from app.services.work_item_insights import WorkItemInsightsService, describe_error, guess_bug_types
from wi_support import FakeAdo, FakeAI, http_error, raw_item, smart_responder

ORG, PROJECT, TAG = "org", "Proj", "monitoring"
_REAL_SLEEP = time.sleep  # the fixture below replaces time.sleep for everyone, including this file's own polling


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(classifier.time, "sleep", lambda _s: None)


def make_raws():
    return [
        raw_item(1, title="VPN tunnel drops", state="Active"),
        raw_item(2, title="Login fails for admins", state="Closed", closed="2026-08-10T09:00:00Z"),
        raw_item(3, type="Task", title="Create new alert for AKS pod restarts", state="Done", closed="2026-09-01T09:00:00Z"),
        raw_item(4, title="Printer is empty", state="New"),
        raw_item(5, title="Old closed work", state="Closed", closed="2020-01-01T00:00:00Z"),
    ]


def service(ado, ai):
    return WorkItemInsightsService(ado_factory=lambda org, pat: ado, ai_factory=lambda: ai)


def refresh(svc, regroup=False, tag=TAG, team=""):
    return svc.start_refresh(ORG, PROJECT, "pat", tag=tag, team=team, regroup=regroup, background=False)


def snap(svc, tag=TAG, team=""):
    return svc.snapshot(ORG, PROJECT, team, tag)


def areas_by_id(snapshot):
    return {i["id"]: i["area"] for i in snapshot["items"]}


class TestFirstRefresh:
    def test_items_are_grouped_saved_and_served(self):
        ai = FakeAI()
        svc = service(FakeAdo(make_raws()), ai)
        status = refresh(svc)
        assert status["status"] == "done" and status["error"] is None
        s = snap(svc)
        assert s["has_data"] and s["area_source"] == "ai" and s["refreshed_at"]
        assert [a["name"] for a in s["areas"]] == ["VPN issues", "Login and authentication", "AKS container restarts"]
        assert areas_by_id(s) == {1: "VPN issues", 2: "Login and authentication", 3: "AKS container restarts", 4: "Other"}
        assert len(ai.calls_of("discover")) == 1

    def test_the_scope_rules_decide_what_is_included(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        refresh(svc)
        assert sorted(areas_by_id(snap(svc))) == [1, 2, 3, 4]  # item 5 closed long before the window

    def test_the_page_gets_plain_fields_not_the_descriptions(self):
        svc = service(FakeAdo([raw_item(1, description="secret details")]), FakeAI())
        refresh(svc)
        item = snap(svc)["items"][0]
        assert set(item) == {"id", "type", "title", "state", "state_category", "assigned_to", "created", "closed", "sprint", "area_path", "area", "alert_work"}
        assert "secret details" not in json.dumps(snap(svc))

    def test_types_and_the_likely_bug_types(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        refresh(svc)
        s = snap(svc)
        assert s["types"] == [{"name": "Bug", "count": 3}, {"name": "Task", "count": 1}]
        assert s["bug_types"] == ["Bug"]

    def test_each_scope_is_kept_apart(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        refresh(svc, tag="monitoring")
        assert snap(svc, tag="platform")["has_data"] is False and snap(svc, tag="monitoring")["has_data"] is True
        assert snap(svc, tag="monitoring", team="Other team")["has_data"] is False


class TestOnlyWhatChangedGoesToTheModel:
    def test_an_unchanged_refresh_asks_the_model_nothing(self):
        ai = FakeAI()
        svc = service(FakeAdo(make_raws()), ai)
        refresh(svc)
        before = len(ai.calls)
        refresh(svc)
        assert len(ai.calls) == before

    def test_a_changed_or_new_item_is_the_only_one_assigned(self):
        ado, ai = FakeAdo(make_raws()), FakeAI()
        svc = service(ado, ai)
        refresh(svc)
        ai.calls.clear()
        ado.raws[4] = raw_item(4, title="VPN printer link is down", state="New", rev=2)
        ado.raws[6] = raw_item(6, title="Login page error", state="New")
        refresh(svc)
        assert ai.assigned_ids() == [4, 6] and not ai.calls_of("discover")
        assert areas_by_id(snap(svc))[4] == "VPN issues" and areas_by_id(snap(svc))[6] == "Login and authentication"

    def test_regroup_proposes_new_areas_and_regroups_everything(self):
        ai = FakeAI()
        svc = service(FakeAdo(make_raws()), ai)
        refresh(svc)
        ai.calls.clear()
        refresh(svc, regroup=True)
        assert len(ai.calls_of("discover")) == 1 and ai.assigned_ids() == [1, 2, 3, 4]

    def test_an_item_that_left_the_scope_is_dropped_from_the_saved_data(self):
        ado = FakeAdo(make_raws())
        svc = service(ado, FakeAI())
        refresh(svc)
        del ado.raws[4]
        refresh(svc)
        assert 4 not in areas_by_id(snap(svc))


class TestAlertWork:
    def inventory(self, svc):
        svc.save_inventory(ORG, PROJECT, "", TAG, "alerts.csv", b"Alert\nVPN tunnel down\nPod restarts\n")

    def test_with_an_inventory_the_same_pass_flags_alert_building_items(self):
        svc = service(FakeAdo(make_raws()), ai := FakeAI())
        self.inventory(svc)
        refresh(svc)
        flags = {i["id"]: i["alert_work"] for i in snap(svc)["items"]}
        assert flags == {1: False, 2: False, 3: True, 4: False}
        assert not ai.calls_of("alert_only")

    def test_without_an_inventory_the_question_is_never_asked(self):
        svc = service(FakeAdo(make_raws()), ai := FakeAI())
        refresh(svc)
        assert all(i["alert_work"] is None for i in snap(svc)["items"])
        assert not any('"alert_work"' in s for s, _u in ai.calls)

    def test_an_inventory_uploaded_later_only_asks_the_alert_question(self):
        svc = service(FakeAdo(make_raws()), ai := FakeAI())
        refresh(svc)
        ai.calls.clear()
        self.inventory(svc)
        refresh(svc)
        assert not ai.calls_of("assign") and not ai.calls_of("discover") and len(ai.calls_of("alert_only")) == 1
        assert {i["id"]: i["alert_work"] for i in snap(svc)["items"]}[3] is True

    def test_the_inventory_summary_is_served_and_can_be_removed(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        summary = svc.save_inventory(ORG, PROJECT, "", TAG, "alerts.csv", b"Alert,Service\nA,VPN\nB,AKS\nC,AKS\n")
        assert summary["count"] == 3 and snap(svc)["inventory"]["categories"][0] == {"name": "AKS", "count": 2}
        assert "alerts" not in snap(svc)["inventory"]
        svc.clear_inventory(ORG, PROJECT, "", TAG)
        assert snap(svc)["inventory"] is None

    def test_an_unreadable_inventory_changes_nothing(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        svc.save_inventory(ORG, PROJECT, "", TAG, "a.csv", b"Alert\nA\n")
        with pytest.raises(ValueError):
            svc.save_inventory(ORG, PROJECT, "", TAG, "a.pdf", b"x")
        assert snap(svc)["inventory"]["count"] == 1


class TestWhenTheAiIsNotAvailable:
    def test_without_azure_openai_items_are_grouped_by_area_path_and_the_page_is_told(self):
        raws = [raw_item(1, area="Proj\\Monitoring\\VPN"), raw_item(2, area="Proj\\Monitoring\\Login"), raw_item(3, area="Proj")]
        svc = service(FakeAdo(raws), None)
        refresh(svc)
        s = snap(svc)
        assert s["area_source"] == "area_path" and areas_by_id(s) == {1: "VPN", 2: "Login", 3: "(project root)"}
        assert "Azure OpenAI is not configured" in s["notes"][0] and "Area Path" in s["notes"][0]

    def test_when_openai_arrives_later_everything_is_regrouped_by_the_model(self):
        ado = FakeAdo(make_raws())
        refresh(service(ado, None))
        svc = service(ado, FakeAI())
        refresh(svc)
        s = snap(svc)
        assert s["area_source"] == "ai" and areas_by_id(s)[1] == "VPN issues" and s["notes"] == []

    def test_if_the_model_cannot_propose_areas_the_first_refresh_still_works(self):
        def broken(system, user):
            if system.startswith("You are given the titles"):
                return "I cannot do that"
            return smart_responder(system, user)

        svc = service(FakeAdo(make_raws()), FakeAI(broken))
        refresh(svc)
        s = snap(svc)
        assert s["area_source"] == "area_path" and "could not propose areas" in s["notes"][0]

    def test_a_model_that_goes_away_keeps_what_was_grouped_and_marks_new_items(self):
        ado = FakeAdo(make_raws())
        refresh(service(ado, FakeAI()))
        ado.raws[6] = raw_item(6, title="Brand new item")
        svc = service(ado, None)
        refresh(svc)
        s = snap(svc)
        assert s["area_source"] == "ai" and areas_by_id(s)[1] == "VPN issues" and areas_by_id(s)[6] == "Not grouped"
        assert "left as they were grouped" in s["notes"][0]

    def test_items_the_model_would_not_answer_for_are_marked_not_guessed(self):
        def stingy(system, user):
            if system.startswith("You place Azure DevOps work items"):
                items = json.loads(user)["items"]
                return json.dumps({"items": [{"id": i["id"], "area": "VPN issues"} for i in items if i["id"] != 4]})
            return smart_responder(system, user)

        ai = FakeAI(stingy)
        svc = service(FakeAdo(make_raws()), ai)
        refresh(svc)
        s = snap(svc)
        assert areas_by_id(s)[4] == "Not grouped" and any("1 work item(s) could not be processed" in n for n in s["notes"])
        ai.calls.clear()
        refresh(svc)  # the next refresh asks again, and only for the item it missed
        assert set(ai.assigned_ids()) == {4}


class TestFailures:
    @pytest.mark.parametrize("error,expected", [
        (http_error(401), "did not accept the personal access token"),
        (http_error(203), "did not accept the personal access token"),
        (http_error(403), "Work Items: Read"),
        (http_error(404), "could not find this organization or project"),
        (http_error(500), "HTTP 500"),
        (ValueError("Team 'X' has no area paths"), "Team 'X' has no area paths"),
        (RuntimeError("boom"), "failed unexpectedly (RuntimeError)"),
    ])
    def test_the_message_says_what_to_fix(self, error, expected):
        assert expected in describe_error(error)

    def test_an_unexpected_error_does_not_show_its_internals_to_the_page(self):
        message = describe_error(RuntimeError("Unable to connect to sqlserver-prod.database.windows.net as svc-account"))
        assert "sqlserver-prod" not in message and "svc-account" not in message

    def test_a_rejected_token_ends_the_job_with_a_message_and_keeps_the_old_data(self):
        ado = FakeAdo(make_raws())
        svc = service(ado, FakeAI())
        refresh(svc)
        ado.wiql_error = lambda top: http_error(401)
        status = refresh(svc)
        assert status["status"] == "error" and "personal access token" in status["error"]
        assert len(snap(svc)["items"]) == 4

    def test_a_team_that_cannot_be_read_is_an_error_not_the_whole_project(self):
        status = refresh(service(FakeAdo(make_raws(), team_fields=http_error(404)), FakeAI()), team="Ghost")
        assert status["status"] == "error" and "area paths of team 'Ghost'" in status["error"]


class TestJobs:
    def test_a_refresh_that_is_already_running_is_not_started_twice(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        key = store.scope_key(ORG, PROJECT, "", TAG)
        insights._jobs[key] = {"status": "running", "phase": "grouping", "done": 3, "total": 10, "message": "busy"}
        status = svc.start_refresh(ORG, PROJECT, "pat", tag=TAG, background=False)
        assert status["message"] == "busy" and not snap(svc)["has_data"]

    def test_the_status_of_a_scope_never_refreshed_is_idle(self):
        assert WorkItemInsightsService.status("nothing")["status"] == "idle"

    def test_a_background_refresh_reports_progress_and_finishes(self):
        svc = service(FakeAdo(make_raws()), FakeAI())
        started = svc.start_refresh(ORG, PROJECT, "pat", tag=TAG)
        assert started["status"] in ("running", "done")
        key = store.scope_key(ORG, PROJECT, "", TAG)
        for _ in range(100):
            if svc.status(key)["status"] != "running":
                break
            _REAL_SLEEP(0.05)
        assert svc.status(key)["status"] == "done" and snap(svc)["has_data"]

    def test_progress_messages_are_readable(self):
        svc = service(FakeAdo([]), FakeAI())
        key = store.scope_key(ORG, PROJECT, "", TAG)
        insights._jobs[key] = {"status": "running"}
        report = svc._progress(key)
        report("reading", 400, 1200)
        assert insights._jobs[key]["message"] == "Reading work items from Azure DevOps (400 of 1200)"
        report("reading", 5000, 0)
        assert insights._jobs[key]["message"] == "Reading work items from Azure DevOps (5000 found)"
        report("grouping", 30, 90)
        assert insights._jobs[key]["message"] == "Grouping work items with AI (30 of 90)"


class TestSnapshotBasics:
    def test_a_scope_with_nothing_saved(self):
        s = snap(service(FakeAdo([]), FakeAI()))
        assert s["has_data"] is False and s["items"] == [] and s["areas"] == [] and s["inventory"] is None
        assert s["scope"] == {"organization": ORG, "project": PROJECT, "team": "", "tag": TAG, "months": 6}

    @pytest.mark.parametrize("configured", [True, False])
    def test_the_page_learns_whether_the_ai_is_configured(self, monkeypatch, configured):
        settings = SimpleNamespace(azure_openai_endpoint="https://x" if configured else "", azure_openai_deployment="d" if configured else "")
        monkeypatch.setattr(insights, "get_settings", lambda: settings)
        assert snap(service(FakeAdo([]), None))["ai_configured"] is configured

    def test_which_types_look_like_bugs(self):
        assert guess_bug_types(["Task", "Bug", "Defect", "Issue", "User Story"]) == ["Bug", "Defect"]
        assert guess_bug_types(["Task", "Issue"]) == []

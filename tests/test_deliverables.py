from datetime import datetime, timezone

import pytest
from app.services.deliverables import completion_record, available_hours, build_report, identity

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 1, tzinfo=timezone.utc)
STATES = {"task": {"closed"}, "user story": {"done"}}
SCOPES = [("cloud\\monitoring", True)]


def revision(rev, date, state="Active", **fields):
    return {"id": 42, "rev": rev, "fields": {
        "System.Id": 42, "System.Title": "August carryover", "System.WorkItemType": "Task",
        "System.ChangedDate": date, "System.State": state,
        "System.IterationPath": "Cloud\\August", "System.AreaPath": "Cloud\\Monitoring",
        "System.AssignedTo": {"id": "alice", "displayName": "Alice", "uniqueName": "alice@example.com"},
        **fields,
    }}


def record(history):
    return completion_record(history, STATES, START, END, SCOPES, "Cloud\\September")


def test_august_iteration_completed_in_september_and_attribution_frozen():
    history = [revision(1, "2026-08-15T09:00:00Z"),
               revision(2, "2026-09-30T23:59:59Z", "Closed", **{"Microsoft.VSTS.Scheduling.CompletedWork": 8}),
               revision(3, "2026-10-05T09:00:00Z", "Closed", **{
                   "System.AssignedTo": {"id": "bob", "displayName": "Bob"},
                   "System.IterationPath": "Cloud\\October", "Microsoft.VSTS.Scheduling.CompletedWork": 20,
                   "System.AreaPath": "Cloud\\Other"})]
    item = record(history)
    assert item["status"] == "delivered"
    assert item["cross_iteration"]
    assert item["owner"]["name"] == "Alice"
    assert item["recorded_hours"] == 8
    assert item["iteration_path"] == "Cloud\\August"
    assert completion_record(history, STATES, datetime(2026, 8, 1, tzinfo=timezone.utc), START, SCOPES, "Cloud\\August") is None


def test_end_exclusive_and_no_credit_for_preperiod_completion():
    assert record([revision(1, "2026-10-01T00:00:00Z", "Closed")]) is None
    assert record([revision(1, "2026-08-31T23:59:59Z", "Closed"), revision(2, "2026-09-03T09:00:00Z", "Closed")]) is None


def test_reopen_inside_sprint_excluded_but_reopen_after_end_only_flagged():
    closed = revision(1, "2026-09-15T09:00:00Z", "Closed")
    assert record([closed, revision(2, "2026-09-20T09:00:00Z")])["status"] == "reopened_in_period"
    item = record([closed, revision(2, "2026-10-02T09:00:00Z")])
    assert item["status"] == "delivered" and item["reopened_after_period"]


def test_recompletion_not_double_counted():
    history = [revision(1, "2026-08-20T09:00:00Z", "Closed"), revision(2, "2026-09-02T09:00:00Z"),
               revision(3, "2026-09-03T09:00:00Z", "Closed")]
    assert record(history)["status"] == "recompleted"
    history = [revision(1, "2026-09-01T09:00:00Z", "Closed"), revision(2, "2026-09-02T09:00:00Z"),
               revision(3, "2026-09-03T09:00:00Z", "Closed")]
    assert record(history)["status"] == "delivered"
    assert record(history)["completion_events_in_period"] == 2


def test_team_scope_at_completion_and_custom_state_category():
    assert record([revision(1, "2026-09-10T09:00:00Z", "Closed", **{"System.AreaPath": "Cloud\\Other"})]) is None
    assert record([revision(1, "2026-09-10T09:00:00Z", "Resolved")]) is None
    item = completion_record([revision(1, "2026-09-10T09:00:00Z", "Accepted")],
                             {"task": {"accepted"}}, START, END, SCOPES, "Cloud\\September")
    assert item["status"] == "delivered"


def test_missing_effort_distinct_from_zero_and_sprint_end_correction():
    assert record([revision(1, "2026-09-10T09:00:00Z", "Closed")])["recorded_hours"] is None
    assert record([revision(1, "2026-09-10T09:00:00Z", "Closed", **{"Microsoft.VSTS.Scheduling.CompletedWork": 0})])["recorded_hours"] == 0
    assert record([revision(1, "2026-09-10T09:00:00Z", "Closed"),
                   revision(2, "2026-09-11T09:00:00Z", "Closed", **{"Microsoft.VSTS.Scheduling.CompletedWork": 4})])["recorded_hours"] == 4


def test_capacity_excludes_weekends_and_overlapping_days_off_once():
    cap = {"activities": [{"capacityPerDay": 8}], "daysOff": [{"start": "2026-09-07T00:00:00Z", "end": "2026-09-08T00:00:00Z"}]}
    team_days = [{"start": "2026-09-08T00:00:00Z", "end": "2026-09-09T00:00:00Z"}]
    assert available_hours(cap, START, END, team_days) == (22 - 3) * 8
    assert available_hours({}, START, END, []) is None


class FakeAdo:
    organization = "org"
    def get_team_iteration(self, *args):
        return {"name": "September", "path": "Cloud\\September", "attributes": {"startDate": "2026-09-01T00:00:00Z", "finishDate": "2026-09-30T00:00:00Z"}}
    def get_team_field_values(self, *args):
        return {"values": [{"value": "Cloud\\Monitoring", "includeChildren": True}]}
    def list_work_item_types(self, *args):
        return [{"name": "Task"}, {"name": "User Story"}]
    def list_work_item_type_states(self, project, kind):
        return [{"name": "Closed" if kind == "Task" else "Done", "category": "Completed"}]
    def query_wiql(self, project, query, top):
        assert 'IterationPath' not in query and 'AreaPath' not in query
        return [42, 43, 44]
    def list_work_item_revisions(self, project, item_id):
        fields = {"Microsoft.VSTS.Scheduling.CompletedWork": 8 if item_id == 42 else 100}
        if item_id == 42:
            fields["System.Parent"] = 43
        if item_id == 44:
            fields["Microsoft.VSTS.Scheduling.CompletedWork"] = None
        rev = revision(1, "2026-09-15T09:00:00Z", "Done" if item_id == 43 else "Closed", **fields)
        rev["id"] = item_id
        if item_id == 43:
            rev["fields"]["System.WorkItemType"] = "User Story"
        return [rev]
    def list_team_members(self, *args):
        return [{"identity": {"id": "alice", "displayName": "Alice", "uniqueName": "alice@example.com"}},
                {"identity": {"id": "bob", "displayName": "Bob"}}]
    def get_iteration_capacity(self, *args):
        return {"teamMembers": [{"teamMember": {"id": "alice"}, "activities": [{"capacityPerDay": 8}], "daysOff": []}]}
    def get_team_days_off(self, *args):
        return {"daysOff": []}
    def get_team_settings(self, *args):
        return {"workingDays": ["monday", "tuesday", "wednesday", "thursday", "friday"]}


def test_full_report_separates_parent_and_child_effort_and_missing_addresses():
    report = build_report(FakeAdo(), "Cloud", "monitoring", "sept-id")
    assert report["delivered_count"] == 1
    assert report["completed_tasks"] == 2
    assert report["recorded_hours"] == 8  # Parent's 100 hours never added to tasks.
    assert report["missing_effort_count"] == 1
    assert report["recipients"] == ["alice@example.com"]
    assert report["missing_recipient_names"] == ["Bob"]
    assert report["people"][0]["available_hours"] == 176
    assert report["end_exclusive"] == "2026-10-01T00:00:00+00:00"


def test_fail_closed_when_team_scope_or_history_unavailable():
    ado = FakeAdo()
    ado.get_team_field_values = lambda *args: {}
    with pytest.raises(ValueError, match="area paths"):
        build_report(ado, "Cloud", "monitoring", "sept-id")
    with pytest.raises(ValueError, match="change date"):
        record([revision(1, "bad-date", "Closed")])


def test_membership_failure_preserves_report_but_disables_draft():
    ado = FakeAdo()
    def fail(*args):
        raise RuntimeError("unavailable")
    ado.list_team_members = fail
    report = build_report(ado, "Cloud", "monitoring", "sept-id")
    assert not report["recipients_verified"]
    assert report["recipients"] == []
    assert report["recorded_hours"] == 8


def test_email_validation_rejects_header_and_recipient_injection():
    assert identity({"uniqueName": "alice@example.com\r\nBcc:evil@example.com"})["email"] is None
    assert identity({"uniqueName": "alice@example.com;evil@example.com"})["email"] is None


def test_capacity_respects_custom_team_working_days():
    cap = {"activities": [{"capacityPerDay": 4}], "daysOff": []}
    assert available_hours(cap, START, END, [], {5, 6}) == 8 * 4


def test_deliverables_endpoint_uses_pat_header_and_returns_verified_report(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.main import create_app
    received = []
    def resolve(org, token):
        received.append((org, token))
        return "resolved-token"
    monkeypatch.setattr(routes, "_resolve_pat", resolve)
    monkeypatch.setattr(routes, "AzureDevOpsClient", lambda org, token: FakeAdo())
    response = TestClient(create_app()).get('/api/v1/ado/sprints/deliverables',
        params={"organization": "org", "project": "Cloud", "team": "monitoring", "iteration_id": "sept"},
        headers={"X-ADO-PAT": "test-pat"})
    assert response.status_code == 200
    assert received == [("org", "test-pat")]
    assert response.json()["recorded_hours"] == 8


def test_deliverables_endpoint_does_not_return_partial_history(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.main import create_app
    ado = FakeAdo()
    def fail(*args):
        raise RuntimeError("secret credential detail")
    ado.list_work_item_revisions = fail
    monkeypatch.setattr(routes, "_resolve_pat", lambda *args: "token")
    monkeypatch.setattr(routes, "AzureDevOpsClient", lambda *args: ado)
    response = TestClient(create_app()).get('/api/v1/ado/sprints/deliverables',
        params={"organization": "org", "project": "Cloud", "team": "monitoring", "iteration_id": "sept"})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "No partial report" in response.text


def test_revision_and_membership_pagination():
    from core.ado_client import AzureDevOpsClient
    class Response:
        def __init__(self, page):
            self.page = page
        def raise_for_status(self):
            pass
        def json(self):
            return {"value": self.page}
    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, params, timeout):
            self.calls.append(params)
            size = params["$top"]
            return Response([{"id": i} for i in range(size if params["$skip"] == 0 else 1)])
    session = Session()
    ado = AzureDevOpsClient("org", "token", session)
    assert len(ado.list_work_item_revisions("Cloud", 42)) == 201
    assert session.calls[1]["$skip"] == 200
    session.calls.clear()
    assert len(ado.list_team_members("Cloud", "monitoring")) == 101
    assert session.calls[1]["$skip"] == 100


def test_saved_snapshot_avoids_regeneration_and_failed_refresh_keeps_previous(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.main import create_app
    from app.services import deliverables
    from app.services.snapshot_store import SnapshotStore
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    monkeypatch.delenv('REPORT_STORAGE_ACCOUNT_URL',raising=False)
    monkeypatch.setattr(routes,'_resolve_pat',lambda *args:'token')
    monkeypatch.setattr(routes,'AzureDevOpsClient',lambda *args:FakeAdo())
    original = deliverables.build_report
    calls=[]
    def build(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(deliverables,'build_report',build)
    params={'organization':'org','project':'Cloud','team':'monitoring','iteration_id':'sept'}
    client=TestClient(create_app())
    first=client.get('/api/v1/ado/sprints/deliverables',params=params)
    assert first.status_code==200 and first.json()['snapshot_saved']
    second=client.get('/api/v1/ado/sprints/deliverables',params=params)
    assert second.json()['from_snapshot'] and len(calls)==1
    refreshed=client.get('/api/v1/ado/sprints/deliverables',params={**params,'regenerate':True})
    assert refreshed.status_code==200 and not refreshed.json()['from_snapshot'] and len(calls)==2
    previous=SnapshotStore().read('deliverables',['org','Cloud','monitoring','sept','v2'])
    def fail(*args):
        raise RuntimeError('history failed')
    monkeypatch.setattr(deliverables,'build_report',fail)
    assert client.get('/api/v1/ado/sprints/deliverables',params={**params,'regenerate':True}).status_code==503
    assert SnapshotStore().read('deliverables',['org','Cloud','monitoring','sept','v2'])==previous

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services import sprint_planning as planning
from app.services.sprint_capacity import normalize_capacity_members
from app.services.sprint_velocity import completed_points, exact_person, forecast_people, previous_completed_sprint
from sprint_support import FakeBoard, NOW, PROJECT, TEAM, story


class VelocityBoard(FakeBoard):
    def __init__(self):
        super().__init__([
            story(1, state="Active", who="ava", iteration="Demo\\Sprint 2", points=5),
            story(2, points=3), story(3, points=5), story(4, points=13),
            story(5, state="Active", who="ben", iteration="Demo\\Sprint 3", points=3),
        ])
        self.snapshot_queries = []
        self.snapshots = [
            story(100, state="Closed", who="ava", iteration="Demo\\Sprint 2", points=15),
            story(101, state="Closed", who="ben", iteration="Demo\\Sprint 2", points=10),
            story(102, state="Closed", who="cara", iteration="Demo\\Sprint 2", points=12),
            story(103, state="Removed", who="ava", iteration="Demo\\Sprint 2", points=20),
            story(104, state="Resolved", who="ava", iteration="Demo\\Sprint 2", points=20),
        ]

    def query_wiql(self, project, query, top=None):
        if " ASOF " in query:
            self.snapshot_queries.append(query)
            return [item["id"] for item in self.snapshots]
        return super().query_wiql(project, query, top=top)

    def get_work_items_batch(self, project, ids, fields=None, as_of=None):
        if as_of:
            assert as_of == "2026-10-02T23:59:59.999Z"
            return deepcopy(self.snapshots)
        return super().get_work_items_batch(project, ids, fields)

    def get_iteration_capacities(self, project, team, iteration):
        return [{"teamMember": {"displayName": "Ava Stone", "uniqueName": "ava@example.test"},
                 "activities": [{"name": "Development", "capacityPerDay": 8}], "daysOff": []}]


def member(name, unique, pto=0, daily=8):
    return {"name": name, "unique_name": unique, "days_off": pto, "capacity_per_day": daily}


def capacity():
    return {"target_iteration_id": "s3", "previous_iteration_id": "s2",
            "previous_members": [member("Ava Stone", "ava@example.test"), member("Ben Ortiz", "ben@example.test"), member("Cara Lin", "cara@example.test", 2)],
            "upcoming_members": [member("Ava Stone", "ava@example.test", 2), member("Ben Ortiz", "ben@example.test"), member("Cara Lin", "cara@example.test")]}


def crew():
    return [{"name": m["name"], "unique_name": m["unique_name"], "areas": ["*"]} for m in capacity()["upcoming_members"]]


def test_individual_formula_matches_all_three_agreed_examples():
    people, notes = forecast_people(VelocityBoard(), PROJECT, TEAM, "s3", crew(), capacity(), ["User Story"], NOW)
    assert [p["capacity_points"] for p in people] == [12, 10, 15]
    assert [p["total_capacity_hours"] for p in people] == [64, 80, 80]
    assert all(p["forecast_status"] == "ready" for p in people)
    assert any("one completed sprint" in note for note in notes)


def test_history_reads_owner_points_and_completed_state_at_sprint_end_not_today():
    board = VelocityBoard()
    totals = completed_points(board, PROJECT, TEAM, planning.list_sprints(board, PROJECT, TEAM)[1], ["User Story"])
    assert [row["points"] for row in totals] == [15, 10, 12]
    assert "ASOF '2026-10-02T23:59:59.999Z'" in board.snapshot_queries[0]
    assert "[System.IterationPath] IN ('Demo\\Sprint 2')" in board.snapshot_queries[0]


def test_baseline_uses_last_actually_finished_sprint_not_current_or_future():
    sprints = planning.list_sprints(VelocityBoard(), PROJECT, TEAM)
    assert previous_completed_sprint(sprints, sprints[3], NOW)["id"] == "s2"
    assert previous_completed_sprint(sprints, sprints[2], datetime(2026, 10, 2, 12, tzinfo=timezone.utc))["id"] == "s1"


@pytest.mark.parametrize("change", ["missing-upcoming", "missing-previous", "zero-previous", "missing-points", "history-failed", "states-failed", "unknown-state"])
def test_unavailable_baseline_never_falls_back_to_eight_points(change):
    board, data = VelocityBoard(), capacity()
    if change == "missing-upcoming":
        data["upcoming_members"] = []
    elif change == "missing-previous":
        data["previous_members"] = []
    elif change == "zero-previous":
        data["previous_members"][0]["days_off"] = 10
    elif change == "missing-points":
        board.snapshots[0]["fields"].pop("Microsoft.VSTS.Scheduling.StoryPoints")
    elif change == "states-failed":
        board.list_work_item_type_states = lambda *args: (_ for _ in ()).throw(PermissionError())
    elif change == "unknown-state":
        board.snapshots[0]["fields"]["System.State"] = "Unmapped historical state"
    else:
        board.query_wiql = lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError())
    people, _ = forecast_people(board, PROJECT, TEAM, "s3", crew()[:1], data, ["User Story"], NOW)
    assert people[0]["capacity_points"] is None
    assert people[0]["forecast_status"] == "unavailable"
    assert people[0]["forecast_note"]


def test_zero_upcoming_days_and_daily_capacity_produce_zero_budget():
    for field, value in (("days_off", 10), ("capacity_per_day", 0)):
        data = capacity()
        data["upcoming_members"][0][field] = value
        people, _ = forecast_people(VelocityBoard(), PROJECT, TEAM, "s3", crew()[:1], data, ["User Story"], NOW)
        assert people[0]["capacity_points"] == 0
        assert people[0]["total_capacity_hours"] == 0


def test_saved_capacity_tab_entries_still_work_if_ado_capacity_is_unreadable():
    board = VelocityBoard()
    board.get_iteration_capacities = lambda *args: (_ for _ in ()).throw(PermissionError())
    people, notes = forecast_people(board, PROJECT, TEAM, "s3", crew(), capacity(), ["User Story"], NOW)
    assert [p["capacity_points"] for p in people] == [12, 10, 15]
    assert any("could not be read" in note for note in notes)
    data = capacity()
    data["upcoming_members"] = []
    people, _ = forecast_people(board, PROJECT, TEAM, "s3", crew(), data, ["User Story"], NOW)
    assert all(p["forecast_status"] == "unavailable" for p in people)


def test_wrong_sprint_context_is_rejected():
    data = capacity()
    data["previous_iteration_id"] = "s1"
    with pytest.raises(planning.PlanningError, match="context changed"):
        forecast_people(VelocityBoard(), PROJECT, TEAM, "s3", crew(), data, ["User Story"], NOW)


def test_identity_matching_rejects_conflicting_emails_and_ambiguous_names():
    rows = [member("Same Name", "a@test"), member("Same Name", "b@test")]
    assert exact_person(rows, {"name": "Same Name", "unique_name": "other@test"}) is None
    assert exact_person(rows, {"name": "Same Name", "unique_name": ""}) is None
    assert exact_person(rows, {"name": "Renamed", "unique_name": "a@test"}) == rows[0]


def test_half_complete_carryover_reserves_half_points_and_new_work_never_exceeds_budget():
    board = VelocityBoard()
    result = planning.plan_sprint(board, organization="org", project=PROJECT, team=TEAM, to_iteration_id="s3", from_iteration_id="s2",
                                  people=crew(), capacity_mode="points", per_person=1, velocity_capacity=capacity(), now=NOW)
    ava = result["people"][0]
    assert ava["points_carried"] == 5
    assert ava["points_reserved"] == 2.5 + ava["points_new"] + ava["points_already_planned"]
    assert all(p["points_reserved"] <= p["points_capacity"] for p in result["people"])
    assert all(p["velocity_based"] for p in result["people"])
    assert any("50%" in warning for warning in ava["warnings"])
    assert result["summary"]["stories_planned"] > len(result["people"])  # per-person story reference is not an allocation cap


def test_unknown_commitment_points_pause_new_work_without_dropping_existing_story():
    board = VelocityBoard()
    board.items[1]["fields"].pop("Microsoft.VSTS.Scheduling.StoryPoints")
    result = planning.plan_sprint(board, organization="org", project=PROJECT, team=TEAM, to_iteration_id="s3", from_iteration_id="s2",
                                  people=crew()[:1], capacity_mode="points", velocity_capacity=capacity(), now=NOW)
    assert result["people"][0]["carried"][0]["id"] == 1
    assert result["people"][0]["new"] == []
    assert any("paused" in warning for warning in result["people"][0]["warnings"])


def test_unowned_carryover_also_reserves_half_points():
    carried = {"id": 1, "area_path": "Demo", "assigned_to": "", "assigned_unique": "", "points": 5}
    person = {**crew()[0], "velocity_based": True, "forecast_status": "ready", "working_days": 10, "pto_days": 0, "capacity_points": 2.5}
    result = planning.make_plan(people=[person], carried=[carried], planned=[], backlog=[], per_person=6)
    assert result["people"][0]["carried"] == [{**carried, "matched_area": "*"}]
    assert result["people"][0]["points_reserved"] == 2.5
    assert result["people"][0]["new"] == []


def test_incomplete_historical_batch_pauses_forecast_explicitly():
    board = VelocityBoard()
    board.get_work_items_batch = lambda *args, **kwargs: []
    with pytest.raises(planning.PlanningError, match="snapshots are incomplete"):
        completed_points(board, PROJECT, TEAM, planning.list_sprints(board, PROJECT, TEAM)[1], ["User Story"])


def test_shared_capacity_counts_overlapping_pto_once_and_keeps_zero_daily_capacity():
    rows = [{"teamMember": {"displayName": "Ava"}, "activities": [{"capacityPerDay": 0}],
             "daysOff": [{"start": "2026-10-05", "end": "2026-10-07"}, {"start": "2026-10-06", "end": "2026-10-09"}]}]
    result = normalize_capacity_members(rows, planning.parse_when("2026-10-05"), planning.parse_when("2026-10-16"))
    assert result[0]["days_off"] == 5
    assert result[0]["capacity_per_day"] == 0

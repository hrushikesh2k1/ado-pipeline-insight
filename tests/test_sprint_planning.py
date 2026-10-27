"""Sprint planning: the three rules (six stories each, flag what is blocked or active too long, areas of choice), and the awkward cases. All data is made up."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.services import sprint_planning as sp
from app.services.work_item_scope import StateMap
from sprint_support import (
    NOW, PROJECT, SPRINTS, STATES, TEAM, FakeBoard, ago, comment, http_error, person, story,
)

AVA = {"name": "Ava Stone", "unique_name": "ava@example.test", "areas": ["Demo\\Alpha\\Backend"]}
BEN = {"name": "Ben Ortiz", "unique_name": "ben@example.test", "areas": ["Demo\\Alpha\\Backend", "Demo\\Alpha\\Frontend"]}
CARA = {"name": "Cara Lin", "unique_name": "cara@example.test", "areas": ["Demo\\Alpha\\Frontend"]}
BACKEND, FRONTEND, OPS = "Demo\\Alpha\\Backend", "Demo\\Alpha\\Frontend", "Demo\\Alpha\\Ops"
S2, S3 = "Demo\\Sprint 2", "Demo\\Sprint 3"


def plain(item_id: int, area: str = BACKEND, who: str | None = None) -> dict:
    """A story as make_plan reads it."""
    name, unique = (person(who)["displayName"], person(who)["uniqueName"]) if who else ("", "")
    return {"id": item_id, "title": f"Story {item_id}", "area_path": area, "assigned_to": name, "assigned_unique": unique, "flags": [], "matched_area": None}


def plan(people, carried=(), planned=(), backlog=(), per_person=6):
    return sp.make_plan(people=sp.normalize_people(people), carried=list(carried), planned=list(planned), backlog=list(backlog), per_person=per_person)


def row(result, name):
    return next(r for r in result["people"] if r["name"] == name)


def ids(stories):
    return [s["id"] for s in stories]


# ---------------------------------------------------------------- sprints

class TestSprints:
    def test_the_sprints_are_listed_oldest_first_with_their_time_frame(self):
        sprints = sp.list_sprints(FakeBoard([], sprints=list(reversed(SPRINTS))), PROJECT, TEAM)
        assert [s["id"] for s in sprints] == ["s1", "s2", "s3", "s4"] and sprints[1]["time_frame"] == "current" and sprints[0]["name"] == "Sprint 1"

    def test_the_current_sprint_and_the_one_after_it_are_proposed(self):
        assert sp.default_sprints(sp.list_sprints(FakeBoard([]), PROJECT, TEAM)) == ("s2", "s3")

    def test_with_no_current_sprint_the_last_past_one_and_the_first_future_one(self):
        frames = [{**s, "attributes": {**s["attributes"], "timeFrame": "past" if s["id"] in ("s1", "s2") else "future"}} for s in SPRINTS]
        assert sp.default_sprints(sp.list_sprints(FakeBoard([], sprints=frames), PROJECT, TEAM)) == ("s2", "s3")

    def test_with_no_future_sprint_there_is_nothing_to_plan(self):
        frames = [{**s, "attributes": {**s["attributes"], "timeFrame": "past" if s["id"] != "s2" else "current"}} for s in SPRINTS[:2]]
        assert sp.default_sprints(sp.list_sprints(FakeBoard([], sprints=frames), PROJECT, TEAM)) == ("s2", None)

    def test_no_sprints_at_all(self):
        assert sp.default_sprints([]) == (None, None)


# ---------------------------------------------------------------- rule 2: what is flagged

class TestFlags:
    def flags(self, state="Active", category="inprogress", tags=(), blocked=None, elapsed=timedelta(days=2), days=10):
        return [(f["code"], f["reason"]) for f in sp.story_flags(state, category, list(tags), blocked, elapsed, days)]

    @pytest.mark.parametrize("tags", [["Blocked"], ["blocked"], ["Team A", "BLOCKED"], ["blocked-by-vendor"]])
    def test_a_blocked_tag_flags_the_story(self, tags):
        assert [c for c, _ in self.flags(tags=tags)] == ["blocked"]

    def test_the_reason_names_what_said_so(self):
        assert self.flags(tags=["Blocked"]) == [("blocked", 'Blocked: tag "Blocked"')]
        assert self.flags(state="Blocked", category="inprogress") == [("blocked", 'Blocked: state "Blocked"')]
        assert self.flags(blocked="Yes") == [("blocked", "Blocked: the Blocked field is Yes")]
        assert self.flags(tags=["Blocked"], blocked="Yes", state="Blocked")[0][1] == 'Blocked: tag "Blocked", state "Blocked", the Blocked field is Yes'

    @pytest.mark.parametrize("blocked", [None, "", "No", "no", False])
    def test_a_blocked_field_that_says_no_flags_nothing(self, blocked):
        assert self.flags(blocked=blocked) == []

    def test_a_story_active_for_more_than_the_limit_is_flagged(self):
        assert self.flags(elapsed=timedelta(days=14)) == [("active_too_long", 'In "Active" for 14 days (more than 10)')]

    def test_exactly_the_limit_is_not_more_than_the_limit(self):
        assert self.flags(elapsed=timedelta(days=10)) == []
        assert [c for c, _ in self.flags(elapsed=timedelta(days=10, hours=1))] == ["active_too_long"]

    def test_the_limit_is_the_callers(self):
        assert [c for c, _ in self.flags(elapsed=timedelta(days=4), days=3)] == ["active_too_long"] and self.flags(elapsed=timedelta(days=4), days=5) == []

    @pytest.mark.parametrize("category", ["proposed", "resolved", "completed", "removed"])
    def test_only_an_active_state_counts_as_active(self, category):
        assert self.flags(category=category, elapsed=timedelta(days=40)) == []

    def test_unknown_time_is_not_a_reason(self):
        assert self.flags(elapsed=None) == []

    def test_a_story_can_be_both(self):
        assert [c for c, _ in self.flags(tags=["Blocked"], elapsed=timedelta(days=30))] == ["blocked", "active_too_long"]


class TestOneStory:
    def made(self, item, active_days=10, project="Demo"):
        return sp.make_story(item, states=StateMap(STATES), now=NOW, active_days=active_days, organization="myorg", project=project)

    def test_the_story_as_the_plan_shows_it(self):
        s = self.made(story(7, "Add the report", state="Active", who="ava", tags="Backend; Blocked", since=ago(14), points=5))
        assert (s["id"], s["title"], s["type"], s["state"], s["state_category"]) == (7, "Add the report", "User Story", "Active", "inprogress")
        assert (s["assigned_to"], s["assigned_unique"], s["tags"], s["points"]) == ("Ava Stone", "ava@example.test", ["Backend", "Blocked"], 5.0)
        assert (s["days_in_state"], s["state_since_exact"], s["state_since"]) == (14, True, "2026-09-24T12:00:00Z")
        assert [f["code"] for f in s["flags"]] == ["blocked", "active_too_long"] and s["comments"] is None

    def test_the_link_opens_the_work_item_and_handles_spaces(self):
        assert self.made(story(7), project="My Project")["url"] == "https://dev.azure.com/myorg/My%20Project/_workitems/edit/7"

    @pytest.mark.parametrize("value,expected", [
        ({"displayName": "Ava Stone", "uniqueName": "ava@example.test"}, ("Ava Stone", "ava@example.test")), ("Ava Stone <ava@example.test>", ("Ava Stone", "ava@example.test")),
        ("Ava Stone", ("Ava Stone", "")), (None, ("", "")), ("", ("", "")),
    ])
    def test_who_a_story_is_assigned_to(self, value, expected):
        assert sp.assignee(value) == expected

    def test_without_the_state_changed_date_the_activated_date_is_used_and_it_says_so(self):
        item = story(7, state="Active", since=ago(1))
        item["fields"].pop("Microsoft.VSTS.Common.StateChangeDate")
        item["fields"]["Microsoft.VSTS.Common.ActivatedDate"] = ago(12)
        s = self.made(item)
        assert (s["days_in_state"], s["state_since_exact"]) == (12, False) and [f["code"] for f in s["flags"]] == ["active_too_long"]

    def test_without_either_date_the_last_change_is_used(self):
        item = story(7, state="Active", since=ago(3))
        item["fields"].pop("Microsoft.VSTS.Common.StateChangeDate")
        assert (self.made(item)["days_in_state"], self.made(item)["state_since_exact"]) == (3, False)

    def test_a_story_with_no_dates_has_no_days(self):
        item = story(7)
        for key in ("Microsoft.VSTS.Common.StateChangeDate", "System.ChangedDate"):
            item["fields"].pop(key)
        s = self.made(item)
        assert s["days_in_state"] is None and s["state_since"] is None and s["flags"] == []

    def test_the_last_comments_are_plain_text_oldest_of_them_first(self):
        board = FakeBoard([], comments={7: [comment("<p>Waiting for <b>the vendor</b></p>", "Cara Lin", "2026-10-07T10:00:00Z"), comment("Asked again", "Ava Stone", "2026-10-05T10:00:00Z"),
                                            comment("First ask", "Ava Stone", "2026-10-01T10:00:00Z"), comment("Much older", "Ava Stone", "2026-09-20T10:00:00Z")]})
        found = sp.read_comments(board, PROJECT, 7)
        assert [(c["author"], c["text"]) for c in found] == [("Ava Stone", "First ask"), ("Ava Stone", "Asked again"), ("Cara Lin", "Waiting for the vendor")]

    def test_a_long_comment_is_cut_and_a_failure_is_none(self):
        assert sp.read_comments(FakeBoard([], comments={7: [comment("x" * 2000)]}), PROJECT, 7)[0]["text"].endswith("…")
        assert len(sp.read_comments(FakeBoard([], comments={7: [comment("x" * 2000)]}), PROJECT, 7)[0]["text"]) == sp.COMMENT_CHARS
        assert sp.read_comments(FakeBoard([], comments={7: http_error(403)}), PROJECT, 7) is None
        assert sp.read_comments(FakeBoard([]), PROJECT, 7) == []


# ---------------------------------------------------------------- rule 3: areas of choice

class TestAreasOfChoice:
    @pytest.mark.parametrize("area,chosen,expected", [
        ("Demo\\Alpha\\Backend", ["Demo\\Alpha\\Backend"], "Demo\\Alpha\\Backend"),
        ("Demo\\Alpha\\Backend\\Api", ["Demo\\Alpha\\Backend"], "Demo\\Alpha\\Backend"),  # under a chosen area
        ("Demo\\Alpha\\Frontend", ["Demo\\Alpha\\Backend"], None),
        ("Demo\\Alpha\\BackendTools", ["Demo\\Alpha\\Backend"], None),  # a longer name is not a child
        ("demo\\alpha\\backend", ["Demo\\Alpha\\Backend"], "Demo\\Alpha\\Backend"),
        ("Demo/Alpha/Backend", ["Demo\\Alpha\\Backend"], "Demo\\Alpha\\Backend"),
        ("Demo\\Alpha\\Ops", ["Demo\\Alpha\\Backend", "Demo\\Alpha\\Ops"], "Demo\\Alpha\\Ops"),
        ("Demo\\Alpha\\Ops", ["*"], "*"), ("Demo\\Alpha\\Ops", [], None), ("Demo\\Alpha\\Ops", [""], None),
    ])
    def test_a_story_matches_an_area_it_is_in_or_under(self, area, chosen, expected):
        assert sp.area_matches(area, chosen) == expected

    def test_people_are_cleaned_up(self):
        clean = sp.normalize_people([
            {"name": " Ava Stone ", "unique_name": "ava@example.test", "areas": ["Demo\\Alpha\\Backend", " Demo\\Alpha\\Backend ", "", "Demo\\Alpha\\Ops"]},
            {"name": "Ava Again", "unique_name": "AVA@example.test", "areas": []},  # the same person
            {"name": "", "unique_name": "", "areas": []}, {"name": "Cara Lin", "areas": None},
        ])
        assert clean == [{"name": "Ava Stone", "unique_name": "ava@example.test", "areas": ["Demo\\Alpha\\Backend", "Demo\\Alpha\\Ops"]}, {"name": "Cara Lin", "unique_name": "", "areas": []}]


# ---------------------------------------------------------------- the plan

class TestRuleOneEachPersonGetsSix:
    def test_carried_over_stories_count_towards_the_six_and_the_rest_is_filled(self):
        backlog = [plain(100 + n) for n in range(10)]
        result = plan([AVA], carried=[plain(1, who="ava"), plain(2, who="ava")], backlog=backlog)
        ava = row(result, "Ava Stone")
        assert ids(ava["carried"]) == [1, 2] and ids(ava["new"]) == [100, 101, 102, 103] and ava["total"] == 6 and ava["open_places"] == 0 and ava["warnings"] == []

    def test_six_is_the_default_and_the_number_can_change(self):
        assert sp.DEFAULT_PER_PERSON == 6
        assert row(plan([AVA], backlog=[plain(n) for n in range(10)], per_person=3), "Ava Stone")["total"] == 3

    def test_the_backlog_is_taken_in_its_order(self):
        assert ids(row(plan([AVA], backlog=[plain(9), plain(3), plain(7)], per_person=2), "Ava Stone")["new"]) == [9, 3]

    def test_stories_already_in_the_next_sprint_count_too(self):
        result = plan([AVA], planned=[plain(5, who="ava")], backlog=[plain(100), plain(101)], per_person=2)
        assert ids(row(result, "Ava Stone")["already_planned"]) == [5] and ids(row(result, "Ava Stone")["new"]) == [100]

    def test_more_carried_than_six_stay_and_are_reported_over(self):
        result = plan([AVA], carried=[plain(n, who="ava") for n in range(1, 9)], backlog=[plain(100)])
        ava = row(result, "Ava Stone")
        assert len(ava["carried"]) == 8 and ava["new"] == [] and ava["over_by"] == 2 and "2 more than the 6 planned" in ava["warnings"][0]

    def test_a_person_the_backlog_cannot_fill_is_told_how_many_places_are_empty(self):
        ava = row(plan([AVA], backlog=[plain(100), plain(101)]), "Ava Stone")
        assert ava["total"] == 2 and ava["open_places"] == 4 and ava["warnings"] == ["4 places still empty: no unassigned story is left in their areas."]
        assert row(plan([AVA], backlog=[plain(100)], per_person=2), "Ava Stone")["warnings"] == ["1 place still empty: no unassigned story is left in their areas."]

    def test_everyone_gets_their_six_when_there_is_enough(self):
        result = plan([AVA, BEN, CARA], backlog=[plain(n, BACKEND if n % 2 else FRONTEND) for n in range(100, 140)])
        assert [r["total"] for r in result["people"]] == [6, 6, 6]

    def test_it_stops_when_everyone_is_full_and_counts_what_is_left_in_the_backlog(self):
        result = plan([AVA], backlog=[plain(n) for n in range(10)], per_person=2)
        assert result["backlog_left"] == 8 and result["unplaced"] == [] and result["unplaced_total"] == 0


class TestRuleThreeAreasOfChoice:
    def test_a_story_goes_to_someone_who_chose_its_area(self):
        result = plan([AVA, CARA], backlog=[plain(1, FRONTEND), plain(2, BACKEND)], per_person=1)
        assert ids(row(result, "Cara Lin")["new"]) == [1] and ids(row(result, "Ava Stone")["new"]) == [2]
        assert row(result, "Cara Lin")["new"][0]["matched_area"] == FRONTEND

    def test_a_story_under_a_chosen_area_goes_there_too(self):
        assert ids(row(plan([AVA], backlog=[plain(1, BACKEND + "\\Api")], per_person=1), "Ava Stone")["new"]) == [1]

    def test_two_people_may_share_an_area_and_the_one_with_more_free_places_takes_it(self):
        result = plan([AVA, BEN], carried=[plain(1, who="ava"), plain(2, who="ava")], backlog=[plain(10), plain(11)], per_person=4)
        # Ben has four free places and Ava two: the first backend story is Ben's; then Ben has three and Ava two, so the second is Ben's too
        assert ids(row(result, "Ben Ortiz")["new"]) == [10, 11]

    def test_when_they_are_level_the_person_with_fewer_areas_takes_it(self):
        result = plan([BEN, AVA], backlog=[plain(10, BACKEND)], per_person=1)
        assert ids(row(result, "Ava Stone")["new"]) == [10] and row(result, "Ben Ortiz")["new"] == []

    def test_a_person_with_no_areas_gets_nothing_new_and_a_warning(self):
        result = plan([AVA, {"name": "Dan Reyes", "areas": []}], backlog=[plain(n) for n in range(10)], per_person=3)
        dan = row(result, "Dan Reyes")
        assert dan["new"] == [] and dan["warnings"][0].startswith("No area of choice is set") and ids(row(result, "Ava Stone")["new"]) == [0, 1, 2]

    def test_any_area_takes_whatever_comes(self):
        result = plan([{"name": "Dan Reyes", "areas": ["*"]}], backlog=[plain(1, OPS), plain(2, "Demo\\Beta\\Reports")], per_person=2)
        assert ids(row(result, "Dan Reyes")["new"]) == [1, 2]

    def test_an_area_nobody_chose_is_listed_with_that_reason(self):
        result = plan([AVA, CARA], backlog=[plain(1, OPS), plain(2, BACKEND)], per_person=2)
        assert [(u["story"]["id"], u["reason"]) for u in result["unplaced"]] == [(1, "nobody has chosen this area")] and result["unplaced_total"] == 1

    def test_an_area_whose_people_are_all_full_says_so(self):
        result = plan([AVA, CARA], backlog=[plain(1, BACKEND), plain(2, BACKEND), plain(3, FRONTEND)], per_person=1)
        assert [(u["story"]["id"], u["reason"]) for u in result["unplaced"]] == [(2, "everyone who chose this area already has a full sprint")]

    def test_only_the_first_unplaced_stories_are_listed_and_all_are_counted(self):
        result = plan([AVA], backlog=[plain(n, OPS) for n in range(80)], per_person=1)
        assert len(result["unplaced"]) == sp.MAX_UNPLACED_LISTED and result["unplaced_total"] == 80

    def test_the_same_input_gives_the_same_plan(self):
        backlog = [plain(n, [BACKEND, FRONTEND][n % 2]) for n in range(30)]
        assert plan([AVA, BEN, CARA], backlog=backlog) == plan([AVA, BEN, CARA], backlog=backlog)


class TestCarriedOverStories:
    def test_an_open_story_stays_with_its_owner_whatever_the_owners_areas(self):
        result = plan([AVA], carried=[plain(1, OPS, who="ava")], per_person=1)
        assert ids(row(result, "Ava Stone")["carried"]) == [1]

    def test_stories_of_people_who_are_not_in_the_plan_are_listed_apart(self):
        result = plan([AVA], carried=[plain(1, who="dan"), plain(2, who="ava")], backlog=[plain(10)], per_person=2)
        assert ids(result["outside_plan"]) == [1] and ids(row(result, "Ava Stone")["carried"]) == [2] and ids(row(result, "Ava Stone")["new"]) == [10]

    def test_an_open_story_with_nobody_on_it_is_taken_before_the_backlog(self):
        result = plan([AVA], carried=[plain(1)], backlog=[plain(10), plain(11)], per_person=2)
        assert ids(row(result, "Ava Stone")["new"]) == [1, 10] and row(result, "Ava Stone")["carried"] == []

    def test_a_person_is_found_by_unique_name_or_by_name(self):
        by_mail = {**plain(1), "assigned_to": "A. Stone", "assigned_unique": "AVA@example.test"}
        by_name = {**plain(2), "assigned_to": "ava stone", "assigned_unique": ""}
        assert ids(row(plan([AVA], carried=[by_mail, by_name], per_person=2), "Ava Stone")["carried"]) == [1, 2]


# ---------------------------------------------------------------- from Azure DevOps

def scenario_items():
    return [
        # the current sprint
        story(10, "Slow export", state="Active", who="ava", since=ago(14), iteration=S2),
        story(11, "Fresh work", state="Active", who="ava", since=ago(2), iteration=S2),
        story(12, "Waiting on vendor", state="New", who="ben", tags="Blocked", iteration=S2),
        story(13, "Already done", state="Closed", who="ben", iteration=S2),
        story(14, "Page layout", state="Active", who="cara", since=ago(3), iteration=S2, area=FRONTEND),
        story(15, "Nobody took it", state="Active", since=ago(1), iteration=S2, area=FRONTEND),
        story(16, "Dropped", state="Removed", who="ava", iteration=S2),
        story(17, "Someone who left", state="Active", who="dan", since=ago(1), iteration=S2),
        story(18, "A bug", state="Active", who="ava", since=ago(1), iteration=S2, kind="Bug"),
        story(19, "Another team's", state="Active", who="ava", since=ago(1), iteration=S2, area="Demo\\Beta\\Reports"),
        # the sprint being planned
        story(20, "Planned already", state="New", who="ava", iteration=S3),
        # the backlog (iteration = the project), unassigned
        story(30, "Backend one", rank=1), story(31, "Backend two", rank=2), story(32, "Frontend one", rank=3, area=FRONTEND), story(33, "Ops one", rank=4, area=OPS),
        story(34, "Backend three", rank=5), story(35, "Frontend two", rank=6, area=FRONTEND), story(36, "Backend four", rank=7),
        story(40, "Taken in the backlog", who="ben", rank=8),
        story(41, "In another sprint", iteration="Demo\\Sprint 4", rank=9),
        story(42, "Not started in Active", state="Active", rank=10),
    ]


def run(board=None, people=(AVA, BEN, CARA), per_person=3, **over):
    board = board or FakeBoard(scenario_items(), comments={10: [comment("newest", when="2026-10-07T10:00:00Z"), comment("middle", when="2026-10-04T10:00:00Z"),
                                                                comment("older", when="2026-10-01T10:00:00Z"), comment("oldest", when="2026-09-20T10:00:00Z")],
                                                         12: [comment("Vendor has not answered", "Ben Ortiz")]})
    kwargs = dict(organization="myorg", project=PROJECT, team=TEAM, from_iteration_id="s2", to_iteration_id="s3", people=[dict(p) for p in people], per_person=per_person, now=NOW)
    kwargs.update(over)
    return sp.plan_sprint(board, **kwargs), board


class TestPlanFromAzureDevOps:
    def test_each_person_gets_the_carried_over_stories_and_then_stories_of_their_areas(self):
        result, _ = run()
        by = {r["name"]: r for r in result["people"]}
        assert ids(by["Ava Stone"]["carried"]) == [10, 11] and ids(by["Ava Stone"]["already_planned"]) == [20] and by["Ava Stone"]["new"] == [] and by["Ava Stone"]["total"] == 3
        assert ids(by["Ben Ortiz"]["carried"]) == [12] and ids(by["Ben Ortiz"]["new"]) == [30, 31]
        assert ids(by["Cara Lin"]["carried"]) == [14] and ids(by["Cara Lin"]["new"]) == [15, 32]  # the ownerless open story first, then the backlog
        assert [r["total"] for r in result["people"]] == [3, 3, 3] and all(r["warnings"] == [] for r in result["people"])

    def test_what_is_finished_removed_a_bug_or_another_teams_is_not_carried(self):
        result, _ = run()
        everything = [s["id"] for r in result["people"] for s in r["carried"] + r["already_planned"] + r["new"]] + ids(result["outside_plan"])
        assert not {13, 16, 18, 19, 40, 41, 42} & set(everything)

    def test_the_stories_of_someone_who_is_not_in_the_plan_are_listed_apart(self):
        result, _ = run()
        assert ids(result["outside_plan"]) == [17] and "Open stories of people who are not in this plan: 1 (listed apart, not counted for anyone)." in result["notes"]

    def test_blocked_and_long_active_stories_are_flagged_with_their_last_three_comments(self):
        result, board = run()
        assert ids(result["flagged"]) == [10, 12]
        slow, blocked = result["flagged"]
        assert [f["code"] for f in slow["flags"]] == ["active_too_long"] and slow["days_in_state"] == 14
        assert [c["text"] for c in slow["comments"]] == ["older", "middle", "newest"]  # three, oldest of them first
        assert [f["code"] for f in blocked["flags"]] == ["blocked"] and [c["text"] for c in blocked["comments"]] == ["Vendor has not answered"]
        assert sorted(board.comment_reads) == [10, 12]  # comments are read for the flagged stories only

    def test_the_summary_counts(self):
        s = run()[0]["summary"]
        assert (s["people"], s["stories_planned"], s["carried"], s["new"], s["already_planned"], s["flagged"], s["blocked"], s["long_active"], s["open_places"]) == (3, 9, 4, 4, 1, 2, 1, 1, 0)

    def test_the_plan_is_marked_as_made_at_a_time(self):
        assert run()[0]["generated_at"] == "2026-10-08T12:00:00Z"

    def test_the_story_limit_is_the_callers(self):
        result, _ = run(per_person=2)
        assert [r["total"] for r in result["people"]] == [3, 2, 2] and result["people"][0]["over_by"] == 1  # Ava carries two and has one planned already

    def test_a_flagged_story_still_counts_for_its_owner(self):
        by = {r["name"]: r for r in run()[0]["people"]}
        assert 10 in ids(by["Ava Stone"]["carried"]) and by["Ava Stone"]["carried"][0]["flags"]

    def test_the_active_days_limit_is_the_callers(self):
        assert ids(run(active_days=1)[0]["flagged"]) == [10, 11, 12, 14]  # 15 and 17 are exactly one day in their state: not more than one
        assert ids(run(active_days=30)[0]["flagged"]) == [12]

    def test_the_comments_are_not_read_for_stories_that_are_not_flagged(self):
        _, board = run(active_days=30)
        assert board.comment_reads == [12]

    def test_comments_that_cannot_be_read_do_not_stop_the_plan(self):
        board = FakeBoard(scenario_items(), comments={10: http_error(403), 12: [comment("ok")]})
        result, _ = run(board)
        assert [s["comments"] for s in result["flagged"]] == [None, [{"author": "Ava Stone", "date": "2026-10-01T09:00:00Z", "text": "ok"}]]
        assert any("comments of some flagged stories could not be read" in n for n in result["notes"])

    def test_no_flagged_story_means_no_comment_reads(self):
        board = FakeBoard([story(11, state="Active", who="ava", since=ago(1), iteration=S2), story(30)])
        result, board = run(board, people=[AVA], per_person=2)
        assert result["flagged"] == [] and board.comment_reads == []

    def test_the_wiql_asks_for_the_right_things(self):
        _, board = run()
        carried, planned, backlog = board.queries
        assert "[System.IterationPath] IN ('Demo\\Sprint 2')" in carried and "[System.State] NOT IN ('Closed', 'Done', 'Removed')" in carried
        assert "[System.IterationPath] IN ('Demo\\Sprint 3')" in planned and "[System.State] NOT IN ('Closed', 'Done', 'Removed')" in planned
        assert "[System.IterationPath] NOT IN ('Demo\\Sprint 2')" in backlog and "[System.State] NOT IN ('Closed', 'Done', 'Removed')" in backlog and "[System.AssignedTo] = ''" in backlog
        assert all("[System.TeamProject] = 'Demo'" in q and "[System.WorkItemType] IN ('User Story')" in q and "[System.AreaPath] UNDER 'Demo\\Alpha'" in q for q in board.queries)
        assert all(q.endswith("ORDER BY [Microsoft.VSTS.Common.BacklogPriority] ASC, [System.Id] ASC") for q in board.queries)

    def test_a_name_with_an_apostrophe_is_quoted(self):
        assert "[System.TeamProject] = 'O''Neil''s'" in sp.build_wiql("O'Neil's", types=["User Story"], areas=[], order="[System.Id] ASC")

    def test_the_backlog_is_read_a_limited_way_down(self):
        class Spy(FakeBoard):
            tops: list = []

            def query_wiql(self, project, wiql, top=None):
                self.tops.append(top)
                return super().query_wiql(project, wiql, top)
        board = Spy(scenario_items())
        board.tops = []
        run(board)
        assert board.tops == [None, None, sp.MAX_BACKLOG]

    def test_an_empty_backlog_is_said_in_a_note(self):
        result, _ = run(FakeBoard([story(10, state="Active", who="ava", since=ago(1), iteration=S2)]), people=[AVA], per_person=2)
        assert any("No backlog stories were found" in n for n in result["notes"]) and row(result, "Ava Stone")["open_places"] == 1

    def test_a_story_of_another_teams_area_is_left_out_even_if_the_query_returned_it(self):
        result, _ = run(FakeBoard(scenario_items(), ignore_areas=True))
        everything = {s["id"] for r in result["people"] for s in r["carried"] + r["already_planned"] + r["new"]} | set(ids(result["outside_plan"]))
        assert 19 not in everything

    def test_an_unassigned_story_already_in_the_next_sprint_is_offered_like_the_backlog(self):
        items = [story(60, "In the sprint, nobody on it", iteration=S3, rank=0.5), story(61, "Backlog", rank=2)]
        result, _ = run(FakeBoard(items), people=[AVA], per_person=2)
        assert ids(row(result, "Ava Stone")["new"]) == [60, 61] and row(result, "Ava Stone")["already_planned"] == []

    def test_a_story_in_the_next_sprint_that_belongs_to_someone_outside_the_plan_is_said(self):
        items = [story(60, "Dan's", who="dan", iteration=S3, state="Active", since=ago(1)), story(61, "Backlog", rank=2)]
        result, _ = run(FakeBoard(items), people=[AVA], per_person=2)
        assert "Stories already in Sprint 3 that belong to people who are not in this plan: 1 (not counted for anyone)." in result["notes"] and ids(row(result, "Ava Stone")["new"]) == [61]

    def test_a_story_the_server_returns_twice_is_planned_once(self):
        class Overlapping(FakeBoard):
            def query_wiql(self, project, wiql, top=None):
                found = super().query_wiql(project, wiql, top)
                return [10] + found if "'Demo', 'Demo\\Sprint 3'" in wiql else found  # the backlog answer also holds a story of the current sprint
        result, _ = run(Overlapping(scenario_items()))
        listed = [s["id"] for r in result["people"] for s in r["carried"] + r["already_planned"] + r["new"]]
        assert listed.count(10) == 1 and len(listed) == len(set(listed))

    def test_the_stories_of_one_team_only(self):
        result, board = run(FakeBoard(scenario_items(), team_areas={"values": [{"value": "Demo\\Alpha\\Frontend", "includeChildren": False}]}))
        assert all("[System.AreaPath] = 'Demo\\Alpha\\Frontend'" in q for q in board.queries)
        assert {s["id"] for r in result["people"] for s in r["carried"] + r["new"]} == {14, 15, 32, 35}

    def test_a_team_without_area_paths_looks_at_every_area(self):
        _, board = run(FakeBoard(scenario_items(), team_areas={"values": []}))
        assert all("AreaPath" not in q for q in board.queries)

    def test_area_paths_that_cannot_be_read_are_said(self):
        result, board = run(FakeBoard(scenario_items(), fail=("team_areas",)))
        assert any("area paths of team 'Alpha' could not be read" in n for n in result["notes"]) and all("AreaPath" not in q for q in board.queries)


class TestAProcessThatDiffers:
    def test_a_process_without_the_backlog_priority_is_read_in_stack_rank_order(self):
        result, board = run(FakeBoard(scenario_items(), no_backlog_order=True))
        assert ids(row(result, "Ben Ortiz")["new"]) == [30, 31] and any("StackRank" in q for q in board.queries)

    def test_a_process_with_neither_is_read_in_id_order(self):
        result, board = run(FakeBoard(scenario_items(), no_backlog_order=True, no_stack_rank=True))
        assert ids(row(result, "Ben Ortiz")["new"]) == [30, 31] and board.queries[-1].endswith("ORDER BY [System.Id] ASC")

    def test_a_field_the_process_does_not_have_is_dropped_and_the_plan_still_works(self):
        result, board = run(FakeBoard(scenario_items(), reject_fields=("Microsoft.VSTS.CMMI.Blocked",)))
        assert result["summary"]["stories_planned"] == 9 and len(board.field_requests) == 2 and "Microsoft.VSTS.CMMI.Blocked" not in board.field_requests[-1]

    def test_without_the_state_changed_field_the_days_are_a_guess_and_it_says_so(self):
        result, _ = run(FakeBoard(scenario_items(), reject_fields=("Microsoft.VSTS.CMMI.Blocked", "Microsoft.VSTS.Common.StateChangeDate")))
        assert any("no 'state changed' date" in n for n in result["notes"]) and ids(result["flagged"])[-1:] == [12]

    def test_the_blocked_field_is_used_when_the_process_has_it(self):
        items = scenario_items() + [story(50, "Stuck", state="Active", who="cara", since=ago(1), iteration=S2, area=FRONTEND, blocked="Yes")]
        assert 50 in ids(run(FakeBoard(items), per_person=4)[0]["flagged"])

    def test_the_story_type_of_another_process(self):
        board = FakeBoard([story(1, "Item", kind="Product Backlog Item", who="ava", state="Committed", iteration=S2, since=ago(1)), story(2, "More", kind="Product Backlog Item", rank=1)],
                          types=["Product Backlog Item", "Bug"])
        result, board = run(board, people=[AVA], per_person=2)
        assert ids(row(result, "Ava Stone")["carried"]) == [1] and "[System.WorkItemType] IN ('Product Backlog Item')" in board.queries[0]

    def test_bugs_are_planned_when_asked_for(self):
        result, board = run(work_item_types=["User Story", "Bug"], per_person=4)
        assert 18 in ids(row(result, "Ava Stone")["carried"]) and "[System.WorkItemType] IN ('User Story', 'Bug')" in board.queries[0]

    def test_types_the_project_does_not_have_are_left_out_of_the_query(self):
        _, board = run(work_item_types=["User Story", "Epic"])
        assert "[System.WorkItemType] IN ('User Story')" in board.queries[0] and "Epic" not in board.queries[0]


class TestWhatTheCallerCanFix:
    @pytest.mark.parametrize("over,message", [
        ({"people": []}, "Add at least one person"), ({"people": [{"name": "", "areas": []}]}, "Add at least one person"), ({"per_person": 0}, "between 1 and 30"),
        ({"per_person": 31}, "between 1 and 30"), ({"active_days": 0}, "between 1 and 90"), ({"to_iteration_id": "s2"}, "different sprint"), ({"to_iteration_id": "nope"}, "not a sprint of this team"),
        ({"from_iteration_id": "nope"}, "not a sprint of this team"), ({"work_item_types": ["Epic"]}, "None of the story types"),
        ({"people": [{"name": f"P{n}", "areas": []} for n in range(41)]}, "At most 40 people"),
    ])
    def test_a_request_that_cannot_be_planned_says_why(self, over, message):
        with pytest.raises(sp.PlanningError, match=message) as caught:
            run(**over)
        assert caught.value.status_code == 422

    def test_a_failure_of_azure_devops_is_not_hidden(self):
        with pytest.raises(Exception, match="HTTP 500"):
            run(FakeBoard(scenario_items(), fail=("iterations",)))


class TestSetup:
    def test_what_the_page_needs_to_start(self):
        setup = sp.team_setup(FakeBoard([]), PROJECT, TEAM)
        assert [s["id"] for s in setup["sprints"]] == ["s1", "s2", "s3", "s4"] and (setup["default_from_id"], setup["default_to_id"]) == ("s2", "s3")
        assert [m["name"] for m in setup["members"]] == ["Ava Stone", "Ben Ortiz", "Cara Lin", "Dan Reyes"] and setup["members"][0]["unique_name"] == "ava@example.test"
        assert (setup["per_person"], setup["active_days"], setup["notes"]) == (6, 10, [])

    def test_the_areas_to_choose_from_are_the_teams_own(self):
        assert sp.team_setup(FakeBoard([]), PROJECT, TEAM)["areas"] == ["Demo\\Alpha", "Demo\\Alpha\\Backend", "Demo\\Alpha\\Backend\\Api", "Demo\\Alpha\\Frontend", "Demo\\Alpha\\Ops"]

    def test_a_team_without_areas_is_offered_every_area(self):
        areas = sp.team_setup(FakeBoard([], team_areas={"values": []}), PROJECT, TEAM)["areas"]
        assert areas[0] == "Demo" and "Demo\\Beta\\Reports" in areas and len(areas) == 8

    def test_the_story_types_the_project_has(self):
        setup = sp.team_setup(FakeBoard([]), PROJECT, TEAM)
        assert setup["work_item_types"] == ["User Story", "Bug"] and setup["default_types"] == ["User Story"]
        other = sp.team_setup(FakeBoard([], types=["Product Backlog Item", "Bug", "Task"]), PROJECT, TEAM)
        assert other["work_item_types"] == ["Product Backlog Item", "Bug"] and other["default_types"] == ["Product Backlog Item"]

    def test_groups_are_not_offered_as_people(self):
        members = [{"identity": {"id": "g", "displayName": "[Demo]\\Alpha Team", "uniqueName": "vstfs:///x", "isContainer": True}},
                   {"identity": {"id": "a", "displayName": "Ava Stone", "uniqueName": "ava@example.test"}}]
        assert [m["name"] for m in sp.team_setup(FakeBoard([], members=members), PROJECT, TEAM)["members"]] == ["Ava Stone"]

    @pytest.mark.parametrize("what,note", [("members", "members of the team could not be read"), ("area_tree", "areas of the project could not be read"), ("team_areas", "area paths of team 'Alpha'")])
    def test_what_cannot_be_read_is_said_and_the_rest_still_works(self, what, note):
        setup = sp.team_setup(FakeBoard([], fail=(what,)), PROJECT, TEAM)
        assert any(note in n for n in setup["notes"]) and [s["id"] for s in setup["sprints"]] == ["s1", "s2", "s3", "s4"]

    def test_the_types_that_cannot_be_listed_fall_back_to_the_common_ones(self):
        assert sp.team_setup(FakeBoard([], fail=("types",)), PROJECT, TEAM)["work_item_types"] == list(sp.DEFAULT_TYPES)


class TestZeroCapacity:
    @pytest.mark.parametrize("estimate", [3.0, 0.0, None])
    def test_explicit_zero_point_budget_prevents_all_new_work(self, estimate):
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, "capacity_points": 0}]), carried=[], planned=[],
            backlog=[{**plain(101), "points": estimate}], per_person=6, capacity_mode="points",
        )
        member = result["people"][0]
        assert member["points_capacity"] == 0
        assert member["new"] == []
        assert any("Point capacity is zero" in warning for warning in member["warnings"])
        assert not any("no unassigned story is left" in warning for warning in member["warnings"])

    @pytest.mark.parametrize("capacity_mode", ["points", "stories"])
    @pytest.mark.parametrize("availability", [
        {"working_days": 0},
        {"working_days": 10, "pto_days": 10},
        {"working_days": 10, "pto_days": 12},
        {"working_days": 0, "capacity_points": 20},
        {"working_days": 10, "pto_days": 10, "capacity_points": 20},
    ])
    @pytest.mark.parametrize("estimate", [3.0, 0.0, None])
    def test_no_available_days_prevents_new_work_in_both_modes(self, capacity_mode, availability, estimate):
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, **availability}]), carried=[], planned=[],
            backlog=[{**plain(101), "points": estimate}], per_person=6, capacity_mode=capacity_mode,
        )
        member = result["people"][0]
        assert member["points_capacity"] == 0
        assert member["new"] == []
        assert any("No working days are available" in warning for warning in member["warnings"])
        assert not any("no unassigned story is left" in warning for warning in member["warnings"])

    @pytest.mark.parametrize("capacity_mode", ["points", "stories"])
    def test_existing_commitments_stay_with_their_owner_and_show_zero_budget_overload(self, capacity_mode):
        carryover = {**plain(101, who="ava"), "points": 3.0}
        existing = {**plain(102, who="ava"), "points": 2.0}
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, "working_days": 0}, BEN]),
            carried=[carryover], planned=[existing], backlog=[{**plain(103), "points": 1.0}],
            per_person=6, capacity_mode=capacity_mode,
        )
        unavailable, available = result["people"]
        assert unavailable["carried"] == [carryover]
        assert unavailable["already_planned"] == [existing]
        assert unavailable["new"] == []
        assert unavailable["total"] == 2
        assert unavailable["points_planned"] == 5
        assert unavailable["points_capacity"] == 0
        assert unavailable["points_over_by"] == 5
        assert unavailable["points_open"] == 0
        assert any("Existing commitments remain assigned" in warning for warning in unavailable["warnings"])
        assert any("Capacity exceeded" in warning for warning in unavailable["warnings"])
        assert ids(available["new"]) == [103]
        _, reasons, _, _ = sp._calculate_risks(result["people"], [], [carryover, existing] + available["new"])
        assert "Capacity exceeded for Ava Stone." in reasons

    @pytest.mark.parametrize("capacity_mode", ["points", "stories"])
    def test_unassigned_carryover_cannot_become_new_work_for_someone_without_available_days(self, capacity_mode):
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, "working_days": 0}]),
            carried=[{**plain(101), "points": 1.0}], planned=[], backlog=[],
            per_person=6, capacity_mode=capacity_mode,
        )
        assert result["people"][0]["new"] == []
        assert result["backlog_left"] == 1

    @pytest.mark.parametrize("estimate", [0.0, None])
    def test_unestimated_existing_commitments_are_not_dropped_at_zero_capacity(self, estimate):
        commitment = {**plain(101, who="ava"), "points": estimate}
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, "capacity_points": 0}]), carried=[commitment], planned=[],
            backlog=[{**plain(102), "points": estimate}], per_person=6, capacity_mode="points",
        )
        member = result["people"][0]
        assert member["carried"] == [commitment]
        assert member["new"] == []
        assert member["points_over_by"] == 0
        assert any("Existing commitments remain assigned" in warning for warning in member["warnings"])

    @pytest.mark.parametrize("capacity_mode", ["points", "stories"])
    @pytest.mark.parametrize("capacity", [{}, {"capacity_points": None}, {"working_days": None}, {"capacity_points": 8}])
    def test_positive_and_omitted_capacity_keep_their_existing_behavior(self, capacity_mode, capacity):
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, **capacity}]), carried=[], planned=[],
            backlog=[{**plain(index), "points": 3.0} for index in range(101, 105)], per_person=6,
            capacity_mode=capacity_mode,
        )
        member = result["people"][0]
        assert member["points_capacity"] == 8
        assert ids(member["new"]) == ([101, 102, 103] if capacity_mode == "points" else [101, 102, 103, 104])

    def test_story_count_mode_still_uses_the_story_target_when_working_days_are_available(self):
        result = sp.make_plan(
            people=sp.normalize_people([{**AVA, "capacity_points": 0}]), carried=[], planned=[],
            backlog=[{**plain(index), "points": 3.0} for index in range(101, 104)], per_person=2, capacity_mode="stories",
        )
        assert ids(result["people"][0]["new"]) == [101, 102]


class TestSprintPlanningEnhancements:
    def test_points_capacity_and_workload_calculation(self):
        p1 = {"name": "Ava Stone", "unique_name": "ava@example.test", "areas": [BACKEND], "working_days": 10, "pto_days": 2, "focus_factor": 0.8}
        clean = sp.normalize_people([p1])
        assert clean[0]["working_days"] == 10
        assert clean[0]["pto_days"] == 2
        assert clean[0]["focus_factor"] == 0.8

        res = sp.make_plan(
            people=clean,
            carried=[{"id": 1, "title": "S1", "points": 3.0, "area_path": BACKEND, "assigned_to": "Ava Stone", "assigned_unique": "ava@example.test", "flags": [], "matched_area": None}],
            planned=[],
            backlog=[{"id": 2, "title": "S2", "points": 5.0, "area_path": BACKEND, "assigned_to": "", "assigned_unique": "", "flags": [], "matched_area": None}],
            per_person=6,
        )
        ava_row = res["people"][0]
        assert ava_row["points_carried"] == 3.0
        assert ava_row["points_new"] == 5.0
        assert ava_row["points_planned"] == 8.0
        # (10 - 2) * 0.8 = 6.4 capacity
        assert ava_row["points_capacity"] == 6.4
        assert ava_row["points_over_by"] == 1.6

    def test_commit_sprint_plan(self):
        class MockClient:
            def __init__(self):
                self.calls = []
            def update_work_item(self, project, work_item_id, patch):
                self.calls.append((project, work_item_id, patch))

        client = MockClient()
        res = sp.commit_sprint_plan(
            client,
            project=PROJECT,
            iteration_path="Demo\\Sprint 3",
            assignments=[{"story_id": 101, "assigned_to": "Ava Stone"}, {"story_id": 102, "assigned_to": "Ben Ortiz"}],
        )
        assert res["success"] is True
        assert res["updated_count"] == 2
        assert len(client.calls) == 2
        assert client.calls[0][1] == 101
        assert client.calls[0][2][0]["value"] == "Demo\\Sprint 3"

    def test_tags_and_area_filter_in_wiql_and_matching(self):
        wiql = sp.build_wiql("Demo", types=["User Story"], areas=[("Demo\\Alpha", True)], order="[System.Id] ASC", tags=["Monitoring", "Maintenance"])
        assert "[System.Tags] CONTAINS 'Monitoring'" in wiql
        assert "[System.Tags] CONTAINS 'Maintenance'" in wiql
        assert "[System.AreaPath] UNDER 'Demo\\Alpha'" in wiql

        # Test area matching with tags
        assert sp.area_matches("Demo\\Alpha", ["Monitoring"], tags=["Monitoring", "TeamName"]) == "Monitoring"
        assert sp.area_matches("Demo\\Alpha\\Other", ["cloudops-monitoring"], tags=["CloudOps-Monitoring"]) == "cloudops-monitoring"

    def test_plan_sprint_auto_detects_previous_sprint_when_from_id_omitted(self):
        # When from_iteration_id is None, it should automatically find Sprint 2 (s2) as predecessor of Sprint 3 (s3)
        result, board = run(from_iteration_id=None)
        assert result["from_sprint"]["id"] == "s2"
        assert result["to_sprint"]["id"] == "s3"
        # Carried stories from s2 are still found
        assert result["summary"]["carried"] == 4

    def test_carryovers_assigned_to_same_persons_and_capacity_decremented(self):
        # Ava has 2 carryovers (stories 10, 11) from Sprint 2, Ben has 1 (story 12)
        # Ava's total limit is 3 stories: with 2 carryovers and 1 already planned (20), her capacity is full (0 new).
        # Ben has 1 carryover, so Ben gets 2 new stories to reach 3.
        # Cara has 1 carryover, so Cara gets 2 new stories to reach 3.
        result, _ = run(from_iteration_id=None, per_person=3)
        by = {r["name"]: r for r in result["people"]}
        # Ava: 2 carried, 1 already planned, 0 new
        assert ids(by["Ava Stone"]["carried"]) == [10, 11]
        assert by["Ava Stone"]["new"] == []
        assert by["Ava Stone"]["total"] == 3

        # Ben: 1 carried (12), 2 new (30, 31)
        assert ids(by["Ben Ortiz"]["carried"]) == [12]
        assert ids(by["Ben Ortiz"]["new"]) == [30, 31]
        assert by["Ben Ortiz"]["total"] == 3

        # Cara: 1 carried (14), 2 new (15, 32)
        assert ids(by["Cara Lin"]["carried"]) == [14]
        assert ids(by["Cara Lin"]["new"]) == [15, 32]
        assert by["Cara Lin"]["total"] == 3

    def test_priority_areas_given_in_filter_orders_backlog_assignments(self):
        # CaraLin and Ben both chose Frontend & Backend
        # area_filter specifies priority areas "Demo\Alpha\Frontend, Demo\Alpha\Backend"
        board = FakeBoard([
            story(201, "Backend Item", area=BACKEND, rank=1),
            story(202, "Frontend Item", area=FRONTEND, rank=2),
        ])
        result = sp.plan_sprint(
            board,
            organization="myorg",
            project=PROJECT,
            team=TEAM,
            to_iteration_id="s3",
            people=[BEN],
            per_person=2,
            area_filter="Demo\\Alpha\\Frontend, Demo\\Alpha\\Backend",
        )
        ben_row = result["people"][0]
        # Frontend item prioritized before Backend item
        assert [s["id"] for s in ben_row["new"]] == [202, 201]




class TestPlanningRegressionFixes:
    @pytest.mark.parametrize('settings', [
        {'capacity_points': 0}, {'working_days': 0},
        {'working_days': 10, 'pto_days': 10}, {'working_days': 5, 'pto_days': 8},
    ])
    def test_zero_capacity_never_gets_new_work_in_points_mode(self, settings):
        p = {**AVA, **settings}
        for value in (0, None, 5):
            backlog = [{'id': 99, 'points': value, 'area_path': BACKEND, 'assigned_to': '', 'assigned_unique': '', 'flags': []}]
            result = sp.make_plan(people=[p], carried=[], planned=[], backlog=backlog, per_person=6, capacity_mode='points')
            assert result['people'][0]['points_capacity'] == 0
            assert result['people'][0]['new'] == []
            assert result['backlog_left'] == 1

    def test_zero_capacity_preserves_existing_work_and_reports_overload(self):
        carry = {'id': 1, 'points': 3, 'area_path': BACKEND, 'assigned_to': AVA['name'], 'assigned_unique': AVA['unique_name'], 'flags': []}
        result = sp.make_plan(people=[{**AVA, 'capacity_points': 0}], carried=[carry], planned=[], backlog=[], per_person=6, capacity_mode='points')
        row = result['people'][0]
        assert row['carried'] == [carry] and row['points_over_by'] == 3
        assert any('Capacity exceeded' in w for w in row['warnings'])
        assert any('Capacity exceeded' in w for w in sp._calculate_risks([row], [], [carry])[1])

    def test_oversized_first_story_does_not_hide_smaller_stories_that_fit(self):
        backlog = [{'id': i, 'points': pts, 'area_path': BACKEND, 'assigned_to': '', 'assigned_unique': '', 'flags': []} for i, pts in [(1, 13), (2, 3)]]
        result = sp.make_plan(people=[{**AVA, 'capacity_points': 5}], carried=[], planned=[], backlog=backlog, per_person=6, capacity_mode='points')
        assert [s['id'] for s in result['people'][0]['new']] == [2]
        assert [u['story']['id'] for u in result['unplaced']] == [1]

    def test_owner_uses_full_identity_before_display_names(self):
        people = [{'name': 'Same Name', 'unique_name': 'other@test'}, {'name': 'Same Name', 'unique_name': 'owner@test'}]
        assert sp._owner(people, {'assigned_to': 'Same Name', 'assigned_unique': 'owner@test'}) is people[1]
        assert sp._owner(people, {'assigned_to': 'Same Name', 'assigned_unique': 'absent@test'}) is None
        assert sp._owner(people, {'assigned_to': 'Same Name', 'assigned_unique': ''}) is None

    def test_owner_never_matches_email_prefixes_or_different_domains(self):
        people = [{'name': 'Alexandra Smith', 'unique_name': 'alexandra@test'}]
        assert sp._owner(people, {'assigned_unique': 'alex@test'}) is None
        assert sp._owner([{'name': 'Alex', 'unique_name': 'alex@a.test'}], {'assigned_unique': 'alex@b.test'}) is None

    def test_unique_only_outside_owner_is_not_treated_as_unassigned(self):
        carry = {'id': 1, 'points': 1, 'area_path': BACKEND, 'assigned_to': '', 'assigned_unique': 'unknown@test', 'flags': []}
        result = sp.make_plan(people=[AVA], carried=[carry], planned=[], backlog=[], per_person=6)
        assert result['outside_plan'] == [carry]
        assert result['people'][0]['new'] == []

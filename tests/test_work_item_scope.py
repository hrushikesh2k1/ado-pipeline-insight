from datetime import datetime, timezone

import pytest

import app.services.work_item_scope as scope
from app.services.work_item_scope import (
    StateMap,
    build_wiql,
    collect_scope_items,
    fetch_raw_items,
    keep_item,
    list_item_ids,
    load_state_map,
    normalize_item,
    parse_when,
    team_area_paths,
    window_start,
)
from wi_support import STATES, FakeAdo, http_error, raw_item

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class TestWindow:
    def test_six_months_back_starts_on_the_first_of_that_month(self):
        assert window_start(NOW, 6) == datetime(2026, 4, 1, tzinfo=timezone.utc)

    def test_it_crosses_the_year_boundary(self):
        assert window_start(datetime(2026, 1, 15, tzinfo=timezone.utc), 6) == datetime(2025, 7, 1, tzinfo=timezone.utc)

    def test_azure_devops_timestamps_with_seven_fraction_digits_are_read(self):
        assert parse_when("2026-04-01T10:00:00.1234567Z") == datetime(2026, 4, 1, 10, 0, 0, 123456, tzinfo=timezone.utc)
        assert parse_when("") is None and parse_when("not a date") is None


class TestStateMeaning:
    def test_closed_comes_from_the_state_category_not_the_name(self):
        states = StateMap({"Bug": {"Fixed and verified": "Completed", "Active": "InProgress"}})
        assert states.category("Bug", "Fixed and verified") == "completed"
        assert states.category("bug", "ACTIVE") == "inprogress"

    def test_a_state_azure_devops_did_not_describe_falls_back_to_its_common_name(self):
        states = StateMap({"Bug": {"Active": "InProgress"}})
        assert states.category("Epic", "Closed") == "completed"
        assert states.category("Epic", "Something custom") == "inprogress"

    def test_finished_states_cover_every_type_and_keep_their_spelling(self):
        states = load_state_map(FakeAdo([]), "Proj")
        assert states.finished_state_names() == ["Closed", "Done", "Removed"]

    def test_when_the_states_cannot_be_read_the_common_names_are_used(self):
        states = load_state_map(FakeAdo([], states_fail=True), "Proj")
        assert states.finished_state_names() == ["Closed", "Done", "Completed", "Removed"]


class TestQuery:
    def query(self, **kw):
        base = dict(areas=[], tag="", months=6, finished_states=["Closed", "Removed"])
        return build_wiql("Proj", **{**base, **kw})

    def test_open_items_of_any_age_or_changed_within_the_window(self):
        q = self.query()
        assert "[System.TeamProject] = 'Proj'" in q
        assert "[System.ChangedDate] >= @StartOfMonth - 6 OR [System.State] NOT IN ('Closed', 'Removed')" in q
        assert q.endswith("ORDER BY [System.Id]")

    def test_team_areas_and_tag_are_optional_and_added_when_given(self):
        assert "AreaPath" not in self.query() and "Tags" not in self.query()
        q = self.query(areas=[("Proj\\Monitoring", True), ("Proj\\Ops", False)], tag="monitoring")
        assert "([System.AreaPath] UNDER 'Proj\\Monitoring' OR [System.AreaPath] = 'Proj\\Ops')" in q
        assert "[System.Tags] CONTAINS 'monitoring'" in q

    def test_quotes_in_names_cannot_break_the_query(self):
        q = self.query(tag="o'brien")
        assert "CONTAINS 'o''brien'" in q
        assert "'it''s'" in build_wiql("Proj", areas=[], tag="", months=1, finished_states=["it's"])
        assert "'O''Neil Project'" in build_wiql("O'Neil Project", areas=[], tag="", months=1, finished_states=["Closed"])

    def test_paging_continues_after_the_last_id(self):
        assert "[System.Id] > 40" in self.query(after_id=40)
        assert "[System.Id] >" not in self.query()


class TestIdPaging:
    def test_every_page_is_read_until_a_short_page(self, monkeypatch):
        ado = FakeAdo([raw_item(i) for i in range(1, 13)])
        monkeypatch.setattr(scope, "ID_PAGE", 5)
        ids = list_item_ids(ado, "Proj", areas=[], tag="", months=6, finished_states=["Closed"])
        assert ids == list(range(1, 13))
        assert len(ado.queries) == 3 and [t for _q, t in ado.queries] == [5, 5, 5]

    def test_a_page_that_is_too_big_is_halved(self, monkeypatch):
        ado = FakeAdo([raw_item(i) for i in range(1, 9)], wiql_error=lambda top: http_error(400) if top and top > 3 else None)
        monkeypatch.setattr(scope, "ID_PAGE", 8)
        monkeypatch.setattr(scope, "MIN_ID_PAGE", 2)
        ids = list_item_ids(ado, "Proj", areas=[], tag="", months=6, finished_states=["Closed"])
        assert ids == list(range(1, 9))
        assert [t for _q, t in ado.queries][:2] == [8, 4]

    def test_a_rejected_token_is_not_retried_with_smaller_pages(self):
        ado = FakeAdo([raw_item(1)], wiql_error=lambda top: http_error(401))
        with pytest.raises(Exception):
            list_item_ids(ado, "Proj", areas=[], tag="", months=6, finished_states=["Closed"])
        assert len(ado.queries) == 1


class TestFieldsAndBatches:
    def test_items_are_read_in_batches_of_200(self):
        ado = FakeAdo([raw_item(i) for i in range(1, 451)])
        assert len(fetch_raw_items(ado, "Proj", list(range(1, 451)))) == 450
        assert [len(b) for b, _f in ado.batches] == [200, 200, 50]

    def test_a_process_without_the_optional_fields_still_works(self):
        ado = FakeAdo([raw_item(i) for i in range(1, 401)], reject_optional=True)
        assert len(fetch_raw_items(ado, "Proj", list(range(1, 401)))) == 400
        fields = [f for _b, f in ado.batches]
        assert fields[0] == scope.FIELDS_FULL and fields[1] == scope.FIELDS_SAFE and fields[2] == scope.FIELDS_SAFE

    def test_a_rejected_token_is_not_mistaken_for_a_missing_field(self):
        class Denied(FakeAdo):
            def get_work_items_batch(self, *a, **k):
                raise http_error(401)

        with pytest.raises(Exception):
            fetch_raw_items(Denied([]), "Proj", [1])


class TestNormalize:
    states = StateMap(STATES)

    def test_a_person_a_sprint_and_plain_text_description(self):
        item = normalize_item(raw_item(7, assigned={"displayName": "Asha Rao", "uniqueName": "asha@x.com"}, iteration="Proj\\2026\\Sprint 5",
                                       description="<div>VPN <b>drops</b></div><br>every hour</div>"), self.states)
        assert item["assigned_to"] == "Asha Rao"
        assert item["sprint"] == "2026\\Sprint 5"
        assert item["description"] == "VPN drops\nevery hour"

    def test_unassigned_and_an_item_still_in_the_root_iteration(self):
        item = normalize_item(raw_item(7, assigned=None, iteration="Proj"), self.states)
        assert item["assigned_to"] == "Unassigned" and item["sprint"] == "No sprint"

    def test_a_text_identity_loses_its_email(self):
        assert normalize_item(raw_item(7, assigned="Asha Rao <asha@x.com>"), self.states)["assigned_to"] == "Asha Rao"

    def test_the_closing_date_is_the_closed_date_then_the_state_change_then_the_last_change(self):
        a = normalize_item(raw_item(1, state="Closed", closed="2026-08-01T09:00:00Z", state_change="2026-08-02T09:00:00Z"), self.states)
        b = normalize_item(raw_item(2, state="Closed", state_change="2026-08-02T09:00:00Z", changed="2026-08-03T09:00:00Z"), self.states)
        c = normalize_item(raw_item(3, state="Closed", changed="2026-08-03T09:00:00Z"), self.states)
        assert [x["closed"] for x in (a, b, c)] == ["2026-08-01T09:00:00Z", "2026-08-02T09:00:00Z", "2026-08-03T09:00:00Z"]

    def test_an_open_item_has_no_closing_date(self):
        assert normalize_item(raw_item(1, state="Active", closed="2026-08-01T09:00:00Z"), self.states)["closed"] is None

    def test_a_bug_with_only_repro_steps_uses_them_as_its_text(self):
        assert normalize_item(raw_item(1, repro="<p>Open the portal</p>"), self.states)["description"] == "Open the portal"

    def test_tags_are_split_and_the_description_is_capped(self):
        item = normalize_item(raw_item(1, tags="monitoring; vpn ;", description="x" * 5000), self.states)
        assert item["tags"] == ["monitoring", "vpn"] and len(item["description"]) == scope.DESCRIPTION_CHARS


class TestExactScope:
    states = StateMap(STATES)
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)

    def keep(self, raw, tag="", scopes=None):
        item = normalize_item(raw, self.states)
        return keep_item(item, start=self.start, tag=tag, team_scopes=scopes or [])

    def test_open_work_is_kept_however_old(self):
        assert self.keep(raw_item(1, state="Active", created="2020-01-01T00:00:00Z"))

    def test_closed_work_is_kept_only_when_it_closed_inside_the_window(self):
        assert self.keep(raw_item(1, state="Closed", closed="2026-04-02T00:00:00Z"))
        assert not self.keep(raw_item(2, state="Closed", closed="2026-03-31T23:59:59Z"))

    def test_removed_work_is_never_counted(self):
        assert not self.keep(raw_item(1, state="Removed"))

    def test_a_tag_must_match_exactly_whatever_the_query_returned(self):
        assert self.keep(raw_item(1, tags="Monitoring; vpn"), tag="monitoring")
        assert not self.keep(raw_item(2, tags="monitoring-extra"), tag="monitoring")
        assert not self.keep(raw_item(3, tags="vpn"), tag="monitoring")

    def test_a_team_keeps_only_its_area_paths(self):
        scopes = [("proj\\monitoring", True)]
        assert self.keep(raw_item(1, area="Proj\\Monitoring\\VPN"), scopes=scopes)
        assert not self.keep(raw_item(2, area="Proj\\Platform"), scopes=scopes)


class TestCollect:
    def test_a_team_scope_is_read_from_its_area_paths(self):
        assert team_area_paths({"values": [{"value": "P\\A", "includeChildren": True}, {"value": "P\\B"}]}) == [("P\\A", True), ("P\\B", False)]
        assert team_area_paths({"defaultValue": "P\\Default"}) == [("P\\Default", False)]
        assert team_area_paths(None) == []

    def test_the_scope_is_everything_open_plus_what_closed_in_the_window(self):
        ado = FakeAdo([
            raw_item(1, state="Active", created="2025-01-01T00:00:00Z"),
            raw_item(2, state="Closed", closed="2026-08-01T00:00:00Z"),
            raw_item(3, state="Closed", closed="2026-01-01T00:00:00Z"),
            raw_item(4, state="Removed"),
            raw_item(5, state="Active", tags="other"),
        ])
        items = collect_scope_items(ado, "Proj", tag="monitoring", now=NOW)
        assert sorted(i["id"] for i in items) == [1, 2]

    def test_no_team_and_no_tag_means_the_whole_project(self):
        ado = FakeAdo([raw_item(1, tags="", area="Proj\\Anywhere"), raw_item(2, tags="x", area="Proj\\Else")])
        assert len(collect_scope_items(ado, "Proj", now=NOW)) == 2
        assert "AreaPath" not in ado.queries[0][0] and "Tags" not in ado.queries[0][0]

    def test_a_team_filters_by_its_area_paths(self):
        ado = FakeAdo([raw_item(1, area="Proj\\Monitoring\\VPN"), raw_item(2, area="Proj\\Platform")])
        items = collect_scope_items(ado, "Proj", team="Monitoring Team", now=NOW)
        assert [i["id"] for i in items] == [1]
        assert "UNDER 'Proj\\Monitoring'" in ado.queries[0][0]

    def test_a_team_that_cannot_be_read_is_an_error_not_the_whole_project(self):
        with pytest.raises(ValueError, match="area paths of team 'Ghost'"):
            collect_scope_items(FakeAdo([raw_item(1)], team_fields=http_error(404)), "Proj", team="Ghost", now=NOW)
        with pytest.raises(ValueError, match="has no area paths"):
            collect_scope_items(FakeAdo([raw_item(1)], team_fields={}), "Proj", team="Empty", now=NOW)

    def test_progress_is_reported(self):
        seen = []
        collect_scope_items(FakeAdo([raw_item(i) for i in range(1, 4)]), "Proj", now=NOW, progress=lambda p, d, t: seen.append((p, d, t)))
        assert seen and seen[-1] == ("reading", 3, 3)
